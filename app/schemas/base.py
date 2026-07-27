from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, field_serializer


class ORMBase(BaseModel):
    """Base for schemas built from ORM objects. Naive datetimes coming out of
    Postgres are always UTC by convention; serialize them with an explicit
    offset so clients don't parse them as local time."""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _naive_datetime_as_utc(self, value):
        if isinstance(value, datetime) and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        return value
