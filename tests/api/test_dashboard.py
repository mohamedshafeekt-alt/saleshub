"""HTTP-level contract for GET /api/v1/dashboard.

Covers: summary tiles (leads generated/qualified, deals in pipeline/closed),
401 with no auth, 403 without dashboard.view, funnel ordered by stage
sort_order, deal distribution grouped by tier, leaderboard ranked by
won-deal revenue, drop-off reasons grouped by cold_reason across cold and
closed-lost stages, conversion trend counting stage-history transitions,
and the merged/paginated activity feed — all returned together from the
single combined endpoint. dashboard.view is a Sales Manager/Admin-only
permission (see rbac_seed.STARTER_ROLES), so every request here authenticates
as a Sales Manager unless the test is specifically checking the 403 case.
"""

from httpx import AsyncClient

from tests.support.roles import UserRole


async def test_dashboard_requires_dashboard_view_permission(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="dashboard-rep@example.com", role=UserRole.SALES_REP)
    response = await client.get("/api/v1/dashboard", headers=auth_headers(rep))
    assert response.status_code == 403


async def test_dashboard_counts_leads_and_deals_in_current_month(
    client: AsyncClient,
    make_user,
    auth_headers,
    make_account,
    make_deal,
    make_deal_stage,
    make_lead,
    make_stage_change,
    db_session,
):
    from datetime import datetime

    from app.models.enums import LeadStatus

    user = await make_user(email="rep@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)

    await make_lead(owner_id=user.id, email="a@acme.com", company="Acme", status=LeadStatus.NOT_CONTACTED)
    # Contacted but never converted — must NOT count as "qualified" (status
    # alone isn't qualification; only an actual Account conversion is).
    await make_lead(owner_id=user.id, email="b@beta.com", company="Beta", status=LeadStatus.CONTACTED)
    converted_lead = await make_lead(
        owner_id=user.id, email="c@converted.com", company="Converted", status=LeadStatus.NOT_CONTACTED
    )

    account = await make_account(owner_id=user.id, company="Acme")
    await make_account(owner_id=user.id, company="Converted", source_lead_id=converted_lead.id)
    open_stage = await make_deal_stage(name="Evaluation", sort_order=2, is_cold=False)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5, is_cold=False)
    lost_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Lost", sort_order=6, is_cold=False)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=1000)
    # Won this month: recorded as a real transition, since that (not
    # Deal.updated_at) is what dates a close.
    won_this_month = await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=2000)
    await make_stage_change(won_this_month, to_stage_id=won_stage.id, at=datetime.now())
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=lost_stage.id, value=500)

    # An old account, both outside the current-month window.
    old_account = await make_account(owner_id=user.id, company="OldCo")
    old_account.created_at = datetime(2020, 1, 1)
    # Opened in 2020 but still open today — still belongs in the pipeline.
    old_open_deal = await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=9999)
    old_open_deal.created_at = datetime(2020, 1, 1)
    # Opened AND won back in 2020 — out of the pipeline, and out of THIS
    # month's deals_closed even though it sits in Closed Won today.
    old_closed_deal = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=4242, created_at=datetime(2020, 1, 1)
    )
    await make_stage_change(old_closed_deal, to_stage_id=won_stage.id, at=datetime(2020, 1, 2))
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["leads_generated"]["value"] == 3
    assert summary["leads_to_accounts"]["value"] == 1
    # deals_in_pipeline = open right now — includes the still-open 2020 deal,
    # excludes the one that closed back in 2020.
    assert summary["deals_in_pipeline"]["value"] == 2
    # Only Closed Won counts as "closed" — the Closed Lost deal above must not.
    assert summary["deals_closed"]["value"] == 1
    # num_accounts = accounts created this period — the 2020 account must not count.
    assert summary["num_accounts"]["value"] == 2


