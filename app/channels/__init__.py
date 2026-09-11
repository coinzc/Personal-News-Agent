"""Outbound message channels."""

from app.channels.base import ChannelError, MessageChannel, MessageResult
from app.channels.digest_delivery import DigestDeliveryService
from app.channels.wechat import WeChatAdapter

__all__ = ["ChannelError", "DigestDeliveryService", "MessageChannel", "MessageResult", "WeChatAdapter"]
