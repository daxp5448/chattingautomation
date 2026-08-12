"""Shared slowapi Limiter instance.

Lives in its own module (rather than being created in app/main.py or
app/api/v1/routers/auth.py) so both can import the *same* instance without a circular
import: app/main.py needs it to wire app.state.limiter / the exception handler /
SlowAPIMiddleware, and the route modules need it to apply `@limiter.limit(...)`
decorators, but app/main.py imports the API router tree (which pulls in the route
modules) at module load time.
"""

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# In-memory storage (slowapi's default) only rate-limits correctly within a single
# process: with N backend replicas each keeping its own independent counter, the
# configured limit is effectively multiplied by N. Redis-backed storage shares one
# counter across every process/replica instead.
#
# Skipped under pytest: PYTEST_VERSION is set by pytest itself for the whole run, before
# any app module is imported (see https://docs.pytest.org/en/stable/reference/reference.html#envvar-PYTEST_VERSION),
# so this reliably detects "running under the test suite" regardless of import order.
# app/tests/conftest.py runs the suite against SQLite with no Redis server available;
# forcing Redis storage there would make every rate-limited endpoint (login, register,
# webhook, refresh, setup) fail its first request instead of just skipping the
# multi-process guarantee this switch exists for. Production/staging (run outside
# pytest) always gets real Redis-backed storage.
_storage_uri = None if os.environ.get("PYTEST_VERSION") else settings.REDIS_URL

# in_memory_fallback_enabled: if Redis is reachable (production/Docker), rate limiting
# stays Redis-backed and correct across every process/replica, unaffected. If Redis is
# unreachable (e.g. local dev without Docker -- the README's "Local development without
# Docker" path never starts Redis), slowapi catches the connection error and degrades to
# per-process in-memory limiting instead of the request failing with an unhandled 500 --
# discovered when this broke login entirely on a machine with no Redis/Docker available.
limiter = Limiter(key_func=get_remote_address, storage_uri=_storage_uri, in_memory_fallback_enabled=True)
