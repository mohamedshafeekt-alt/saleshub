"""Notification list/read/delete routes. Self-scoped only -- every route
operates on the current user's own recipient_id, so no permission code
gates this router (any authenticated, active user may use it)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import NotificationType
from app.models.user import User
from app.schemas.generic_response import Page
from app.schemas.notification import (
    DeleteNotificationsRequest,
    MarkReadRequest,
    NotificationRead,
    NotificationUpdate,
    UnreadCountRead,
)
from app.services.notification_service import (
    NotificationAccessForbiddenError,
    NotificationNotFoundError,
    delete_notifications,
    get_unread_count,
    list_notifications,
    mark_all_read,
    set_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationRead])
async def list_notifications_route(
    unread_only: bool = Query(False),
    type: NotificationType | None = Query(None),
    limit: int = Query(20),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[NotificationRead]:
    items, total = await list_notifications(
        db, requester=current_user, unread_only=unread_only, type=type, limit=limit, offset=offset
    )
    return Page[NotificationRead](
        items=[NotificationRead.model_validate(item) for item in items], total=total, limit=limit, offset=offset
    )


@router.get("/unread-count", response_model=UnreadCountRead)
async def unread_count_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountRead:
    count = await get_unread_count(db, requester=current_user)
    return UnreadCountRead(unread_count=count)


@router.patch("/{notification_id}", response_model=NotificationRead)
async def update_notification_route(
    notification_id: int,
    data: NotificationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationRead:
    try:
        notification = await set_read(db, notification_id, requester=current_user, is_read=data.is_read)
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotificationAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()
    return NotificationRead.model_validate(notification)


@router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read_route(
    data: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    updated = await mark_all_read(db, requester=current_user, ids=data.ids)
    await db.commit()
    return {"updated": updated}


@router.delete("", status_code=status.HTTP_200_OK)
async def delete_notifications_route(
    data: DeleteNotificationsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    try:
        await delete_notifications(db, data.ids, requester=current_user)
    except NotificationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotificationAccessForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await db.commit()
    return {"deleted": len(data.ids)}
