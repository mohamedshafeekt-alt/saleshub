"""HTTP-level contract for /api/v1/deals.

Covers: 201 create as each allowed role, 422 missing required field
(deal_name/account_id/owner_id) and bad stage enum value, 401 no auth, 403
for Delivery SME on create/list and for a non-owning Sales Rep on
get/patch/delete/stage-history, 404 for creating against a nonexistent
account and for a missing deal id, 200 list scoped by role and by each
filter (owner_id/stage/search), 200 partial PATCH, 400 PATCH that would
leave stage=cold_deals with no cold_reason on record, 200 PATCH that sets
stage=cold_deals together with cold_reason in the same request, 204
DELETE followed by a 404 GET, and GET /deals/{id}/stage-history reflecting
stage transitions in order after PATCHes.
"""

from httpx import AsyncClient

from app.models.user import UserRole

DEALS_URL = "/api/v1/deals"


def _deal_payload(**overrides) -> dict:
    payload = {
        "deal_name": "Acme Expansion",
        "account_id": overrides.pop("account_id"),
        "owner_id": overrides.pop("owner_id"),
    }
    payload.update(overrides)
    return payload


async def test_create_deal_as_sales_rep_returns_201(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-create-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Rep Deal Co")
    headers = auth_headers(rep)

    response = await client.post(
        DEALS_URL,
        json=_deal_payload(account_id=account.id, owner_id=rep.id, deal_name="Rep Deal"),
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["deal_name"] == "Rep Deal"
    assert body["account_id"] == account.id
    assert body["owner_id"] == rep.id
    assert body["currency"] == "USD"
    assert body["stage"] == "received_requirements"
    assert "id" in body


async def test_create_deal_as_sales_manager_returns_201(
    client: AsyncClient, make_user, auth_headers, make_account
):
    manager = await make_user(email="manager-create-deal@example.com", role=UserRole.SALES_MANAGER)
    rep = await make_user(email="rep-owned-by-manager-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Manager Deal Co")
    headers = auth_headers(manager)

    response = await client.post(
        DEALS_URL, json=_deal_payload(account_id=account.id, owner_id=rep.id), headers=headers
    )

    assert response.status_code == 201


async def test_create_deal_as_admin_returns_201(
    client: AsyncClient, make_user, auth_headers, make_account
):
    admin = await make_user(email="admin-create-deal@example.com", role=UserRole.ADMIN)
    rep = await make_user(email="rep-owned-by-admin-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Admin Deal Co")
    headers = auth_headers(admin)

    response = await client.post(
        DEALS_URL, json=_deal_payload(account_id=account.id, owner_id=rep.id), headers=headers
    )

    assert response.status_code == 201


async def test_create_deal_missing_deal_name_returns_422(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-missing-name-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Missing Name Deal Co")
    headers = auth_headers(rep)
    payload = _deal_payload(account_id=account.id, owner_id=rep.id)
    del payload["deal_name"]

    response = await client.post(DEALS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_deal_missing_account_id_returns_422(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-missing-account-deal@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    payload = _deal_payload(account_id=1, owner_id=rep.id)
    del payload["account_id"]

    response = await client.post(DEALS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_deal_missing_owner_id_returns_422(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-missing-owner-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Missing Owner Deal Co")
    headers = auth_headers(rep)
    payload = _deal_payload(account_id=account.id, owner_id=rep.id)
    del payload["owner_id"]

    response = await client.post(DEALS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_deal_bad_stage_enum_value_returns_422(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-bad-stage-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Bad Stage Deal Co")
    headers = auth_headers(rep)

    response = await client.post(
        DEALS_URL,
        json=_deal_payload(account_id=account.id, owner_id=rep.id, stage="not_a_real_stage"),
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_deal_no_auth_header_returns_401(client: AsyncClient, make_user, make_account):
    rep = await make_user(email="rep-no-auth-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="No Auth Deal Co")

    response = await client.post(DEALS_URL, json=_deal_payload(account_id=account.id, owner_id=rep.id))

    assert response.status_code == 401


async def test_create_deal_as_delivery_sme_returns_403(
    client: AsyncClient, make_user, auth_headers, make_account
):
    sme = await make_user(email="sme-create-deal@example.com", role=UserRole.DELIVERY_SME)
    other_rep = await make_user(email="rep-for-sme-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=other_rep.id, company="SME Deal Co")
    headers = auth_headers(sme)

    response = await client.post(
        DEALS_URL, json=_deal_payload(account_id=account.id, owner_id=other_rep.id), headers=headers
    )

    assert response.status_code == 403


async def test_create_deal_returns_404_for_nonexistent_account(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-create-404-deal@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        DEALS_URL, json=_deal_payload(account_id=999_999, owner_id=rep.id), headers=headers
    )

    assert response.status_code == 404


async def test_list_deals_as_delivery_sme_returns_403(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-list-deal@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.get(DEALS_URL, headers=headers)

    assert response.status_code == 403


async def test_list_deals_sales_rep_only_sees_own_deals(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    rep_a = await make_user(email="rep-list-a-deal@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-b-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep_a.id, company="List Deal Co A")
    own_deal = await make_deal(account_id=account.id, owner_id=rep_a.id, deal_name="Own List Deal")
    await make_deal(account_id=account.id, owner_id=rep_b.id, deal_name="Other List Deal")
    headers = auth_headers(rep_a)

    response = await client.get(DEALS_URL, params={"owner_id": rep_b.id}, headers=headers)

    assert response.status_code == 200
    assert [deal["id"] for deal in response.json()] == [own_deal.id]


async def test_list_deals_manager_sees_all_deals(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    manager = await make_user(email="manager-list-deal@example.com", role=UserRole.SALES_MANAGER)
    rep_a = await make_user(email="rep-list-c-deal@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-d-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep_a.id, company="List Deal Co B")
    deal_a = await make_deal(account_id=account.id, owner_id=rep_a.id, deal_name="List Deal A")
    deal_b = await make_deal(account_id=account.id, owner_id=rep_b.id, deal_name="List Deal B")
    headers = auth_headers(manager)

    response = await client.get(DEALS_URL, headers=headers)

    assert response.status_code == 200
    ids = {deal["id"] for deal in response.json()}
    assert {deal_a.id, deal_b.id} <= ids


async def test_list_deals_filters_by_stage(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    rep = await make_user(email="rep-filter-stage-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Filter Stage Deal Co")
    eval_deal = await make_deal(
        account_id=account.id, owner_id=rep.id, deal_name="Eval Filter Deal", stage="evaluation"
    )
    await make_deal(
        account_id=account.id, owner_id=rep.id, deal_name="Proposal Filter Deal", stage="proposals"
    )
    headers = auth_headers(rep)

    response = await client.get(DEALS_URL, params={"stage": "evaluation"}, headers=headers)

    assert response.status_code == 200
    assert [deal["id"] for deal in response.json()] == [eval_deal.id]


async def test_list_deals_filters_by_search(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    rep = await make_user(email="rep-filter-search-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Filter Search Deal Co")
    match = await make_deal(account_id=account.id, owner_id=rep.id, deal_name="Searchable Deal Inc")
    await make_deal(account_id=account.id, owner_id=rep.id, deal_name="Nothing Deal")
    headers = auth_headers(rep)

    response = await client.get(DEALS_URL, params={"search": "searchable"}, headers=headers)

    assert response.status_code == 200
    assert [deal["id"] for deal in response.json()] == [match.id]


async def test_get_deal_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-get-404-deal@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{DEALS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_get_deal_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-owns-get-deal@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-get-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Get Forbidden Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Get Forbidden Deal")
    headers = auth_headers(other_rep)

    response = await client.get(f"{DEALS_URL}/{deal.id}", headers=headers)

    assert response.status_code == 403


async def test_get_deal_returns_200_for_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-owns-get-ok-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Get Ok Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Get Ok Deal")
    headers = auth_headers(owner)

    response = await client.get(f"{DEALS_URL}/{deal.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == deal.id


async def test_update_deal_partial_patch_returns_200(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-patch-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Old Patch Deal", value=1000.0)
    headers = auth_headers(owner)

    response = await client.patch(
        f"{DEALS_URL}/{deal.id}", json={"deal_name": "New Patch Deal"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deal_name"] == "New Patch Deal"
    assert body["value"] == 1000.0


async def test_update_deal_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-patch-404-deal@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.patch(f"{DEALS_URL}/999999", json={"deal_name": "New"}, headers=headers)

    assert response.status_code == 404


async def test_update_deal_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-owns-patch-deal@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-patch-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Forbidden Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Patch Forbidden Deal")
    headers = auth_headers(other_rep)

    response = await client.patch(f"{DEALS_URL}/{deal.id}", json={"deal_name": "New"}, headers=headers)

    assert response.status_code == 403


async def test_update_deal_returns_400_when_stage_cold_without_reason(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-patch-cold-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Cold Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Patch Cold Deal")
    headers = auth_headers(owner)

    response = await client.patch(f"{DEALS_URL}/{deal.id}", json={"stage": "cold_deals"}, headers=headers)

    assert response.status_code == 400


async def test_update_deal_returns_200_when_cold_reason_provided_with_stage(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-patch-cold-ok-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Cold Ok Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Patch Cold Ok Deal")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{DEALS_URL}/{deal.id}",
        json={"stage": "cold_deals", "cold_reason": "Lost budget"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "cold_deals"
    assert body["cold_reason"] == "Lost budget"


async def test_create_deal_returns_400_when_stage_cold_without_reason(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-create-cold-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Create Cold Deal Co")
    headers = auth_headers(rep)

    response = await client.post(
        DEALS_URL,
        json=_deal_payload(account_id=account.id, owner_id=rep.id, stage="cold_deals"),
        headers=headers,
    )

    assert response.status_code == 400


async def test_delete_deal_returns_204(client: AsyncClient, make_user, auth_headers, make_account, make_deal):
    owner = await make_user(email="rep-delete-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Delete Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Delete Me Deal")
    headers = auth_headers(owner)

    response = await client.delete(f"{DEALS_URL}/{deal.id}", headers=headers)

    assert response.status_code == 204

    follow_up = await client.get(f"{DEALS_URL}/{deal.id}", headers=headers)
    assert follow_up.status_code == 404


async def test_delete_deal_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-delete-404-deal@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{DEALS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_delete_deal_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-owns-delete-deal@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-delete-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Delete Forbidden Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Delete Forbidden Deal")
    headers = auth_headers(other_rep)

    response = await client.delete(f"{DEALS_URL}/{deal.id}", headers=headers)

    assert response.status_code == 403


# --- GET /deals/{deal_id}/stage-history --------------------------------------


async def test_stage_history_returns_200_reflecting_transitions_after_patches(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-history-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="History Deal Co")
    deal = await make_deal(
        account_id=account.id, owner_id=owner.id, deal_name="History Deal", stage="received_requirements"
    )
    headers = auth_headers(owner)

    await client.patch(f"{DEALS_URL}/{deal.id}", json={"stage": "qualified_to_buy"}, headers=headers)
    await client.patch(f"{DEALS_URL}/{deal.id}", json={"stage": "evaluation"}, headers=headers)

    response = await client.get(f"{DEALS_URL}/{deal.id}/stage-history", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [row["to_stage"] for row in body] == ["qualified_to_buy", "evaluation"]


async def test_stage_history_returns_404_for_nonexistent_deal(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-history-404-deal@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{DEALS_URL}/999999/stage-history", headers=headers)

    assert response.status_code == 404


async def test_stage_history_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-owns-history-deal@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-history-deal@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="History Forbidden Deal Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id, deal_name="History Forbidden Deal")
    headers = auth_headers(other_rep)

    response = await client.get(f"{DEALS_URL}/{deal.id}/stage-history", headers=headers)

    assert response.status_code == 403
