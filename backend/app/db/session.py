import sys
from collections.abc import AsyncGenerator

from sqlalchemy import event
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
elif "pytest" in sys.modules:
    # aiosqlite's default pool reuses a single physical connection tied to a background
    # thread; a test that fires many concurrent-ish requests through the ASGI test client
    # (e.g. a webhook + several follow-up API calls in one test) can trigger a pool
    # checkout/reconnect from outside the SQLAlchemy greenlet context, raising
    # `MissingGreenlet` on an otherwise-correct test. NullPool opens a fresh connection
    # per checkout and closes it immediately after, which sidesteps that entirely.
    #
    # Deliberately gated on "are we actually running under pytest" (conftest.py imports
    # this exact module, so sys.modules already has pytest in it by then), NOT just "is
    # this a sqlite URL" -- local dev also runs on sqlite (dev.db), and unconditionally
    # applying NullPool there meant EVERY authenticated request paid the cost of opening
    # and closing a brand new file connection from scratch, every single time, instead of
    # reusing one. On Windows that's not "slightly slower" as the original comment assumed
    # -- real-time antivirus scanning a freshly-opened file on every single request made
    # every authenticated endpoint consistently ~4 SECONDS slower than an unauthenticated
    # one that never touched the DB, which is exactly the "why is nothing loading" symptom
    # this was silently causing. Real dev/prod SQLite now gets SQLAlchemy's normal default
    # pool (reuses connections) like any other engine.
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

if settings.DATABASE_URL.startswith("sqlite"):
    # WAL mode lets readers and a writer proceed concurrently against the same file
    # (the default rollback-journal mode takes an exclusive lock for the whole duration
    # of any write transaction, blocking every other connection's reads until it
    # commits) -- real latency under the concurrent webhook + dashboard-polling traffic
    # this file's own pool_size comment above describes. synchronous=NORMAL is WAL's
    # documented safe pairing (still fsyncs at checkpoints; only relaxes the guarantee
    # for the now-much-rarer case of an OS crash, not an app crash) -- see
    # https://sqlite.org/pragma.html#pragma_synchronous. Set once per raw DBAPI
    # connection as it's created (fired for every pooled connection, not just the
    # first), since PRAGMAs are per-connection state, not persisted in the file itself
    # for synchronous (WAL mode itself IS persisted in the file after the first set,
    # but setting it again is a harmless no-op).
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
