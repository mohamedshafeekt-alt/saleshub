"""Combined Documents API: read-only cross-entity list of Account and Deal
documents (the "Documents" sidebar page). Filterable by `source`
(account/deal) and `search` (file name substring, case-insensitive). No
separate RBAC tag -- like search.router, any authenticated user can call
this; per-row visibility is already scoped in app.services.document_service
by the same ownership rule the Account/Deal list endpoints use."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.document import DocumentRead
from app.services.document_service import list_documents

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[DocumentRead])
async def list_documents_route(
    source: Literal["account", "deal"] | None = Query(None),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentRead]:
    return await list_documents(db, current_user, source=source, search=search)
