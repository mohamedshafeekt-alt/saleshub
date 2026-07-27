"""DealStage request/response schemas."""

from pydantic import BaseModel
from app.schemas.base import ORMBase


class DealStageCreate(BaseModel):
    company_id: int
    name: str
    sort_order: int
    is_cold: bool = False


class DealStageUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    is_cold: bool | None = None


class DealStageRead(ORMBase):

    id: int
    company_id: int
    name: str
    sort_order: int
    is_cold: bool
