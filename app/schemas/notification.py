"""Notification request/response schemas."""

from datetime import datetime

from pydantic import BaseModel
from app.schemas.base import ORMBase

from app.models.enums import NotificationType


class NotificationRead(ORMBase):

    id: int
    type: NotificationType
    title: str
    body: str
    is_read: bool
    read_at: datetime | None
    actor_id: int | None
    entity_type: str
    entity_id: int
    created_at: datetime


class NotificationUpdate(BaseModel):
    is_read: bool


class UnreadCountRead(BaseModel):
    unread_count: int


class MarkReadRequest(BaseModel):
    ids: list[int] | None = None


class DeleteNotificationsRequest(BaseModel):
    ids: list[int]
