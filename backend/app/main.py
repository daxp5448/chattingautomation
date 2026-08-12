import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.v1.api import api_router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import AsyncSessionLocal
from app.services.payment import cod  # noqa: F401 -- registers the COD payment gateway

# Must run before any request-handling code (and before the FastAPI(...) app below is
# constructed) so every `logging.getLogger(__name__)` created anywhere in the app --
# including in modules imported above -- picks up this format/level instead of silently
# falling back to Python's bare, timestamp-less, WARNING-only lastResort handler.
logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)

if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT, traces_sample_rate=0.1)

# Secrets that MUST be explicitly configured (non-empty) before this app is allowed to
# serve traffic in production. JWT_SECRET_KEY has no default at all (Settings() already
# fails to construct if it's missing), but an operator could still explicitly set it to
# "" in the environment, so it's checked here too for defense in depth.
_REQUIRED_PRODUCTION_SECRETS = ("JWT_SECRET_KEY", "FIELD_ENCRYPTION_KEY", "WHATSAPP_WEBHOOK_VERIFY_TOKEN")

# Substrings that suggest DATABASE_URL is still pointed at a local/default database
# rather than a real production one. Not a hard failure -- a legitimate deploy can run
# Postgres on the same host as the app (so "localhost"/"127.0.0.1" alone isn't proof of
# misconfiguration) -- just a loud heads-up so an operator who forgot to update it notices
# before customer data ends up in a throwaway local database.
_LOCAL_DATABASE_URL_MARKERS = ("localhost", "127.0.0.1", "postgres:postgres@")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT == "production":
        missing = [name for name in _REQUIRED_PRODUCTION_SECRETS if not getattr(settings, name, "")]
        if missing:
            raise RuntimeError(
                "Refusing to start in production with missing required secret(s): "
                f"{', '.join(missing)}. Set these via environment/.env before serving traffic."
            )
        if any(marker in settings.DATABASE_URL for marker in _LOCAL_DATABASE_URL_MARKERS):
            logger.warning(
                "DATABASE_URL looks like it might still be pointed at a local/default "
                "database while ENVIRONMENT=production. If this is intentional (e.g. "
                "Postgres colocated on the same host), ignore this warning -- otherwise "
                "double-check DATABASE_URL before serving real traffic."
            )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    **({"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.ENVIRONMENT == "production" else {}),
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Only sent in production: HSTS over plain http in local dev would tell the browser to
    # force https on localhost, which actively breaks non-TLS local development.
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health() -> JSONResponse:
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.error("Health check DB connectivity failed", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok"})


# Meta requires a reachable Privacy Policy URL before an app can be switched to Live
# mode. This is a generic, app-level policy (not per-restaurant) -- good enough to
# satisfy that requirement for WhatsApp Cloud API testing/production use.
_PRIVACY_POLICY_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Privacy Policy — KelvionTech WhatsApp Restaurant Platform</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; color: #1f2937; line-height: 1.6; }
    h1 { font-size: 1.5rem; } h2 { font-size: 1.1rem; margin-top: 1.5rem; }
  </style>
</head>
<body>
  <h1>Privacy Policy</h1>
  <p>This policy covers the KelvionTech WhatsApp ordering platform and any restaurant using it to
  take orders over WhatsApp.</p>

  <h2>What we collect</h2>
  <p>When you message a restaurant on WhatsApp through this platform, we store your WhatsApp phone
  number, name (if provided), messages exchanged with the bot, and order history (items, delivery
  address, payment status) so the restaurant can fulfill your order and provide support.</p>

  <h2>How we use it</h2>
  <p>Data is used only to process orders, respond to your messages, and operate loyalty/coupon
  features for the specific restaurant you're messaging. We do not sell or share your data with
  third parties, except payment processors (e.g. Razorpay) strictly to complete a transaction you
  initiated.</p>

  <h2>Data retention</h2>
  <p>Order and conversation history is retained for as long as your account with the restaurant is
  active, so order history and loyalty points remain accurate.</p>

  <h2>Contact</h2>
  <p>To request access to or deletion of your data, contact the restaurant you ordered from directly
  via the support number in their WhatsApp bot.</p>
</body>
</html>
"""


@app.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    return _PRIVACY_POLICY_HTML
