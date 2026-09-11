from fastapi import APIRouter, Header, HTTPException, Request

from app.schemas.wechat import WeChatInboundMessage, WeChatInboundResponse

router = APIRouter(prefix="/api/wechat", tags=["wechat"])


@router.post("/webhook", response_model=WeChatInboundResponse)
async def webhook(
    payload: WeChatInboundMessage,
    request: Request,
    x_wechat_webhook_token: str | None = Header(default=None),
) -> WeChatInboundResponse:
    settings = request.app.state.settings
    expected = settings.wechat_webhook_token
    if expected and x_wechat_webhook_token != expected.get_secret_value():
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    container = getattr(request.app.state, "container", None)
    if container is None or not container.agent_available:
        raise HTTPException(status_code=503, detail="Agent service is not configured")
    session_key = payload.session_key or f"wechat:{payload.sender_id}"
    result = await container.chat(payload.content, session_key=session_key)
    return WeChatInboundResponse(
        content=result.content,
        conversation_id=str(result.conversation_id) if result.conversation_id else None,
    )