async def test_dashboard_deals_in_pipeline_is_a_snapshot_as_of_period_end(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    from datetime import datetime

    user = await make_user(email="pipeline-snapshot@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="SnapshotCo")
    open_stage = await make_deal_stage(name="Evaluation", sort_order=1, is_cold=False)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5, is_cold=False)

    opened = {"created_at": datetime(2020, 1, 1), "with_history": True}

    # Opened before the snapshot date, never closed — open at the snapshot AND today.
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=100, **opened)
    # Opened before, closed before the snapshot date — gone by then already.
    closed_before = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=200, **opened
    )
    await make_stage_change(closed_before, to_stage_id=won_stage.id, at=datetime(2020, 2, 1))
    # Opened before, closed AFTER the snapshot date — was still open at the
    # snapshot even though it's closed now. Proves the as-of reconstruction,
    # not just "currently open".
    closed_after = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=300, **opened
    )
    await make_stage_change(closed_after, to_stage_id=won_stage.id, at=datetime(2020, 8, 1))
    await db_session.flush()
    await db_session.commit()

    response = await client.get(
        "/api/v1/dashboard?period=custom&start_date=2020-01-01&end_date=2020-06-30", headers=headers
    )

    assert response.status_code == 200
    # As of 2020-06-30: still_open and closed_after were open; closed_before wasn't.
    assert response.json()["summary"]["deals_in_pipeline"]["value"] == 2


async def test_dashboard_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/dashboard")
    assert response.status_code == 401


async def test_dashboard_period_rejects_today_and_requires_range_for_custom(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="period@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)

    assert (await client.get("/api/v1/dashboard?period=today", headers=headers)).status_code == 422
    assert (await client.get("/api/v1/dashboard?period=custom", headers=headers)).status_code == 422


async def test_dashboard_custom_period_rejects_end_date_before_start_date(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="reversed-range@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)

    response = await client.get(
        "/api/v1/dashboard?period=custom&start_date=2026-02-01&end_date=2026-01-01", headers=headers
    )
    assert response.status_code == 422


async def test_dashboard_custom_period_scopes_leads_to_given_range(
    client: AsyncClient, make_user, auth_headers, make_lead, db_session
):
    from datetime import datetime

    from app.models.enums import LeadStatus

    user = await make_user(email="custom@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)

    in_range = await make_lead(owner_id=user.id, email="in@range.com", company="InRange", status=LeadStatus.NOT_CONTACTED)
    in_range.created_at = datetime(2026, 1, 15)
    out_of_range = await make_lead(
        owner_id=user.id, email="out@range.com", company="OutOfRange", status=LeadStatus.NOT_CONTACTED
    )
    out_of_range.created_at = datetime(2026, 2, 15)
    await db_session.flush()
    await db_session.commit()

    response = await client.get(
        "/api/v1/dashboard?period=custom&start_date=2026-01-01&end_date=2026-01-31", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["summary"]["leads_generated"]["value"] == 1


async def test_dashboard_funnel_live_counts_open_stages_and_period_scopes_terminal_stages(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    from datetime import datetime

    user = await make_user(email="funnel@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="FunnelCo")
    stage_a = await make_deal_stage(name="Received Requirements", sort_order=0)
    stage_b = await make_deal_stage(company_id=stage_a.company_id, name="Qualified to Buy", sort_order=1)
    won_stage = await make_deal_stage(company_id=stage_a.company_id, name="Closed Won", sort_order=5)

    # Open stages: a live count, period ignored — one of these is deliberately
    # backdated to prove it still counts (no date filter applies to open stages).
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_a.id)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_a.id, created_at=datetime(2020, 1, 1))
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_b.id)

    # Terminal stage: period-scoped by when the deal entered it, same as
    # deals_closed — the 2020 win must not count in this month's Closed Won bar.
    # Both start in Qualified to Buy and move out, so that bar stays at 1.
    won_this_month = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_b.id)
    await make_stage_change(won_this_month, to_stage_id=won_stage.id, at=datetime.now())
    old_won = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_b.id)
    await make_stage_change(old_won, to_stage_id=won_stage.id, at=datetime(2020, 1, 1))
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    stages = [
        s
        for s in response.json()["funnel"]["stages"]
        if s["stage_name"] in {"Received Requirements", "Qualified to Buy", "Closed Won"}
    ]
    assert stages == [
        {"stage_id": stage_a.id, "stage_name": "Received Requirements", "is_terminal": False, "count": 2},
        {"stage_id": stage_b.id, "stage_name": "Qualified to Buy", "is_terminal": False, "count": 1},
        {"stage_id": won_stage.id, "stage_name": "Closed Won", "is_terminal": True, "count": 1},
    ]


async def test_dashboard_deal_distribution_groups_by_tier_within_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage
):
    from datetime import datetime

    from app.models.enums import LeadTier

    user = await make_user(email="dist@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="DistCo")
    stage = await make_deal_stage(name="Evaluation", sort_order=0)
    # `with_history=True` -- distribution is now scoped by `entered_current_stage_in`
    # (deal_stage_history), not `created_at`, so it agrees with `GET
    # /deals?date_field=closed_at` for the same range (was created_at-scoped,
    # which counted a different set of deals than that list view).
    await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=stage.id, tier=LeadTier.GOLD, value=1000, with_history=True
    )
    await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=stage.id, tier=LeadTier.GOLD, value=500, with_history=True
    )
    await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=stage.id, tier=LeadTier.SILVER, value=200, with_history=True
    )
    # Entered its (only) stage in 2020 -- outside the current-month window.
    await make_deal(
        account_id=account.id,
        owner_id=user.id,
        stage_id=stage.id,
        tier=LeadTier.SILVER,
        value=999,
        with_history=True,
        created_at=datetime(2020, 1, 1),
    )

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    entries = {e["tier"]: e for e in response.json()["deal_distribution"]["entries"]}
    assert entries["gold"] == {"tier": "gold", "count": 2, "total_value": 1500.0}
    # Silver excludes the deal that entered its stage outside the current-month window.
    assert entries["silver"] == {"tier": "silver", "count": 1, "total_value": 200.0}


