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


async def test_create_lead_as_delivery_sme_returns_201(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-create@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=sme.id, email="sme-created@example.com"), headers=headers
    )

    assert response.status_code == 201


async def test_list_leads_as_delivery_sme_returns_200(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-list@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.get(LEADS_URL, headers=headers)

    assert response.status_code == 200


async def test_list_leads_sales_rep_sees_unassigned_lead(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    rep = await make_user(email="rep-unassigned-list@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-unassigned-owner@example.com", role=UserRole.SALES_REP)
    unassigned = await make_lead(owner_id=None, email="unassigned-list-lead@example.com")
    await make_lead(owner_id=other_rep.id, email="other-owned-list-lead@example.com")
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, headers=headers)

    assert response.status_code == 200
    ids = {lead["id"] for lead in response.json()}
    assert unassigned.id in ids


async def test_get_lead_sales_rep_can_access_unassigned_lead(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    rep = await make_user(email="rep-unassigned-get@example.com", role=UserRole.SALES_REP)
    unassigned = await make_lead(owner_id=None, email="unassigned-get-lead@example.com")
    headers = auth_headers(rep)

    response = await client.get(f"{LEADS_URL}/{unassigned.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == unassigned.id


async def test_get_lead_sales_rep_still_403_for_lead_owned_by_other_user(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-other-owner-get@example.com", role=UserRole.SALES_REP)
    requester = await make_user(email="rep-other-requester-get@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="other-owned-get-lead@example.com")
    headers = auth_headers(requester)

    response = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert response.status_code == 403


async def test_list_leads_delivery_sme_sees_unassigned_lead(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    sme = await make_user(email="sme-unassigned-list@example.com", role=UserRole.DELIVERY_SME)
    other_rep = await make_user(email="rep-unassigned-sme-owner@example.com", role=UserRole.SALES_REP)
    unassigned = await make_lead(owner_id=None, email="unassigned-sme-list-lead@example.com")
    await make_lead(owner_id=other_rep.id, email="other-owned-sme-list-lead@example.com")
    headers = auth_headers(sme)

    response = await client.get(LEADS_URL, headers=headers)

    assert response.status_code == 200
    ids = {lead["id"] for lead in response.json()}
    assert unassigned.id in ids


async def test_get_lead_delivery_sme_can_access_unassigned_lead(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    sme = await make_user(email="sme-unassigned-get@example.com", role=UserRole.DELIVERY_SME)
    unassigned = await make_lead(owner_id=None, email="unassigned-sme-get-lead@example.com")
    headers = auth_headers(sme)

    response = await client.get(f"{LEADS_URL}/{unassigned.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == unassigned.id


async def test_get_lead_delivery_sme_still_403_for_lead_owned_by_other_user(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-other-owner-sme-get@example.com", role=UserRole.SALES_REP)
    sme = await make_user(email="sme-other-requester-get@example.com", role=UserRole.DELIVERY_SME)
    lead = await make_lead(owner_id=owner.id, email="other-owned-sme-get-lead@example.com")
    headers = auth_headers(sme)

    response = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert response.status_code == 403


async def test_list_leads_sales_rep_owner_id_param_does_not_leak_other_reps_leads(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    # An explicit owner_id filter ANDs on top of the Sales Rep's own-or-unassigned
    # base scope, so asking for another rep's owner_id yields nothing.
    rep_a = await make_user(email="rep-list-a@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-b@example.com", role=UserRole.SALES_REP)
    await make_lead(owner_id=rep_a.id, email="own-list-lead@example.com")
    await make_lead(owner_id=rep_b.id, email="other-list-lead@example.com")
    headers = auth_headers(rep_a)

    response = await client.get(LEADS_URL, params={"owner_id": rep_b.id}, headers=headers)

    assert response.status_code == 200
    assert response.json() == []


async def test_list_leads_sales_rep_only_sees_own_leads(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    rep_a = await make_user(email="rep-list-own-a@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-own-b@example.com", role=UserRole.SALES_REP)
    own_lead = await make_lead(owner_id=rep_a.id, email="own-list-lead-2@example.com")
    other_lead = await make_lead(owner_id=rep_b.id, email="other-list-lead-2@example.com")
    headers = auth_headers(rep_a)

    response = await client.get(LEADS_URL, headers=headers)

    assert response.status_code == 200
    ids = [lead["id"] for lead in response.json()]
    assert own_lead.id in ids
    assert other_lead.id not in ids


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


async def test_list_leads_search_still_matches_unassigned_leads(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    rep = await make_user(email="rep-search-unassigned@example.com", role=UserRole.SALES_REP)
    unassigned_match = await make_lead(
        owner_id=None, email="unassigned-searchable@example.com", company="Searchable Unassigned Co"
    )
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, params={"search": "searchable unassigned"}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()] == [unassigned_match.id]


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


# --- POST /api/v1/leads/{lead_id}/convert -----------------------------------


async def test_convert_lead_to_account_returns_201_with_account_body(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-convert@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(
        owner_id=owner.id,
        email="convert-lead-api@example.com",
        company="Convert API Co",
        domain="convert-api.example.com",
    )
    headers = auth_headers(owner)

    response = await client.post(f"{LEADS_URL}/{lead.id}/convert", headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["company"] == "Convert API Co"
    assert body["domain"] == "convert-api.example.com"
    assert body["owner_id"] == owner.id
    assert body["source_lead_id"] == lead.id
    assert "id" in body


async def test_convert_lead_to_account_returns_404_for_nonexistent_lead(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-convert-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(f"{LEADS_URL}/999999/convert", headers=headers)

    assert response.status_code == 404


async def test_convert_lead_to_account_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-convert@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-convert@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-forbidden-api@example.com")
    headers = auth_headers(other_rep)

    response = await client.post(f"{LEADS_URL}/{lead.id}/convert", headers=headers)

    assert response.status_code == 403


async def test_convert_lead_to_account_returns_409_for_already_converted_lead(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-convert-twice@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-twice-api@example.com")
    headers = auth_headers(owner)
    first = await client.post(f"{LEADS_URL}/{lead.id}/convert", headers=headers)
    assert first.status_code == 201

    response = await client.post(f"{LEADS_URL}/{lead.id}/convert", headers=headers)

    assert response.status_code == 409


async def test_convert_lead_to_account_sets_is_converted_on_the_lead(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-convert-flag-api@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-flag-api@example.com")
    headers = auth_headers(owner)

    convert_response = await client.post(f"{LEADS_URL}/{lead.id}/convert", headers=headers)
    assert convert_response.status_code == 201

    get_response = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert get_response.status_code == 200
    assert get_response.json()["is_converted"] is True


async def test_convert_lead_missing_tier_and_owner_returns_400(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    manager = await make_user(email="manager-convert-missing@example.com", role=UserRole.SALES_MANAGER)
    lead = await make_lead(
        owner_id=None, email="convert-missing-fields@example.com", tier=None
    )
    headers = auth_headers(manager)

    response = await client.post(f"{LEADS_URL}/{lead.id}/convert", headers=headers)

    assert response.status_code == 400


async def test_convert_lead_missing_tier_and_owner_with_override_returns_201(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    manager = await make_user(email="manager-convert-override@example.com", role=UserRole.SALES_MANAGER)
    new_owner = await make_user(email="rep-convert-override-owner@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(
        owner_id=None, email="convert-override-fields@example.com", tier=None
    )
    headers = auth_headers(manager)

    response = await client.post(
        f"{LEADS_URL}/{lead.id}/convert",
        json={"tier": "gold", "owner_id": new_owner.id},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["tier"] == "gold"
    assert body["owner_id"] == new_owner.id


# --- Lead.tier / Lead.owner_id optional --------------------------------------


async def test_create_lead_without_tier_and_owner_id_returns_201(
    client: AsyncClient, make_user, auth_headers
):
    manager = await make_user(email="manager-no-tier-owner@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(manager)
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "company": "Acme Corp",
        "email": "no-tier-owner@example.com",
        "source": "website",
    }

    response = await client.post(LEADS_URL, json=payload, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["tier"] is None
    assert body["owner_id"] is None


# --- Lead.status --------------------------------------------------------------


async def test_create_lead_status_defaults_to_not_contacted(
    client: AsyncClient, make_user, auth_headers
):
    manager = await make_user(email="manager-status-default@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(manager)

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=manager.id, email="status-default@example.com"), headers=headers
    )

    assert response.status_code == 201
    assert response.json()["status"] == "not_contacted"


async def test_create_lead_status_settable_explicitly(client: AsyncClient, make_user, auth_headers):
    manager = await make_user(email="manager-status-explicit@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(manager)

    response = await client.post(
        LEADS_URL,
        json=_lead_payload(
            owner_id=manager.id, email="status-explicit@example.com", status="contacted"
        ),
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "contacted"


async def test_update_lead_status_via_patch(client: AsyncClient, make_user, auth_headers, make_lead):
    owner = await make_user(email="rep-status-patch@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="status-patch@example.com")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{LEADS_URL}/{lead.id}", json={"status": "junk_lead"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "junk_lead"


async def test_list_leads_filters_by_status(client: AsyncClient, make_user, auth_headers, make_lead):
    manager = await make_user(email="manager-status-filter@example.com", role=UserRole.SALES_MANAGER)
    rep = await make_user(email="rep-status-filter@example.com", role=UserRole.SALES_REP)
    junk = await make_lead(owner_id=rep.id, email="status-filter-junk@example.com", status="junk_lead")
    await make_lead(owner_id=rep.id, email="status-filter-not-contacted@example.com")
    headers = auth_headers(manager)

    response = await client.get(LEADS_URL, params={"status": "junk_lead"}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()] == [junk.id]
