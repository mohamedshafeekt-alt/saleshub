from pydantic import BaseModel


class ErrorResponse(BaseModel):
    status_code: int = 400
    status: str | None = "error"
    message: str | None = ""
