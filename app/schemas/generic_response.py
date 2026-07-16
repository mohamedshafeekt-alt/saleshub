from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorResponse(BaseModel):
    status_code: int = 400
    status: str | None = "error"
    message: str | None = ""


class Page(BaseModel, Generic[T]):
    """Paginated list response: items for this page, plus enough to render
    "1-25 of 806" and drive prev/next without a second request."""

    items: list[T]
    total: int
    limit: int
    offset: int
