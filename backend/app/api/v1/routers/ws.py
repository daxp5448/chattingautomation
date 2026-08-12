import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.display_tokens import hash_display_token
from app.core.security import decode_token
from app.core.ws_manager import manager
from app.db.session import AsyncSessionLocal
from app.models.enums import UserRole
from app.repositories.display_device_repository import DisplayDeviceRepository
from app.repositories.user_repository import UserRepository

router = APIRouter(prefix="/ws", tags=["websocket"])


@router.websocket("/restaurants/{restaurant_id}/orders")
async def orders_ws(
    websocket: WebSocket,
    restaurant_id: uuid.UUID,
    token: str | None = Query(None),
    device_token: str | None = Query(None),
):
    # Browsers can't set headers on the WebSocket handshake, so the auth secret travels
    # as a query param instead. Two mutually exclusive auth paths share this one socket:
    # `token` is a staff JWT (validated the same way as the REST Authorization header),
    # `device_token` is a POS/kitchen display's raw device token (hashed and matched
    # against an active, non-revoked DisplayDevice for this restaurant). Either way the
    # connection only ever *receives* broadcast events below -- it never reads anything
    # the client sends, so a POS connection has no way to mutate state over this socket.
    if device_token is not None:
        async with AsyncSessionLocal() as session:
            device = await DisplayDeviceRepository(session).get_active_by_token_hash(
                hash_display_token(device_token), restaurant_id
            )
        if not device:
            await websocket.close(code=4401)
            return

        await manager.connect(restaurant_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(restaurant_id, websocket)
        return

    if not token:
        await websocket.close(code=4401)
        return
    try:
        claims = decode_token(token)
    except ValueError:
        await websocket.close(code=4401)
        return
    if claims.get("type") != "access":
        await websocket.close(code=4401)
        return

    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get(uuid.UUID(claims["sub"]))

    if not user or not user.is_active:
        await websocket.close(code=4401)
        return
    if user.role != UserRole.SUPER_ADMIN and user.restaurant_id != restaurant_id:
        await websocket.close(code=4403)
        return

    await manager.connect(restaurant_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(restaurant_id, websocket)