async def test_dashboard_leaderboard_ranks_owners_by_won_revenue_within_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    from datetime import datetime

    rep_1 = await make_user(email="rep1@example.com", first_name="Sarah", role=UserRole.SALES_MANAGER)
    rep_2 = await make_user(email="rep2@example.com", first_name="Mike")
    headers = auth_headers(rep_1)
    account = await make_account(owner_id=rep_1.id, company="LeadersCo")
    won_stage = await make_deal_stage(name="Closed Won", sort_order=5)
    open_stage = await make_deal_stage(company_id=won_stage.company_id, name="Evaluation", sort_order=1)
    sarah_won = await make_deal(account_id=account.id, owner_id=rep_1.id, stage_id=open_stage.id, value=500)
    await make_stage_change(sarah_won, to_stage_id=won_stage.id, at=datetime.now())
    mike_won = await make_deal(account_id=account.id, owner_id=rep_2.id, stage_id=open_stage.id, value=1000)
    await make_stage_change(mike_won, to_stage_id=won_stage.id, at=datetime.now())
    await make_deal(account_id=account.id, owner_id=rep_2.id, stage_id=open_stage.id, value=9999)
    old_won = await make_deal(account_id=account.id, owner_id=rep_2.id, stage_id=open_stage.id, value=7777)
    await make_stage_change(old_won, to_stage_id=won_stage.id, at=datetime(2020, 1, 1))
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    entries = response.json()["leaderboard"]["entries"]
    by_owner = {e["owner_id"]: e for e in entries}
    # Mike's old (out-of-period) won deal must not inflate this period's revenue.
    assert by_owner[rep_2.id] == {"owner_id": rep_2.id, "owner_name": "Mike", "revenue": 1000.0, "deals_closed": 1}
    assert by_owner[rep_1.id] == {"owner_id": rep_1.id, "owner_name": "Sarah", "revenue": 500.0, "deals_closed": 1}
    assert entries.index(by_owner[rep_2.id]) < entries.index(by_owner[rep_1.id])


async def test_dashboard_deals_closed_dates_the_close_not_the_last_edit(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    """A 2020 win edited today must not land in this month's numbers.

    This is the regression that killed Deal.updated_at as a close timestamp:
    Base.updated_at carries onupdate=func.now(), so a rename is enough to drag a
    long-closed deal into the current period's Deals Closed tile and leaderboard.
    """
    from datetime import datetime

    user = await make_user(email="closed-at@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="ClosedAtCo")
    open_stage = await make_deal_stage(name="Proposals", sort_order=3)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5)

    old_win = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=5000, created_at=datetime(2020, 1, 1)
    )
    await make_stage_change(old_win, to_stage_id=won_stage.id, at=datetime(2020, 3, 1))

    old_win.deal_name = "Renamed today"
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(old_win)
    # The edit really did bump updated_at — otherwise this test proves nothing.
    assert old_win.updated_at > datetime(2020, 12, 31)

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["deals_closed"]["value"] == 0
    assert body["leaderboard"]["entries"] == []
    won_bar = next(s for s in body["funnel"]["stages"] if s["stage_name"] == "Closed Won")
    assert won_bar["count"] == 0


