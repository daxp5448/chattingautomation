import os
import tempfile
from pathlib import Path

# Outside the project folder (which lives under OneDrive) on purpose: OneDrive's real-time
# sync intercepting writes to a rapidly-rewritten SQLite file caused intermittent
# "database is locked" / "no such table" / PermissionError test flakiness -- the same class
# of issue that also broke the frontend's webpack cache (see that fix: node_modules/.next
# relocated the same way). The OS temp dir is never OneDrive-synced.
TEST_DB_PATH = Path(tempfile.gettempdir()) / "kelviontech_test_db.sqlite3"

# Must be set before any `app.*` module is imported, since Settings() and the SQLAlchemy
# engine are both created at import time. No Postgres/Docker in this dev environment, so
# the test suite runs against SQLite via the portable GUID column type (app/db/types.py).
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["FIELD_ENCRYPTION_KEY"] = "3Zk1v3q8bV3z8mYw5s9nqz1yqjq9m0iFhZ2xW8pQeQ8="
os.environ["WHATSAPP_APP_SECRET"] = "test-app-secret"
os.environ["WHATSAPP_WEBHOOK_VERIFY_TOKEN"] = "test-verify-token"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.restaurant_repository import _phone_number_id_cache  # noqa: E402
from app.services import broadcast_service, image_pipeline, image_storage_service, storage_service  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_restaurant_cache():
    """`_phone_number_id_cache` (app/repositories/restaurant_repository.py) is a
    module-level, process-wide TTL cache, same lifetime concern as the rate limiter above.
    Several test files reuse the same literal phone_number_id constant (e.g.
    "TEST_PHONE_NUMBER_ID"), and `_fresh_schema` below drops/recreates the DB every test --
    without clearing the cache too, a later test's webhook call could be served a cached
    Restaurant row from a *previous* test whose underlying DB row (and restaurant_id FK
    target) no longer exists.
    """
    _phone_number_id_cache.clear()
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """The Limiter (app/core/rate_limit.py) uses in-memory storage keyed off client
    address, and that single instance is imported once and shared for the whole pytest
    process. Without resetting it, /auth/register and /auth/login's 5/minute limit would
    accumulate hits across unrelated tests (and files) that all appear to originate from
    the same test-client address, causing unrelated tests to start failing with 429s.
    """
    limiter.reset()
    yield


@pytest.fixture(autouse=True)
def _fake_storage(monkeypatch):
    """No MinIO/S3 running in the test environment; storage_service.upload_bytes is
    only ever best-effort (invoice attachment), so tests shouldn't depend on it or
    pay for its real (failing) connection attempt.
    """
    monkeypatch.setattr(storage_service, "upload_bytes", lambda key, content, content_type, **kw: f"https://fake-storage.test/{key}")


@pytest.fixture(autouse=True)
def _fake_image_storage(monkeypatch):
    """No MinIO/S3 running in the test environment. Unlike storage_service.py's
    best-effort fake above (which just returns a stub URL string), the image pipeline's
    storage is a hard dependency whose whole point is durable round-tripping -- variant
    generation and re-crop both download the original back -- so this is a real in-memory
    fake store, not just a URL stub. See app/services/image_storage_service.py.
    """
    store: dict[str, bytes] = {}

    def _upload(key: str, content: bytes, content_type: str) -> None:
        store[key] = content

    def _download(key: str) -> bytes:
        if key not in store:
            raise image_storage_service.ImageStorageError(f"no such key in fake store: {key}")
        return store[key]

    def _public_url(key: str) -> str:
        return f"https://fake-image-storage.test/{key}"

    monkeypatch.setattr(image_storage_service, "upload_bytes", _upload)
    monkeypatch.setattr(image_storage_service, "download_bytes", _download)
    monkeypatch.setattr(image_storage_service, "public_url", _public_url)


@pytest.fixture(autouse=True)
def _sync_image_processing(monkeypatch):
    """Real Celery/Redis aren't running in the test environment. Runs image processing
    synchronously on the caller's own event loop instead of dispatching to a broker, so
    upload/crop tests can assert on status="ready" immediately -- see
    app/services/image_pipeline.py::enqueue_processing's docstring for why this (an
    awaited coroutine substituted in place of the real one) avoids nesting a second
    asyncio.run() inside the request's already-running event loop, unlike naively
    enabling Celery's eager mode would.
    """
    async def _run_now(image_id):
        await image_pipeline.process_image(image_id)

    monkeypatch.setattr(image_pipeline, "enqueue_processing", _run_now)


@pytest.fixture(autouse=True)
def _sync_broadcast_dispatch(monkeypatch):
    """Same reasoning as `_sync_image_processing` above: no real Celery broker/worker
    runs in the test environment, so a router calling `.delay()` directly would try (and
    fail) to connect to Redis. Runs the send synchronously on the caller's own event loop
    instead -- see app/services/broadcast_service.py::enqueue_broadcast_send's docstring.

    Also swaps the real GraphAPIWhatsAppSender for an in-memory one and zeroes the
    inter-send pacing delay, so a router test that incidentally triggers a real send
    (rather than calling the send task directly with its own explicit mocks) never
    attempts a real network call to Meta or waits out a real sleep.
    """
    from app.services.whatsapp_client import InMemoryWhatsAppSender
    from app.tasks import broadcast_sender

    monkeypatch.setattr(broadcast_sender, "_sender", InMemoryWhatsAppSender())
    monkeypatch.setattr(broadcast_sender, "SEND_PACING_SECONDS", 0)

    async def _run_now(campaign_id):
        await broadcast_sender._send_broadcast_campaign(str(campaign_id))

    monkeypatch.setattr(broadcast_service, "enqueue_broadcast_send", _run_now)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_schema():
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
