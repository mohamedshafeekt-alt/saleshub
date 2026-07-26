"""AccountActivity ORM model: a Note/Meeting/Call/Comment logged against an Account."""

from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AccountActivityType

if TYPE_CHECKING:
    from app.models.user import User

__all__ = ["AccountActivity"]


class AccountActivity(Base):
    __tablename__ = "account_activities"

    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[AccountActivityType] = mapped_column(
        Enum(
            AccountActivityType,
            name="account_activity_type",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
    )
    note: Mapped[str] = mapped_column(nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    creator: Mapped["User"] = relationship("User", lazy="joined", foreign_keys=[created_by])
    updater: Mapped["User | None"] = relationship("User", lazy="joined", foreign_keys=[updated_by])

    @property
    def created_by_name(self) -> str:
        return " ".join(filter(None, [self.creator.first_name, self.creator.last_name]))

    @property
    def updated_by_name(self) -> str | None:
        if self.updater is None:
            return None
        return " ".join(filter(None, [self.updater.first_name, self.updater.last_name]))
