"""Lead ORM model: prospecting record owned by a Sales Rep."""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import LeadSource, LeadStatus

if TYPE_CHECKING:
    from app.models.lead_activity import LeadActivity
    from app.models.lead_contact import LeadContact
    from app.models.user import User

__all__ = ["Lead"]


class Lead(Base):
    __tablename__ = "leads"

    first_name: Mapped[str] = mapped_column(nullable=False)
    last_name: Mapped[str | None] = mapped_column(nullable=True)
    company: Mapped[str] = mapped_column(nullable=False)
    domain: Mapped[str | None] = mapped_column(nullable=True)
    job_title: Mapped[str | None] = mapped_column(nullable=True)
    email: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(nullable=True)
    source: Mapped[LeadSource] = mapped_column(
        Enum(LeadSource, name="lead_source", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=False,
    )
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status", values_callable=lambda enum_cls: [m.value for m in enum_cls]),
        nullable=False,
        default=LeadStatus.NOT_CONTACTED,
        server_default="not_contacted",
    )
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    next_follow_up_date: Mapped[date | None] = mapped_column(nullable=True)
    follow_up_note: Mapped[str | None] = mapped_column(nullable=True)
    is_converted: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    is_favourite: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    # Eager (joined) since every list/get response needs the owner's display
    # name; contacts/activities stay lazy since only the single-lead detail
    # view needs them and eager-loading them for every list row would waste
    # a query fanning out per lead.
    owner: Mapped["User | None"] = relationship("User", lazy="joined")
    # passive_deletes=True: the FK already has ON DELETE CASCADE at the DB
    # level, so let the DB remove children instead of the ORM nulling their
    # (NOT NULL) lead_id on an unloaded collection when the lead is deleted.
    contacts: Mapped[list["LeadContact"]] = relationship(
        "LeadContact", order_by="LeadContact.id", passive_deletes=True
    )
    # id, not created_at: created_at is now()-based (fixed for the whole
    # transaction), so activities inserted in the same transaction would tie.
    activities: Mapped[list["LeadActivity"]] = relationship(
        "LeadActivity", order_by="LeadActivity.id", passive_deletes=True
    )

    @property
    def name(self) -> str:
        return " ".join(filter(None, [self.first_name, self.last_name]))

    @property
    def owner_name(self) -> str | None:
        if self.owner is None:
            return None
        return " ".join(filter(None, [self.owner.first_name, self.owner.last_name]))

    @property
    def activity_count(self) -> int:
        return len(self.activities)

    @property
    def last_contact_at(self) -> datetime | None:
        if not self.activities:
            return None
        return max(activity.updated_at for activity in self.activities)
