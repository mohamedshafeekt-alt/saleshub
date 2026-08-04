"""HTTP-level contract for GET /api/v1/dashboard.

Covers: summary tiles (leads generated/qualified, deals in pipeline/closed),
401 with no auth, funnel ordered by stage sort_order, deal distribution
grouped by tier, leaderboard ranked by won-deal revenue, drop-off reasons
grouped by cold_reason across cold and closed-lost stages, conversion trend
counting stage-history transitions, and the merged/paginated activity feed —
all returned together from the single combined endpoint.
"""

from httpx import AsyncClient


async def test_dashboard_counts_leads_and_deals_in_current_month(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, make_lead, db_session
):
    from datetime import datetime

    from app.models.enums import LeadStatus

    user = await make_user(email="rep@example.com")
    headers = auth_headers(user)

    await make_lead(owner_id=user.id, email="a@acme.com", company="Acme", status=LeadStatus.NOT_CONTACTED)
    await make_lead(owner_id=user.id, email="b@beta.com", company="Beta", status=LeadStatus.CONTACTED)

    account = await make_account(owner_id=user.id, company="Acme")
    open_stage = await make_deal_stage(name="Evaluation", sort_order=2, is_cold=False)
    won_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Won", sort_order=5, is_cold=False)
    lost_stage = await make_deal_stage(company_id=open_stage.company_id, name="Closed Lost", sort_order=6, is_cold=False)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=1000)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=won_stage.id, value=2000)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=lost_stage.id, value=500)

    # An old account and an old open deal, both outside the current-month window.
    old_account = await make_account(owner_id=user.id, company="OldCo")
    old_account.created_at = datetime(2020, 1, 1)
    old_deal = await make_deal(account_id=account.id, owner_id=user.id, stage_id=open_stage.id, value=9999)
    old_deal.created_at = datetime(2020, 1, 1)
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["leads_generated"]["value"] == 2
    assert summary["qualified_leads"]["value"] == 1
    # deals_in_pipeline = open deals opened this period — the 2020 deal must not count.
    assert summary["deals_in_pipeline"]["value"] == 1
    # Only Closed Won counts as "closed" — the Closed Lost deal above must not.
    assert summary["deals_closed"]["value"] == 1
    # num_accounts = accounts created this period — the 2020 account must not count.
    assert summary["num_accounts"]["value"] == 1


async def test_dashboard_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/dashboard")
    assert response.status_code == 401


async def test_dashboard_period_rejects_today_and_requires_range_for_custom(
    client: AsyncClient, make_user, auth_headers
):
    user = await make_user(email="period@example.com")
    headers = auth_headers(user)

    assert (await client.get("/api/v1/dashboard?period=today", headers=headers)).status_code == 422
    assert (await client.get("/api/v1/dashboard?period=custom", headers=headers)).status_code == 422


async def test_dashboard_custom_period_scopes_leads_to_given_range(
    client: AsyncClient, make_user, auth_headers, make_lead, db_session
):
    from datetime import datetime

    from app.models.enums import LeadStatus

    user = await make_user(email="custom@example.com")
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


async def test_dashboard_funnel_counts_stage_entries_this_period_ordered_by_sort_order(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, db_session
):
    from app.models.deal_stage_history import DealStageHistory

    user = await make_user(email="funnel@example.com")
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="FunnelCo")
    stage_a = await make_deal_stage(name="Received Requirements", sort_order=0)
    stage_b = await make_deal_stage(company_id=stage_a.company_id, name="Qualified to Buy", sort_order=1)
    deal_1 = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_a.id)
    deal_2 = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_a.id)
    deal_3 = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage_b.id)

    # Funnel counts stage-entry events (DealStageHistory), not current stage —
    # make_deal alone leaves no history row, so these mark the entries explicitly.
    db_session.add_all(
        [
            DealStageHistory(deal_id=deal_1.id, from_stage_id=None, to_stage_id=stage_a.id, changed_by=user.id),
            DealStageHistory(deal_id=deal_2.id, from_stage_id=None, to_stage_id=stage_a.id, changed_by=user.id),
            DealStageHistory(deal_id=deal_3.id, from_stage_id=None, to_stage_id=stage_b.id, changed_by=user.id),
        ]
    )
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    stages = [
        s for s in response.json()["funnel"]["stages"] if s["stage_name"] in {"Received Requirements", "Qualified to Buy"}
    ]
    assert stages == [
        {"stage_name": "Received Requirements", "count": 2},
        {"stage_name": "Qualified to Buy", "count": 1},
    ]


