from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if not settings.DATABASE_URL.startswith("sqlite"):
    # SQLite (used for the test suite, see app/tests/conftest.py) is engine-created with
    # SingletonThreadPool/StaticPool, which reject pool_size/max_overflow outright
    # (create_engine raises TypeError) -- these only apply to the QueuePool a real Postgres
    # deployment uses. Sized for concurrent webhook traffic across ~50-100 tenants sharing
    # this one process; the default pool_size=5 would starve fast under that load.
    _engine_kwargs["pool_size"] = 20
    _engine_kwargs["max_overflow"] = 20
else:
    # aiosqlite's default pool reuses a single physical connection tied to a background
    # thread; a test that fires many concurrent-ish requests through the ASGI test client
    # (e.g. a webhook + several follow-up API calls in one test) can trigger a pool
    # checkout/reconnect from outside the SQLAlchemy greenlet context, raising
    # `MissingGreenlet` on an otherwise-correct test. NullPool opens a fresh connection
    # per checkout and closes it immediately after, which is slightly slower but sidesteps
    # that entirely -- fine for a test-only SQLite database, never used against Postgres.
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
