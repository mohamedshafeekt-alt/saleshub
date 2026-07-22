from pydantic import BaseModel


class SearchResult(BaseModel):
    id: int
    label: str
    name: str
