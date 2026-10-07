"""Account Source Detail schemas: the ordered User/Contact chain."""

from typing import Literal

from pydantic import BaseModel, model_validator

PersonType = Literal["user", "contact"]


class SourcePersonRef(BaseModel):
    type: PersonType
    id: int


class SourceDetailUpdate(BaseModel):
    members: list[SourcePersonRef]

    @model_validator(mode="after")
    def _chain_rules(self) -> "SourceDetailUpdate":
        refs = [(m.type, m.id) for m in self.members]
        if len(set(refs)) != len(refs):
            raise ValueError("The same person cannot appear twice in the chain")
        return self


class SourcePersonRead(BaseModel):
    type: PersonType
    id: int
    name: str
    email: str | None
    phone: str | None
