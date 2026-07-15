"""HTTP-level contract for /api/v1/leads.

Covers: 201 create as each allowed role, 409 duplicate email, 422 missing
required field, 401 no auth, 403 for Delivery SME (list + create) and for a
non-owning Sales Rep (get/update/delete), 200 list scoped by role and by each
filter (owner_id/source/tier/search), 404 for a missing lead, 200 partial
PATCH, 204 DELETE.
"""

from httpx import AsyncClient

from app.models.user import UserRole

LEADS_URL = "/api/v1/leads"


def _lead_payload(**overrides) -> dict:
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "company": "Acme Corp",
        "email": "jane.doe@acme.com",
        "source": "website",
        "tier": "gold",
        "owner_id": overrides.pop("owner_id"),
    }
    payload.update(overrides)
    return payload


async def test_create_lead_as_sales_rep_returns_201(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-create@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=rep.id, email="created-by-rep@example.com"), headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "created-by-rep@example.com"
    assert body["company"] == "Acme Corp"
    assert body["source"] == "website"
    assert body["tier"] == "gold"
    assert body["owner_id"] == rep.id
    assert "id" in body


async def test_create_lead_as_sales_manager_returns_201(client: AsyncClient, make_user, auth_headers):
    manager = await make_user(email="manager-create@example.com", role=UserRole.SALES_MANAGER)
    rep = await make_user(email="rep-owned-by-manager@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(manager)

    response = await client.post(
        LEADS_URL,
        json=_lead_payload(owner_id=rep.id, email="created-by-manager@example.com"),
        headers=headers,
    )

    assert response.status_code == 201


async def test_create_lead_as_admin_returns_201(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-create@example.com", role=UserRole.ADMIN)
    rep = await make_user(email="rep-owned-by-admin@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=rep.id, email="created-by-admin@example.com"), headers=headers
    )

    assert response.status_code == 201


async def test_create_lead_duplicate_email_returns_409(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-dup@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    await client.post(
        LEADS_URL, json=_lead_payload(owner_id=rep.id, email="dup-lead@example.com"), headers=headers
    )

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=rep.id, email="dup-lead@example.com"), headers=headers
    )

    assert response.status_code == 409


async def test_create_lead_missing_company_returns_422(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-missing-company@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    payload = _lead_payload(owner_id=rep.id, email="missing-company@example.com")
    del payload["company"]

    response = await client.post(LEADS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_lead_bad_source_enum_value_returns_422(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-bad-source@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        LEADS_URL,
        json=_lead_payload(owner_id=rep.id, email="bad-source@example.com", source="not_a_real_source"),
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_lead_no_auth_header_returns_401(client: AsyncClient, make_user):
    rep = await make_user(email="rep-no-auth@example.com", role=UserRole.SALES_REP)

    response = await client.post(LEADS_URL, json=_lead_payload(owner_id=rep.id, email="no-auth@example.com"))

    assert response.status_code == 401


async def test_create_lead_as_delivery_sme_returns_403(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-create@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=sme.id, email="sme-blocked@example.com"), headers=headers
    )

    assert response.status_code == 403


async def test_list_leads_as_delivery_sme_returns_403(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-list@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.get(LEADS_URL, headers=headers)

    assert response.status_code == 403


async def test_list_leads_sales_rep_only_sees_own_leads(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    rep_a = await make_user(email="rep-list-a@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-b@example.com", role=UserRole.SALES_REP)
    own_lead = await make_lead(owner_id=rep_a.id, email="own-list-lead@example.com")
    await make_lead(owner_id=rep_b.id, email="other-list-lead@example.com")
    headers = auth_headers(rep_a)

    response = await client.get(LEADS_URL, params={"owner_id": rep_b.id}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [lead["id"] for lead in body] == [own_lead.id]


async def test_list_leads_manager_sees_all_leads(client: AsyncClient, make_user, auth_headers, make_lead):
    manager = await make_user(email="manager-list@example.com", role=UserRole.SALES_MANAGER)
    rep_a = await make_user(email="rep-list-c@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-d@example.com", role=UserRole.SALES_REP)
    lead_a = await make_lead(owner_id=rep_a.id, email="list-lead-a@example.com")
    lead_b = await make_lead(owner_id=rep_b.id, email="list-lead-b@example.com")
    headers = auth_headers(manager)

    response = await client.get(LEADS_URL, headers=headers)

    assert response.status_code == 200
    ids = {lead["id"] for lead in response.json()}
    assert {lead_a.id, lead_b.id} <= ids


async def test_list_leads_filters_by_owner_id(client: AsyncClient, make_user, auth_headers, make_lead):
    manager = await make_user(email="manager-list-owner@example.com", role=UserRole.SALES_MANAGER)
    rep_a = await make_user(email="rep-filter-owner-a@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-filter-owner-b@example.com", role=UserRole.SALES_REP)
    lead_a = await make_lead(owner_id=rep_a.id, email="filter-owner-a@example.com")
    await make_lead(owner_id=rep_b.id, email="filter-owner-b@example.com")
    headers = auth_headers(manager)

    response = await client.get(LEADS_URL, params={"owner_id": rep_a.id}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()] == [lead_a.id]


async def test_list_leads_filters_by_source(client: AsyncClient, make_user, auth_headers, make_lead):
    rep = await make_user(email="rep-filter-source@example.com", role=UserRole.SALES_REP)
    website_lead = await make_lead(owner_id=rep.id, email="filter-source-website@example.com", source="website")
    await make_lead(owner_id=rep.id, email="filter-source-referral@example.com", source="referral")
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, params={"source": "website"}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()] == [website_lead.id]


async def test_list_leads_filters_by_tier(client: AsyncClient, make_user, auth_headers, make_lead):
    rep = await make_user(email="rep-filter-tier@example.com", role=UserRole.SALES_REP)
    gold_lead = await make_lead(owner_id=rep.id, email="filter-tier-gold@example.com", tier="gold")
    await make_lead(owner_id=rep.id, email="filter-tier-bronze@example.com", tier="bronze")
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, params={"tier": "gold"}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()] == [gold_lead.id]


async def test_list_leads_filters_by_search(client: AsyncClient, make_user, auth_headers, make_lead):
    rep = await make_user(email="rep-filter-search@example.com", role=UserRole.SALES_REP)
    match = await make_lead(
        owner_id=rep.id, email="filter-search-match@example.com", company="Searchable Widgets Inc"
    )
    await make_lead(owner_id=rep.id, email="filter-search-nomatch@example.com", company="Nothing Co")
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, params={"search": "searchable"}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()] == [match.id]


async def test_get_lead_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-get-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{LEADS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_get_lead_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-get@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-get@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="get-forbidden@example.com")
    headers = auth_headers(other_rep)

    response = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert response.status_code == 403


async def test_get_lead_returns_200_for_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-get-ok@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="get-ok@example.com")
    headers = auth_headers(owner)

    response = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == lead.id


async def test_update_lead_partial_patch_returns_200(client: AsyncClient, make_user, auth_headers, make_lead):
    owner = await make_user(email="rep-patch@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="patch-me@example.com", company="Old Co")
    headers = auth_headers(owner)

    response = await client.patch(f"{LEADS_URL}/{lead.id}", json={"company": "New Co"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["company"] == "New Co"
    assert body["email"] == "patch-me@example.com"


async def test_update_lead_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-patch-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.patch(f"{LEADS_URL}/999999", json={"company": "New Co"}, headers=headers)

    assert response.status_code == 404


async def test_update_lead_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-patch@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-patch@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="patch-forbidden@example.com")
    headers = auth_headers(other_rep)

    response = await client.patch(f"{LEADS_URL}/{lead.id}", json={"company": "New Co"}, headers=headers)

    assert response.status_code == 403


async def test_update_lead_duplicate_email_returns_409(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-patch-dup@example.com", role=UserRole.SALES_REP)
    await make_lead(owner_id=owner.id, email="patch-dup-taken@example.com")
    lead_to_update = await make_lead(owner_id=owner.id, email="patch-dup-original@example.com")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{LEADS_URL}/{lead_to_update.id}", json={"email": "patch-dup-taken@example.com"}, headers=headers
    )

    assert response.status_code == 409


async def test_delete_lead_returns_204(client: AsyncClient, make_user, auth_headers, make_lead):
    owner = await make_user(email="rep-delete@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="delete-me@example.com")
    headers = auth_headers(owner)

    response = await client.delete(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert response.status_code == 204

    follow_up = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)
    assert follow_up.status_code == 404


async def test_delete_lead_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-delete-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{LEADS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_delete_lead_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-delete@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-delete@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="delete-forbidden@example.com")
    headers = auth_headers(other_rep)

    response = await client.delete(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert response.status_code == 403
