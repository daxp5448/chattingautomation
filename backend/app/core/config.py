from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "KelvionTech WhatsApp Restaurant Platform"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"

    # Root logger level (see logging.basicConfig(...) call in app/main.py). Standard
    # library level names ("DEBUG", "INFO", "WARNING", ...) as accepted by `logging`.
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/kelviontech"

    # No functional default: an unset value fails Settings() construction at import
    # time instead of silently signing tokens with a known, public placeholder string.
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 14

    # Symmetric key used to encrypt WhatsApp access tokens at rest (Fernet key). No
    # working default -- must be supplied via env/`.env`. An empty/invalid value makes
    # Fernet(...) raise loudly at import time in app/core/security.py rather than
    # silently encrypting secrets with a key that ships in source control.
    FIELD_ENCRYPTION_KEY: str = ""

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # "local" writes/reads uploaded images straight to disk (LOCAL_MEDIA_DIR below) -- no
    # MinIO/S3 needed for local dev. Switch to "s3" once a real bucket/MinIO is actually
    # reachable; every S3_* setting below is then used exactly as before. See
    # app/services/image_storage_service.py, which is the only thing that branches on this.
    STORAGE_BACKEND: str = "local"
    # Folder uploaded image bytes are written to when STORAGE_BACKEND="local" -- relative
    # paths resolve against the backend process's working directory (normally
    # `backend/`), matching how DATABASE_URL-less sqlite paths already behave elsewhere in
    # this file. Created automatically on first write; safe to point at a bind-mounted
    # volume in a real deployment.
    LOCAL_MEDIA_DIR: str = "media_storage"

    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET: str = "kelviontech-media"
    S3_REGION: str = "us-east-1"

    # The public, internet-reachable base URL demo/catalog image links are built from --
    # deliberately separate from S3_ENDPOINT_URL (which the backend uses to talk to
    # MinIO/S3 directly, e.g. over a private/local address that's never meant to be
    # public). Meta's servers fetch WhatsApp message images directly from whatever URL is
    # stored, so this must be reachable from the internet -- either the same publicly
    # tunnelled URL the webhook already needs (see app/api/v1/routers/media.py, a
    # passthrough so images ride that one tunnel instead of needing a second one pointed
    # at MinIO directly: set this to "<your-ngrok-or-prod-domain>/api/v1/media") or a real
    # public bucket's own URL. Local default points straight at MinIO for same-machine
    # testing, where "reachable from the internet" doesn't matter yet. See
    # app/niche_seeds/_media.py for where this is consumed.
    PUBLIC_MEDIA_BASE_URL: str = "http://localhost:9000/kelviontech-media"

    # The public, internet-reachable base URL for this backend's own API -- same tunnel
    # PUBLIC_MEDIA_BASE_URL rides (that setting is literally "<this>/media"), but needed as
    # its own value now that a second consumer exists: WhatsApp Flow endpoint_uri (see
    # app/api/v1/routers/whatsapp_flow.py), which Meta calls directly and so must be a real
    # public URL, not the local dev address FastAPI itself binds to. Update alongside
    # PUBLIC_MEDIA_BASE_URL whenever the tunnel URL changes.
    PUBLIC_API_BASE_URL: str = "http://localhost:8000/api/v1"

    WHATSAPP_GRAPH_API_VERSION: str = "v20.0"
    WHATSAPP_APP_SECRET: str = ""
    # Verify token configured on the single Meta App webhook subscription (App dashboard).
    # This is app-level, not per-restaurant: Meta calls one webhook URL for the whole app;
    # which restaurant a message belongs to is resolved per-message via phone_number_id.
    # No working default -- must be supplied via env/`.env`.
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: str = ""

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Base URL of the owner/admin frontend, used to build the one-time account-setup
    # link returned from POST /restaurants (see app/api/v1/routers/restaurants.py and
    # app/core/security.py:generate_setup_token).
    FRONTEND_URL: str = "http://localhost:3000"

    # Generic SMTP -- works with Gmail (app password), SendGrid/SES/Mailgun SMTP relay,
    # or any other provider, so there's no vendor lock-in baked into the code. Empty
    # SMTP_HOST means "not configured": app/services/email_service.py no-ops with a
    # logged warning instead of failing whatever triggered the send (restaurant
    # creation, a status change) -- same resilience pattern as storage_service.py when
    # MinIO/S3 isn't reachable.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "noreply@kelviontech.dev"
    SMTP_FROM_NAME: str = "KelvionTech Platform"

    # Sentry error tracking. Empty means "not configured": app/main.py skips
    # sentry_sdk.init(...) entirely, same no-op-when-unset pattern as SMTP_HOST above and
    # WHATSAPP_APP_SECRET below -- optional observability, not a hard requirement to boot.
    SENTRY_DSN: str = ""


# Placeholder strings that used to be hardcoded, functional defaults for the secrets
# above. Kept only so the production startup check (app/main.py) can catch an operator
# who copy-pasted one of them into a real environment instead of generating a real
# secret.
INSECURE_PLACEHOLDER_SECRETS = {"change-me-in-production", "change-me-verify-token", ""}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
