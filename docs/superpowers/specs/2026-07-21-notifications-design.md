# Notifications — Backend/API Design

## Scope

In-app notifications only, wired to events that already exist in the
codebase. No new Task entity, no real-time push, no email mirroring, no
@mention system. All four are explicitly deferred (see Deferred section).

## Data model

New `app/models/notification.py`:

```python
class NotificationType(str, enum.Enum):
    TASK_OVERDUE = "task_overdue"
    DEAL_STAGE_CHANGED = "deal_stage_changed"
    LEAD_ASSIGNED = "lead_assigned"
    IMPORT_COMPLETED = "import_completed"

class Notification(Base):
    __tablename__ = "notifications"
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[NotificationType] = mapped_column(Enum(...), nullable=False)
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str] = mapped_column(nullable=False)
    is_read: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(nullable=False)   # "lead" | "deal"
    entity_id: Mapped[int] = mapped_column(nullable=False)
```

One row per recipient. `is_active`/`is_delete`/`created_at`/`updated_at`
inherited from `Base`.

`TASK_OVERDUE` notifications for lead follow-ups are **not stored rows** —
computed at read time from `Lead.next_follow_up_date < today` for leads
owned by the requesting user, and merged into the `GET /notifications`
response. No scheduler/cron exists in this codebase; adding one just to
pre-materialize these rows is unnecessary for Phase 1.

## Trigger points (plain function calls, no event bus)

Insert a `create_notification(db, recipient_id, type, ...)` call at the
point each event already happens:

- `lead_service.py` — lead reassigned → notify new owner (`LEAD_ASSIGNED`)
- `deal_service.py` — stage transition (already writes `DealStageHistory`)
  → notify deal owner + sales manager (`DEAL_STAGE_CHANGED`)
- CSV import completion path → notify the importing user (`IMPORT_COMPLETED`)

## API — `app/api/v1/notifications.py`

- `GET /notifications?unread_only=&type=&page=` — paginated list (stored
  rows + computed overdue-followup entries merged in, sorted by time)
- `GET /notifications/unread-count` — for the bell badge; client polls this
- `PATCH /notifications/{id}/read` — mark one read
- `POST /notifications/read-all` — mark-all-as-read; optional `ids: list[int]`
  body to scope it to a selection (covers the "2 items selected → Mark Read"
  bulk bar without a separate bulk endpoint)
- `DELETE /notifications` — body `{ids: list[int]}`, soft-deletes
  (`is_delete=True`); covers single delete and the bulk "Delete" action

No `mentions` filter/tab — deferred (see below).

## Delivery

Polling only. Client hits `unread-count` on an interval and `GET
/notifications` when the panel opens. No websocket/SSE infra — none
exists elsewhere in this codebase and nothing here needs sub-second
latency.

## Deferred (explicit, out of scope for this pass)

- **Task entity** — no standalone Task model; overdue notifications derive
  from `Lead.next_follow_up_date`. Add a real Task model only if a
  dedicated task-management screen gets built.
- **Real-time push** — polling covers the UI; add WebSocket/SSE if latency
  becomes a real complaint.
- **Email mirroring** — scope doc mentions optional per-type email
  notifications; skipped, needs a preferences table + settings UI.
- **Mentions tab** — no @mention concept exists anywhere (leads/deals have
  no comment-mention parsing); tab is not implemented.

## Testing

- `tests/services/test_notification_service.py` — create/list/mark-read/
  mark-all/delete, unread-count math, overdue-followup merge logic
- `tests/api/test_notifications.py` — RBAC (users only see their own
  notifications), pagination, unread_only filter
