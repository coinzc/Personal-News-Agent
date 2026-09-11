from pydantic import BaseModel, ConfigDict, Field


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4_000)
    session_key: str = Field(default="default", min_length=1, max_length=255)


class AgentChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    conversation_id: str | None = None
    tool_calls: list[dict[str, object]] = Field(default_factory=list)