async def test_dashboard_deals_closed_tile_matches_deals_list_closed_at_drill_down(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    """Clicking the tile has to land on exactly the deals it counted.

    The tile is event-scoped ("closed this period") while the deals list defaults
    to created_at ("opened this period"), which is why the two used to disagree.
    date_field=closed_at is the lens that reconciles them; this asserts the
    contract directly so it can't drift apart again.
    """
    from datetime import date, datetime

    user = await make_user(email="drilldown@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="DrillCo")
    open_stage = await make_deal_stage(name="Contracts", sort_order=4)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5)

    # Opened long ago, won this month — in the tile, but NOT in a created_at-filtered list.
    old_deal_new_win = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=1000, created_at=datetime(2020, 1, 1)
    )
    await make_stage_change(old_deal_new_win, to_stage_id=won_stage.id, at=datetime.now())
    # Opened and won this month — in both.
    fresh_win = await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=2000)
    await make_stage_change(fresh_win, to_stage_id=won_stage.id, at=datetime.now())
    # Won in 2020, and still open today — in neither.
    old_win = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=3000, created_at=datetime(2020, 1, 1)
    )
    await make_stage_change(old_win, to_stage_id=won_stage.id, at=datetime(2020, 3, 1))
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=4000)
    await db_session.flush()
    await db_session.commit()

    dashboard = await client.get("/api/v1/dashboard", headers=headers)
    assert dashboard.status_code == 200
    body = dashboard.json()
    tile = body["summary"]["deals_closed"]["value"]
    assert tile == 2

    today = date.today()
    drill_down = await client.get(
        f"/api/v1/deals?view=list&date_field=closed_at&stage_id={won_stage.id}"
        f"&date_from={today.replace(day=1)}&date_to={today}",
        headers=headers,
    )
    assert drill_down.status_code == 200
    assert drill_down.json()["total"] == tile
    assert {item["id"] for item in drill_down.json()["items"]} == {old_deal_new_win.id, fresh_win.id}

    # ...and the funnel bar is the same number, from the same predicate.
    won_bar = next(s for s in body["funnel"]["stages"] if s["stage_name"] == "Closed Won")
    assert won_bar["count"] == tile


async def test_dashboard_deals_closed_drill_down_excludes_lost_and_cold_deals(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    """The tile only counts Closed Won (dashboard_service._count_deals_closed).

    date_field=closed_at alone -- no stage_id needed -- has to carry that same
    Closed-Won-only meaning, since that's the drill-down the dashboard's "Deals
    Closed" tile actually links to. It used to fall back to "any terminal stage"
    (Closed Won, Closed Lost, or cold), which folded lost/cold deals closed in
    the same period into a tile-labelled drill-down that never counted them.
    """
    from datetime import date, datetime

    user = await make_user(email="drilldown-lost@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="DrillLostCo")
    open_stage = await make_deal_stage(name="Contracts", sort_order=4)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5)
    lost_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Lost", sort_order=6)

    win = await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=1000)
    await make_stage_change(win, to_stage_id=won_stage.id, at=datetime.now())
    lost = await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=500)
    await make_stage_change(lost, to_stage_id=lost_stage.id, at=datetime.now())
    await db_session.flush()
    await db_session.commit()

    dashboard = await client.get("/api/v1/dashboard", headers=headers)
    tile = dashboard.json()["summary"]["deals_closed"]["value"]
    assert tile == 1

    today = date.today()
    drill_down = await client.get(
        f"/api/v1/deals?view=list&date_field=closed_at"
        f"&date_from={today.replace(day=1)}&date_to={today}",
        headers=headers,
    )
    assert drill_down.status_code == 200
    assert drill_down.json()["total"] == tile
    assert {item["id"] for item in drill_down.json()["items"]} == {win.id}


