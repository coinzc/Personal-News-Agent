"""Outbound message channels."""

from app.channels.base import ChannelError, MessageChannel, MessageResult
from app.channels.digest_delivery import DigestDeliveryService
from app.channels.wechat import WeChatAdapter
from app.channels.wecom import WeComGroupBotAdapter

__all__ = [
    "ChannelError",
    "DigestDeliveryService",
    "MessageChannel",
    "MessageResult",
    "WeChatAdapter",
    "WeComGroupBotAdapter",
]
