"""HTTP-level contract for /api/v1/deal-stages.

Covers: 201 create, 200 list (optionally filtered by company_id), 200 get,
200 partial patch, 404 for missing id on get/patch/delete, 204 delete, and
400 when deleting a stage still referenced by a deal.
"""

from httpx import AsyncClient

from tests.support.roles import UserRole

DEAL_STAGES_URL = "/api/v1/deal-stages"


async def test_create_deal_stage_returns_201(
    client: AsyncClient, make_user, auth_headers, make_company
):
    rep = await make_user(email="rep-create-stage@example.com", role=UserRole.SALES_REP)
    company = await make_company(name="Create Stage API Co")
    headers = auth_headers(rep)

    response = await client.post(
        DEAL_STAGES_URL,
        json={"company_id": company.id, "name": "Received Requirement", "sort_order": 0},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["company_id"] == company.id
    assert body["name"] == "Received Requirement"
    assert body["sort_order"] == 0
    assert body["is_cold"] is False


async def test_list_deal_stages_filters_by_company_id(
    client: AsyncClient, make_user, auth_headers, make_company, make_deal_stage
):
    rep = await make_user(email="rep-list-stage@example.com", role=UserRole.SALES_REP)
    company_a = await make_company(name="List Stage API Co A")
    company_b = await make_company(name="List Stage API Co B")
    stage_a = await make_deal_stage(company_id=company_a.id, name="Stage A")
    await make_deal_stage(company_id=company_b.id, name="Stage B")
    headers = auth_headers(rep)

    response = await client.get(DEAL_STAGES_URL, params={"company_id": company_a.id}, headers=headers)

    assert response.status_code == 200
    assert [stage["id"] for stage in response.json()] == [stage_a.id]


async def test_get_deal_stage_returns_404_for_missing_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-get-stage-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{DEAL_STAGES_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_update_deal_stage_partial_patch_returns_200(
    client: AsyncClient, make_user, auth_headers, make_deal_stage
):
    rep = await make_user(email="rep-patch-stage@example.com", role=UserRole.SALES_REP)
    stage = await make_deal_stage(name="Old Stage Name")
    headers = auth_headers(rep)

    response = await client.patch(
        f"{DEAL_STAGES_URL}/{stage.id}", json={"name": "New Stage Name"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Stage Name"


async def test_update_deal_stage_returns_404_for_missing_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-patch-stage-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.patch(
        f"{DEAL_STAGES_URL}/999999", json={"name": "New"}, headers=headers
    )

    assert response.status_code == 404


async def test_delete_deal_stage_returns_204(client: AsyncClient, make_user, auth_headers, make_deal_stage):
    rep = await make_user(email="rep-delete-stage@example.com", role=UserRole.SALES_REP)
    stage = await make_deal_stage(name="Deletable Stage API")
    headers = auth_headers(rep)

    response = await client.delete(f"{DEAL_STAGES_URL}/{stage.id}", headers=headers)

    assert response.status_code == 204

    follow_up = await client.get(f"{DEAL_STAGES_URL}/{stage.id}", headers=headers)
    assert follow_up.status_code == 404


async def test_delete_deal_stage_returns_404_for_missing_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-delete-stage-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{DEAL_STAGES_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_delete_deal_stage_returns_400_when_referenced_by_a_deal(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_deal_stage
):
    rep = await make_user(email="rep-delete-stage-in-use@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Delete Stage In Use Co")
    stage = await make_deal_stage(name="In Use Stage API")
    await make_deal(account_id=account.id, owner_id=rep.id, deal_name="In Use Deal API", stage_id=stage.id)
    headers = auth_headers(rep)

    response = await client.delete(f"{DEAL_STAGES_URL}/{stage.id}", headers=headers)

    assert response.status_code == 400
