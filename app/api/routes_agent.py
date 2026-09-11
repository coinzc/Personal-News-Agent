from fastapi import APIRouter, HTTPException, Request

from app.schemas.agent import AgentChatRequest, AgentChatResponse

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatResponse)
async def chat(payload: AgentChatRequest, request: Request) -> AgentChatResponse:
    container = getattr(request.app.state, "container", None)
    if container is None or not container.agent_available:
        raise HTTPException(status_code=503, detail="Agent service is not configured")
    result = await container.chat(payload.message, session_key=payload.session_key)
    return AgentChatResponse(
        content=result.content,
        conversation_id=str(result.conversation_id) if result.conversation_id else None,
        tool_calls=result.tool_calls,
    )
