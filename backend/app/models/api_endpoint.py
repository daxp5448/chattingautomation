from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApiEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A Super-Admin-curated allowlist entry a flow's API_CALL step may reference --
    mirrors NicheTemplate/ImageTypeProfile's "Super Admin curates, business consumes"
    pattern. A business/flow author never types a raw URL; they pick from this catalog
    in the visual builder. See app/services/api_endpoint_client.py for why this alone
    isn't sufficient SSRF protection (an approved hostname can still repoint via DNS
    after approval) and what additionally happens at actual call time.

    `capturable_context_keys` is a closed allowlist of GenericConversationState.context
    keys this endpoint is allowed to receive -- request bodies are ALWAYS the fixed shape
    `{"context": {k: context.get(k) for k in capturable_context_keys}}`. There is no
    templating/interpolation into the URL, path, query string, or headers anywhere --
    closing a header/URL-injection surface independent of the endpoint allowlist itself.
    """

    __tablename__ = "api_endpoints"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    method: Mapped[str] = mapped_column(String(10), default="POST", nullable=False)
    # A small fixed set of header names Super Admin explicitly approves sending to this
    # endpoint (e.g. an API key) -- values live here, never sourced from customer/flow
    # context, so there is no injection path through them.
    allowed_headers: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    capturable_context_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    timeout_seconds: Mapped[float] = mapped_column(default=5.0, nullable=False)
    response_size_cap_bytes: Mapped[int] = mapped_column(Integer, default=65536, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