async def test_dashboard_deals_closed_excludes_a_deal_reopened_out_of_closed_won(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    """Documents the chosen semantics: the count is anchored to the deal's
    CURRENT stage, so re-opening a deal removes it from the period it closed in
    (see entered_current_stage_in). Keeps tile, funnel bar and drill-down equal."""
    from datetime import datetime

    user = await make_user(email="reopened@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="ReopenCo")
    open_stage = await make_deal_stage(name="Contracts", sort_order=4)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5)

    deal = await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=1000)
    await make_stage_change(deal, to_stage_id=won_stage.id, at=datetime.now())
    await make_stage_change(deal, to_stage_id=open_stage.id, at=datetime.now())
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    assert response.json()["summary"]["deals_closed"]["value"] == 0
    # ...and it's back in the pipeline snapshot instead.
    assert response.json()["summary"]["deals_in_pipeline"]["value"] == 1


async def test_dashboard_deals_closed_counts_a_re_won_deal_only_in_its_latest_close_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_stage_change, db_session
):
    """A deal won, re-opened, then re-won has TWO transitions into Closed Won.

    Only the most recent one counts. Testing "is there any entry into Closed Won
    in this range" would put the deal in both March's and this month's
    deals_closed, so summing the months would exceed the distinct deal count.
    """
    from datetime import datetime

    user = await make_user(email="rewon@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="ReWonCo")
    open_stage = await make_deal_stage(name="Contracts", sort_order=4)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5)

    deal = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=1000,
        created_at=datetime(2026, 3, 1), with_history=True,
    )
    await make_stage_change(deal, to_stage_id=won_stage.id, at=datetime(2026, 3, 10))
    await make_stage_change(deal, to_stage_id=open_stage.id, at=datetime(2026, 4, 1))
    await make_stage_change(deal, to_stage_id=won_stage.id, at=datetime.now())
    await db_session.flush()
    await db_session.commit()

    march = await client.get(
        "/api/v1/dashboard?period=custom&start_date=2026-03-01&end_date=2026-03-31", headers=headers
    )
    now = await client.get("/api/v1/dashboard", headers=headers)

    assert march.status_code == 200 and now.status_code == 200
    # The March win was superseded — it does not count twice.
    assert march.json()["summary"]["deals_closed"]["value"] == 0
    assert now.json()["summary"]["deals_closed"]["value"] == 1
    # Revenue follows the same rule, so a re-won deal can't be paid out twice.
    assert march.json()["leaderboard"]["entries"] == []
    assert now.json()["leaderboard"]["entries"][0]["revenue"] == 1000.0


async def test_dashboard_drop_off_reasons_groups_cold_and_lost_deals_by_reason_and_stage_lost(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, db_session
):
    from datetime import datetime

    from app.models.deal_stage_history import DealStageHistory

    user = await make_user(email="dropoff@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="DropOffCo")
    open_stage = await make_deal_stage(name="Proposals", sort_order=3)
    cold_stage = await make_deal_stage(company_id=open_stage.company_id, name="Cold Deals", sort_order=6, is_cold=True)
    lost_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Lost", sort_order=7)

    # created directly into a cold/lost stage -- no prior stage, "Unknown"
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=cold_stage.id, cold_reason="Pricing too high", value=1000)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=lost_stage.id, cold_reason="Competitor chosen", value=300)

    # dropped off from a real prior stage
    dropped_deal = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=open_stage.id, cold_reason="Pricing too high", value=500
    )
    dropped_deal.stage_id = lost_stage.id
    db_session.add(
        DealStageHistory(deal_id=dropped_deal.id, from_stage_id=open_stage.id, to_stage_id=lost_stage.id, changed_by=user.id)
    )
    await db_session.flush()
    await db_session.commit()

    # An old drop-off (stage-lost transition dated 2020) — must not leak into
    # this month's count/lost_value, only the ones above should show.
    old_stage = await make_deal_stage(company_id=open_stage.company_id, name="Evaluation", sort_order=1)
    old_dropped = await make_deal(
        account_id=account.id, owner_id=user.id, stage_id=cold_stage.id, cold_reason="Old reason", value=8888
    )
    old_transition = DealStageHistory(
        deal_id=old_dropped.id, from_stage_id=old_stage.id, to_stage_id=cold_stage.id, changed_by=user.id
    )
    db_session.add(old_transition)
    await db_session.flush()
    old_transition.created_at = datetime(2020, 1, 1)
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    entries = {(e["reason"], e["stage_lost"]): e for e in response.json()["drop_off_reasons"]["entries"]}
    assert entries[("Pricing too high", "Unknown")]["count"] == 1
    assert entries[("Pricing too high", "Unknown")]["lost_value"] == 1000.0
    assert entries[("Pricing too high", "Proposals")]["count"] == 1
    assert entries[("Pricing too high", "Proposals")]["lost_value"] == 500.0
    assert entries[("Competitor chosen", "Unknown")]["count"] == 1
    assert entries[("Competitor chosen", "Unknown")]["lost_value"] == 300.0
    # The 2020 drop-off must not appear at all in this month's list.
    assert ("Old reason", "Evaluation") not in entries


