"""DealStage request/response schemas."""

from pydantic import BaseModel, ConfigDict


class DealStageCreate(BaseModel):
    company_id: int
    name: str
    sort_order: int
    is_cold: bool = False


class DealStageUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None
    is_cold: bool | None = None


class DealStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    sort_order: int
    is_cold: bool