async def test_dashboard_deal_distribution_groups_by_tier_within_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, db_session
):
    from datetime import datetime

    from app.models.enums import LeadTier

    user = await make_user(email="dist@example.com")
    headers = auth_headers(user)
    account = await make_account(owner_id=user.id, company="DistCo")
    stage = await make_deal_stage(name="Evaluation", sort_order=0)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage.id, tier=LeadTier.GOLD, value=1000)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage.id, tier=LeadTier.GOLD, value=500)
    await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage.id, tier=LeadTier.SILVER, value=200)
    old_deal = await make_deal(account_id=account.id, owner_id=user.id, stage_id=stage.id, tier=LeadTier.SILVER, value=999)
    old_deal.created_at = datetime(2020, 1, 1)
    await db_session.flush()
    await db_session.commit()

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    entries = {e["tier"]: e for e in response.json()["deal_distribution"]["entries"]}
    assert entries["gold"] == {"tier": "gold", "count": 2, "total_value": 1500.0}
    # Silver excludes the deal created outside the current-month window.
    assert entries["silver"] == {"tier": "silver", "count": 1, "total_value": 200.0}


async def test_dashboard_leaderboard_ranks_owners_by_won_revenue_within_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, db_session
):
    from datetime import datetime

    rep_1 = await make_user(email="rep1@example.com", first_name="Sarah")
    rep_2 = await make_user(email="rep2@example.com", first_name="Mike")
    headers = auth_headers(rep_1)
    account = await make_account(owner_id=rep_1.id, company="LeadersCo")
    won_stage = await make_deal_stage(name="Closed Won", sort_order=5)
    open_stage = await make_deal_stage(company_id=won_stage.company_id, name="Evaluation", sort_order=1)
    await make_deal(account_id=account.id, owner_id=rep_1.id, stage_id=won_stage.id, value=500)
    await make_deal(account_id=account.id, owner_id=rep_2.id, stage_id=won_stage.id, value=1000)
    await make_deal(account_id=account.id, owner_id=rep_2.id, stage_id=open_stage.id, value=9999)
    old_won = await make_deal(account_id=account.id, owner_id=rep_2.id, stage_id=won_stage.id, value=7777)
    old_won.updated_at = datetime(2020, 1, 1)
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


async def test_dashboard_drop_off_reasons_groups_cold_and_lost_deals_by_reason_and_stage_lost(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, db_session
):
    from app.models.deal_stage_history import DealStageHistory

    user = await make_user(email="dropoff@example.com")
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

    response = await client.get("/api/v1/dashboard", headers=headers)

    assert response.status_code == 200
    entries = {(e["reason"], e["stage_lost"]): e for e in response.json()["drop_off_reasons"]["entries"]}
    assert entries[("Pricing too high", "Unknown")]["count"] == 1
    assert entries[("Pricing too high", "Unknown")]["lost_value"] == 1000.0
    assert entries[("Pricing too high", "Proposals")]["count"] == 1
    assert entries[("Pricing too high", "Proposals")]["lost_value"] == 500.0
    assert entries[("Competitor chosen", "Unknown")]["count"] == 1
    assert entries[("Competitor chosen", "Unknown")]["lost_value"] == 300.0


async def test_dashboard_conversion_trend_counts_stage_transitions_within_period(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage, db_session
):
    from datetime import datetime

    from app.models.deal_stage_history import DealStageHistory

    user = await make_user(email="trend@example.com")
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

    user = await make_user(email="feed@example.com")
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