async def test_dashboard_conversion_trend_counts_stage_transitions_within_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, db_session
):
    from datetime import datetime

    from app.models.deal_stage_history import DealStageHistory

    user = await make_user(email="trend@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="TrendCo")
    stage_a = await make_deal_stage(name="Evaluation", sort_order=1)
    stage_b = await make_deal_stage(company_id=stage_a.company_id, name="Closed Won", sort_order=5)
    deal = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_b.id)
    old_deal = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_b.id)

    db_session.add(DealStageHistory(deal_id=deal.id, from_stage_id=stage_a.id, to_stage_id=stage_b.id, changed_by=user.id))
    old_transition = DealStageHistory(deal_id=old_deal.id, from_stage_id=stage_a.id, to_stage_id=stage_b.id, changed_by=user.id)
    db_session.add(old_transition)
    await db_session.flush()
    old_transition.created_at = datetime(2020, 1, 1)
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard?granularity=monthly", headers=headers)

    assert response.status_code == 200
    entries = response.json()["conversion_trend"]["entries"]
    # Only the in-period transition counts — the 2020 one must not show up at all.
    assert entries == [{"period": entries[0]["period"], "stage_name": "Closed Won", "count": 1}]

    custom_response = await client.get(
        "/api/v1/dashboard?granularity=monthly&period=custom&start_date=2020-01-01&end_date=2020-01-31",
        headers=headers,
    )
    assert custom_response.status_code == 200
    custom_entries = custom_response.json()["conversion_trend"]["entries"]
    assert any(e["stage_name"] == "Closed Won" and e["count"] == 1 for e in custom_entries)


async def test_dashboard_activity_feed_merges_and_sorts_across_entities_within_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_lead, db_session
):
    from datetime import datetime

    from app.models.account_activity import AccountActivity
    from app.models.deal_activity import DealActivity
    from app.models.lead_activity import LeadActivity

    user = await make_user(email="feed@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="FeedCo")
    stage = await make_deal_stage(name="Evaluation", sort_order=0)
    deal = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage.id)

    lead = await make_lead(owner_id=user.id, email="c@feed.com", company="FeedLead")

    db_session.add_all(
        [
            DealActivity(deal_id=deal.id, type="call", note="Call about proposal", created_by=user.id, updated_by=user.id),
            LeadActivity(lead_id=lead.id, type="note", note="Initial note", created_by=user.id, updated_by=user.id),
            AccountActivity(account_id=account.id, type="meeting", note="Kickoff meeting", created_by=user.id, updated_by=user.id),
        ]
    )
    old_activity = DealActivity(
        deal_id=deal.id, type="call", note="Ancient call", created_by=user.id, updated_by=user.id
    )
    db_session.add(old_activity)
    await db_session.flush()
    old_activity.created_at = datetime(2020, 1, 1)
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard?limit=10", headers=headers)

    assert response.status_code == 200
    body = response.json()["activity_feed"]["entries"]
    assert len(body) == 3
    assert {e["entity_type"] for e in body} <= {"deal", "lead", "account"}
    assert all(e["note"] != "Ancient call" for e in body)
