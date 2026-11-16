from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import require_wechat_webhook_token
from app.schemas.wechat import WeChatInboundMessage, WeChatInboundResponse

router = APIRouter(prefix="/api/wechat", tags=["wechat"])


@router.post("/webhook", response_model=WeChatInboundResponse)
async def webhook(
    payload: WeChatInboundMessage,
    request: Request,
    _: None = Depends(require_wechat_webhook_token),
) -> WeChatInboundResponse:
    container = getattr(request.app.state, "container", None)
    if container is None or not container.agent_available:
        raise HTTPException(status_code=503, detail="Agent service is not configured")
    session_key = payload.session_key or f"wechat:{payload.sender_id}"
    result = await container.chat(payload.content, session_key=session_key)
    return WeChatInboundResponse(
        content=result.content,
        conversation_id=str(result.conversation_id) if result.conversation_id else None,
    )
