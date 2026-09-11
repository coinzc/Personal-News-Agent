from pydantic import BaseModel, ConfigDict, Field


class WeChatInboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender_id: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=4_000)
    session_key: str | None = Field(default=None, max_length=255)


class WeChatInboundResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str
    conversation_id: str | None = None
