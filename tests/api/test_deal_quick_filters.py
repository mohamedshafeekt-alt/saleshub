"""Dashboard deal tiles (In view / Very high / Overdue / Due today / Past SLA)
and the matching GET /deals?quick_filter=... drill-down: one predicate, so a
tile's count always equals the rows its click shows."""

from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient

from app.core.deal_scoring import SCORING_DIMENSIONS
from tests.support.roles import UserRole

DEALS_URL = "/api/v1/deals"


def _scores_worth(level_score: int) -> dict[str, str]:
    return {
        dim: next(k for k, (_, s) in spec["levels"].items() if s == level_score)
        for dim, spec in SCORING_DIMENSIONS.items()
    }


async def _seed(make_user, make_account, make_deal_stage, make_deal):
    rep = await make_user(email="rep-qf@example.com", role=UserRole.SALES_REP)
    other = await make_user(email="other-qf@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="QF Co")
    open_stage = await make_deal_stage(name="QF Open")
    won = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=9)
    today = date.today()
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)  # DB timestamps are naive UTC
    d = {}
    d["a"] = await make_deal(  # Mode A, due today
        account_id=account.id, owner_id=rep.id, stage_id=open_stage.id, deal_name="A",
        scores=_scores_worth(3), follow_up_date=today)
    d["b"] = await make_deal(  # overdue
        account_id=account.id, owner_id=rep.id, stage_id=open_stage.id, deal_name="B",
        scores=_scores_worth(2), follow_up_date=today - timedelta(days=2))
    d["c"] = await make_deal(  # past SLA, proposal not sent
        account_id=account.id, owner_id=rep.id, stage_id=open_stage.id, deal_name="C",
        scores=_scores_worth(2), proposal_sla_due_at=past)
    d["d"] = await make_deal(  # SLA passed but proposal sent -> not past SLA
        account_id=account.id, owner_id=rep.id, stage_id=open_stage.id, deal_name="D",
        scores=_scores_worth(2), proposal_sla_due_at=past, proposal_status="proposal_sent")
    d["e"] = await make_deal(  # closed: counted nowhere
        account_id=account.id, owner_id=rep.id, stage_id=won.id, deal_name="E",
        scores=_scores_worth(3), follow_up_date=today - timedelta(days=1), proposal_sla_due_at=past)
    d["f"] = await make_deal(  # someone else's deal: not in rep's view
        account_id=account.id, owner_id=other.id, stage_id=open_stage.id, deal_name="F",
        scores=_scores_worth(3), follow_up_date=today)
    return rep, d


async def test_dashboard_deal_tiles_count_open_deals_by_rule(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal_stage, make_deal
):
    rep, _ = await _seed(make_user, make_account, make_deal_stage, make_deal)
    admin = await make_user(email="admin-qf@example.com", role=UserRole.ADMIN)

    # Admin sees every owner's deals, so F (another rep's open Mode A deal due
    # today) counts too.
    response = await client.get("/api/v1/dashboard", headers=auth_headers(admin))

    assert response.status_code == 200
    assert response.json()["deal_tiles"] == {
        "in_view": 5, "very_high": 2, "overdue": 1, "due_today": 2, "past_sla": 1,
    }


async def test_quick_filter_lists_exactly_the_deals_each_tile_counts(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal_stage, make_deal
):
    rep, d = await _seed(make_user, make_account, make_deal_stage, make_deal)
    expected = {
        "in_view": {"A", "B", "C", "D"},
        "very_high": {"A"},
        "overdue": {"B"},
        "due_today": {"A"},
        "past_sla": {"C"},
    }

    for quick_filter, names in expected.items():
        response = await client.get(DEALS_URL, params={"quick_filter": quick_filter}, headers=auth_headers(rep))
        assert response.status_code == 200, quick_filter
        assert {i["deal_name"] for i in response.json()["items"]} == names, quick_filter
        assert response.json()["total"] == len(names), quick_filter


async def test_quick_filter_rejects_unknown_value(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-qf-bad@example.com", role=UserRole.SALES_REP)

    response = await client.get(DEALS_URL, params={"quick_filter": "nope"}, headers=auth_headers(rep))

    assert response.status_code == 422
