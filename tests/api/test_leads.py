"""HTTP-level contract for /api/v1/leads.

Covers: 201 create / 200 update as each allowed role (single POST route,
dispatched on whether `id` is present in the body), 409 duplicate email, 422
missing required field, 401 no auth, 403 for Delivery SME (list + create) and
for a non-owning Sales Rep (get/update/delete), 200 list scoped by role and by
each filter (owner_id/source/search), 404 for a missing lead, 204 DELETE,
bulk import template download (xlsx/csv) and file upload (xlsx/csv, plus a
rejected non-spreadsheet extension).
"""

import io

import openpyxl
import pytest_asyncio
from httpx import AsyncClient

from tests.support.roles import UserRole

LEADS_URL = "/api/v1/leads"


class FakeEmailSender:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.calls.append({"to": to, "subject": subject, "body": body})


@pytest_asyncio.fixture(autouse=True)
async def fake_email_sender(client: AsyncClient):
    """Every test here creates leads over HTTP, which now sends an admin
    notification email; override with a fake so none of them touch real SMTP.
    Autouse (rather than an explicit param on every test) since this applies
    uniformly across the whole file."""
    from app.core.deps import get_email_sender
    from app.main import app

    fake = FakeEmailSender()
    app.dependency_overrides[get_email_sender] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_email_sender, None)


def _lead_payload(**overrides) -> dict:
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "company": "Acme Corp",
        "email": "jane.doe@acme.com",
        "source": "website",
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


async def test_create_lead_empty_extra_contact_returns_422(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-empty-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        LEADS_URL,
        json=_lead_payload(
            owner_id=rep.id, email="empty-contact@example.com", contacts=[{"email": None, "phone": None}]
        ),
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_lead_malformed_extra_contact_email_returns_422(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-bad-contact-email@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        LEADS_URL,
        json=_lead_payload(
            owner_id=rep.id,
            email="bad-contact-email@example.com",
            contacts=[{"email": "not-an-email"}],
        ),
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


async def test_create_lead_notifies_admin_by_email(
    client: AsyncClient, make_user, auth_headers, fake_email_sender
):
    admin = await make_user(email="admin-gets-notified@example.com", role=UserRole.ADMIN)
    rep = await make_user(email="rep-triggers-notify@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=rep.id, email="notify-me@example.com"), headers=headers
    )

    assert response.status_code == 201
    assert any(call["to"] == admin.email for call in fake_email_sender.calls)


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
    ids = {lead["id"] for lead in response.json()["items"]}
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
    ids = {lead["id"] for lead in response.json()["items"]}
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
    assert response.json()["items"] == []


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
    ids = [lead["id"] for lead in response.json()["items"]]
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
    ids = {lead["id"] for lead in response.json()["items"]}
    assert {lead_a.id, lead_b.id} <= ids


async def test_list_leads_total_reflects_full_filtered_count_not_page_size(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    rep = await make_user(email="rep-total-count@example.com", role=UserRole.SALES_REP)
    for i in range(3):
        await make_lead(owner_id=rep.id, email=f"total-count-{i}@example.com")
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, params={"limit": 2, "offset": 0}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0


async def test_list_leads_filters_by_owner_id(client: AsyncClient, make_user, auth_headers, make_lead):
    manager = await make_user(email="manager-list-owner@example.com", role=UserRole.SALES_MANAGER)
    rep_a = await make_user(email="rep-filter-owner-a@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-filter-owner-b@example.com", role=UserRole.SALES_REP)
    lead_a = await make_lead(owner_id=rep_a.id, email="filter-owner-a@example.com")
    await make_lead(owner_id=rep_b.id, email="filter-owner-b@example.com")
    headers = auth_headers(manager)

    response = await client.get(LEADS_URL, params={"owner_id": rep_a.id}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()["items"]] == [lead_a.id]


async def test_list_leads_filters_by_source(client: AsyncClient, make_user, auth_headers, make_lead):
    rep = await make_user(email="rep-filter-source@example.com", role=UserRole.SALES_REP)
    website_lead = await make_lead(owner_id=rep.id, email="filter-source-website@example.com", source="website")
    await make_lead(owner_id=rep.id, email="filter-source-referral@example.com", source="referral")
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, params={"source": "website"}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()["items"]] == [website_lead.id]


async def test_list_leads_filters_by_search(client: AsyncClient, make_user, auth_headers, make_lead):
    rep = await make_user(email="rep-filter-search@example.com", role=UserRole.SALES_REP)
    match = await make_lead(
        owner_id=rep.id, email="filter-search-match@example.com", company="Searchable Widgets Inc"
    )
    await make_lead(owner_id=rep.id, email="filter-search-nomatch@example.com", company="Nothing Co")
    headers = auth_headers(rep)

    response = await client.get(LEADS_URL, params={"search": "searchable"}, headers=headers)

    assert response.status_code == 200
    assert [lead["id"] for lead in response.json()["items"]] == [match.id]


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
    assert [lead["id"] for lead in response.json()["items"]] == [unassigned_match.id]


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


async def test_list_leads_returns_owner_name_and_updated_at(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owner-name@example.com", role=UserRole.SALES_REP, first_name="Karthick")
    await make_lead(owner_id=owner.id, email="owner-name-list-lead@example.com")
    headers = auth_headers(owner)

    response = await client.get(LEADS_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()["items"][0]
    assert body["owner_name"] == "Karthick"
    assert "updated_at" in body


async def test_get_lead_detail_includes_contacts_activities_and_owner_name(
    client: AsyncClient, make_user, auth_headers
):
    owner = await make_user(email="rep-detail@example.com", role=UserRole.SALES_REP, first_name="Vishnu")
    headers = auth_headers(owner)

    create_response = await client.post(
        LEADS_URL,
        json=_lead_payload(
            owner_id=owner.id,
            email="detail-lead-created@example.com",
            phone="+1-555-0200",
            contacts=[{"email": "extra@example.com"}],
        ),
        headers=headers,
    )
    created_lead_id = create_response.json()["id"]

    await client.post(
        f"{LEADS_URL}/{created_lead_id}/activities",
        json={"type": "call", "note": "Discussed pricing"},
        headers=headers,
    )

    response = await client.get(f"{LEADS_URL}/{created_lead_id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["owner_name"] == "Vishnu"
    assert "updated_at" in body

    contact_emails = {contact["email"] for contact in body["contacts"]}
    assert contact_emails == {"detail-lead-created@example.com", "extra@example.com"}

    assert body["activity_count"] == 1
    activity = body["activities"][0]
    assert activity["type"] == "call"
    assert activity["note"] == "Discussed pricing"
    assert activity["created_by_name"] == "Vishnu"


async def test_get_lead_detail_activities_are_in_insertion_order(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    # Ordered by id, not created_at: created_at is now()-based (fixed for the
    # whole transaction), so activities logged back-to-back here would tie
    # and could sort arbitrarily if ordering relied on it instead.
    owner = await make_user(email="rep-activity-order@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="activity-order-lead@example.com")
    headers = auth_headers(owner)

    await client.post(
        f"{LEADS_URL}/{lead.id}/activities", json={"type": "note", "note": "first"}, headers=headers
    )
    await client.post(
        f"{LEADS_URL}/{lead.id}/activities", json={"type": "call", "note": "second"}, headers=headers
    )

    response = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert response.status_code == 200
    notes = [activity["note"] for activity in response.json()["activities"]]
    assert notes == ["first", "second"]


async def test_update_lead_partial_patch_returns_200(client: AsyncClient, make_user, auth_headers, make_lead):
    owner = await make_user(email="rep-patch@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="patch-me@example.com", company="Old Co")
    headers = auth_headers(owner)

    response = await client.post(
        LEADS_URL, json={"id": lead.id, "company": "New Co"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company"] == "New Co"
    assert body["email"] == "patch-me@example.com"


async def test_update_lead_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-patch-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(LEADS_URL, json={"id": 999999, "company": "New Co"}, headers=headers)

    assert response.status_code == 404


async def test_update_lead_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-patch@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-patch@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="patch-forbidden@example.com")
    headers = auth_headers(other_rep)

    response = await client.post(
        LEADS_URL, json={"id": lead.id, "company": "New Co"}, headers=headers
    )

    assert response.status_code == 403


async def test_update_lead_duplicate_email_returns_409(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-patch-dup@example.com", role=UserRole.SALES_REP)
    await make_lead(owner_id=owner.id, email="patch-dup-taken@example.com")
    lead_to_update = await make_lead(owner_id=owner.id, email="patch-dup-original@example.com")
    headers = auth_headers(owner)

    response = await client.post(
        LEADS_URL,
        json={"id": lead_to_update.id, "email": "patch-dup-taken@example.com"},
        headers=headers,
    )

    assert response.status_code == 409


async def test_upsert_lead_dispatches_to_create_when_id_omitted(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-upsert-create@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        LEADS_URL, json=_lead_payload(owner_id=rep.id, email="upsert-create@example.com"), headers=headers
    )

    assert response.status_code == 201
    assert "id" in response.json()


async def test_upsert_lead_dispatches_to_update_when_id_present(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-upsert-update@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="upsert-update@example.com", company="Old Co")
    headers = auth_headers(owner)

    response = await client.post(
        LEADS_URL, json={"id": lead.id, "company": "Updated Co"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == lead.id
    assert body["company"] == "Updated Co"


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

    response = await client.post(
        f"{LEADS_URL}/{lead.id}/convert", json={"tier": "gold"}, headers=headers
    )

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
    first = await client.post(f"{LEADS_URL}/{lead.id}/convert", json={"tier": "gold"}, headers=headers)
    assert first.status_code == 201

    response = await client.post(f"{LEADS_URL}/{lead.id}/convert", json={"tier": "gold"}, headers=headers)

    assert response.status_code == 409


async def test_convert_lead_to_account_sets_is_converted_on_the_lead(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-convert-flag-api@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="convert-flag-api@example.com")
    headers = auth_headers(owner)

    convert_response = await client.post(
        f"{LEADS_URL}/{lead.id}/convert", json={"tier": "gold"}, headers=headers
    )
    assert convert_response.status_code == 201

    get_response = await client.get(f"{LEADS_URL}/{lead.id}", headers=headers)

    assert get_response.status_code == 200
    assert get_response.json()["is_converted"] is True


async def test_convert_lead_missing_tier_and_owner_returns_400(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    manager = await make_user(email="manager-convert-missing@example.com", role=UserRole.SALES_MANAGER)
    lead = await make_lead(owner_id=None, email="convert-missing-fields@example.com")
    headers = auth_headers(manager)

    response = await client.post(f"{LEADS_URL}/{lead.id}/convert", headers=headers)

    assert response.status_code == 400


async def test_convert_lead_missing_tier_and_owner_with_override_returns_201(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    manager = await make_user(email="manager-convert-override@example.com", role=UserRole.SALES_MANAGER)
    new_owner = await make_user(email="rep-convert-override-owner@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=None, email="convert-override-fields@example.com")
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


# --- Lead.owner_id optional ---------------------------------------------------


async def test_create_lead_without_owner_id_returns_201(client: AsyncClient, make_user, auth_headers):
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


async def test_update_lead_status_via_post(client: AsyncClient, make_user, auth_headers, make_lead):
    owner = await make_user(email="rep-status-patch@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="status-patch@example.com")
    headers = auth_headers(owner)

    response = await client.post(
        LEADS_URL, json={"id": lead.id, "status": "junk_lead"}, headers=headers
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
    assert [lead["id"] for lead in response.json()["items"]] == [junk.id]


# --- POST /api/v1/leads/{lead_id}/activities ---------------------------------


async def test_create_lead_activity_returns_201(client: AsyncClient, make_user, auth_headers, make_lead):
    owner = await make_user(email="rep-activity-create@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="activity-create-lead@example.com")
    headers = auth_headers(owner)

    response = await client.post(
        f"{LEADS_URL}/{lead.id}/activities",
        json={"type": "call", "note": "Discussed pricing"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["lead_id"] == lead.id
    assert body["type"] == "call"
    assert body["note"] == "Discussed pricing"
    assert body["created_by"] == owner.id
    assert "id" in body


async def test_create_lead_activity_returns_404_for_nonexistent_lead(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-activity-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        f"{LEADS_URL}/999999/activities", json={"type": "note", "note": "x"}, headers=headers
    )

    assert response.status_code == 404


async def test_create_lead_activity_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-activity@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-activity@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="activity-forbidden-api@example.com")
    headers = auth_headers(other_rep)

    response = await client.post(
        f"{LEADS_URL}/{lead.id}/activities", json={"type": "note", "note": "x"}, headers=headers
    )

    assert response.status_code == 403


async def test_create_lead_activity_bad_type_enum_value_returns_422(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-activity-bad-type@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="activity-bad-type-lead@example.com")
    headers = auth_headers(owner)

    response = await client.post(
        f"{LEADS_URL}/{lead.id}/activities",
        json={"type": "not_a_real_type", "note": "x"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_lead_activity_empty_note_returns_422(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-activity-empty-note@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="activity-empty-note-lead@example.com")
    headers = auth_headers(owner)

    response = await client.post(
        f"{LEADS_URL}/{lead.id}/activities",
        json={"type": "note", "note": ""},
        headers=headers,
    )

    assert response.status_code == 422


async def test_download_lead_import_template_xlsx(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-template-xlsx@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{LEADS_URL}/import/template?format=xlsx", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "attachment" in response.headers["content-disposition"]


async def test_download_lead_import_template_csv(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-template-csv@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{LEADS_URL}/import/template?format=csv", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]


async def test_download_lead_import_template_defaults_to_xlsx(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-template-default@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{LEADS_URL}/import/template", headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")


async def test_upload_lead_import_csv_creates_leads(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-upload-csv@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    csv_content = (
        b"first_name,last_name,company,domain,job_title,linkedin_url,email,phone,"
        b"source,status,follow_up_note\n"
        b"Jane,Doe,Acme Corp,acme.com,VP,https://linkedin.com/in/jane,jane.upload.csv@acme.com,"
        b"+1 555 0000,website,,\n"
    )

    response = await client.post(
        f"{LEADS_URL}/import",
        headers=headers,
        files={"file": ("leads.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert body["errors"] == []
    leads = await client.get(f"{LEADS_URL}?search=Acme+Corp", headers=headers)
    created = next(item for item in leads.json()["items"] if item["email"] == "jane.upload.csv@acme.com")
    assert created["owner_id"] == rep.id


async def test_upload_lead_import_xlsx_creates_leads(client: AsyncClient, make_user, auth_headers):
    import io

    from openpyxl import Workbook

    rep = await make_user(email="rep-upload-xlsx@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "first_name",
            "last_name",
            "company",
            "domain",
            "job_title",
            "linkedin_url",
            "email",
            "phone",
            "source",
            "status",
            "follow_up_note",
        ]
    )
    sheet.append(["Jane", "Doe", "Acme Corp", "acme.com", "VP", "", "jane.upload.xlsx@acme.com", "", "website", "", ""])
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = await client.post(
        f"{LEADS_URL}/import",
        headers=headers,
        files={
            "file": (
                "leads.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert body["errors"] == []
    leads = await client.get(f"{LEADS_URL}?search=Acme+Corp", headers=headers)
    created = next(item for item in leads.json()["items"] if item["email"] == "jane.upload.xlsx@acme.com")
    assert created["owner_id"] == rep.id


async def test_upload_lead_import_rejects_bad_extension(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-upload-bad-ext@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        f"{LEADS_URL}/import",
        headers=headers,
        files={"file": ("leads.txt", b"not a real file", "text/plain")},
    )

    assert response.status_code == 400


async def test_upload_lead_import_rejects_corrupt_xlsx_content(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-upload-corrupt@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        f"{LEADS_URL}/import",
        headers=headers,
        files={
            "file": (
                "leads.xlsx",
                b"not actually an xlsx file",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400

async def test_list_lead_activities_returns_200_filtered_by_type(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-list-activities@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="list-activities-lead@example.com")
    headers = auth_headers(owner)
    await client.post(
        f"{LEADS_URL}/{lead.id}/activities", json={"type": "call", "note": "call note"}, headers=headers
    )
    await client.post(
        f"{LEADS_URL}/{lead.id}/activities", json={"type": "note", "note": "note note"}, headers=headers
    )

    response = await client.get(f"{LEADS_URL}/{lead.id}/activities?types=call", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["type"] == "call"
    assert body[0]["created_by_name"]


async def test_list_lead_activities_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-list-activity@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-list-activity@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="list-activity-forbidden-api@example.com")

    response = await client.get(f"{LEADS_URL}/{lead.id}/activities", headers=auth_headers(other_rep))

    assert response.status_code == 403


async def test_update_lead_activity_returns_200(client: AsyncClient, make_user, auth_headers, make_lead):
    owner = await make_user(email="rep-update-activity@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="update-activity-lead@example.com")
    headers = auth_headers(owner)
    created = (
        await client.post(
            f"{LEADS_URL}/{lead.id}/activities", json={"type": "note", "note": "original"}, headers=headers
        )
    ).json()

    response = await client.patch(
        f"{LEADS_URL}/{lead.id}/activities/{created['id']}",
        json={"note": "revised"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["note"] == "revised"
    assert body["updated_by"] == owner.id
    assert body["updated_by_name"]


async def test_update_lead_activity_returns_404_for_missing_activity(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-update-missing-activity@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="update-missing-activity-lead@example.com")

    response = await client.patch(
        f"{LEADS_URL}/{lead.id}/activities/999999",
        json={"note": "revised"},
        headers=auth_headers(owner),
    )

    assert response.status_code == 404


async def test_delete_lead_activity_returns_204_then_404_on_refetch(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-delete-activity@example.com", role=UserRole.SALES_REP)
    admin = await make_user(email="admin-delete-activity@example.com", role=UserRole.ADMIN)
    lead = await make_lead(owner_id=owner.id, email="delete-activity-lead@example.com")
    owner_headers = auth_headers(owner)
    created = (
        await client.post(
            f"{LEADS_URL}/{lead.id}/activities", json={"type": "note", "note": "to delete"}, headers=owner_headers
        )
    ).json()

    delete_response = await client.delete(
        f"{LEADS_URL}/{lead.id}/activities/{created['id']}", headers=auth_headers(admin)
    )

    assert delete_response.status_code == 204
    refetch = await client.patch(
        f"{LEADS_URL}/{lead.id}/activities/{created['id']}", json={"note": "x"}, headers=owner_headers
    )
    assert refetch.status_code == 404


async def test_delete_lead_activity_returns_403_for_lead_owner(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-delete-forbidden@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(owner_id=owner.id, email="delete-activity-forbidden-lead@example.com")
    headers = auth_headers(owner)
    created = (
        await client.post(
            f"{LEADS_URL}/{lead.id}/activities", json={"type": "note", "note": "cannot delete"}, headers=headers
        )
    ).json()

    response = await client.delete(f"{LEADS_URL}/{lead.id}/activities/{created['id']}", headers=headers)

    assert response.status_code == 403


async def test_update_lead_activity_returns_403_for_non_owner(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-owns-update-activity@example.com", role=UserRole.SALES_REP)
    admin = await make_user(email="admin-update-activity@example.com", role=UserRole.ADMIN)
    lead = await make_lead(owner_id=owner.id, email="update-activity-forbidden-lead@example.com")
    created = (
        await client.post(
            f"{LEADS_URL}/{lead.id}/activities",
            json={"type": "note", "note": "cannot edit"},
            headers=auth_headers(owner),
        )
    ).json()

    response = await client.patch(
        f"{LEADS_URL}/{lead.id}/activities/{created['id']}",
        json={"note": "revised"},
        headers=auth_headers(admin),
    )

    assert response.status_code == 403


async def test_list_leads_to_export_returns_valid_xlsx_with_expected_rows(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-export-lead@example.com", role=UserRole.SALES_REP)
    await make_lead(owner_id=owner.id, email="export-xlsx-lead@example.com", company="Export Xlsx Lead Co")
    headers = auth_headers(owner)

    response = await client.get(LEADS_URL, params={"to_export": "true"}, headers=headers)

    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "leads.xlsx" in response.headers["content-disposition"]

    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    sheet = workbook.active
    header = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    assert header == ["Name", "Email", "Phone", "Company", "Source", "Status", "Owner"]
    data_rows = list(sheet.iter_rows(min_row=2, values_only=True))
    assert any(row[3] == "Export Xlsx Lead Co" for row in data_rows)


async def test_list_leads_to_export_filters_by_owner_id(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    """export must respect owner_id the same way list_leads does."""
    manager = await make_user(email="manager-export-owner-filter@example.com", role=UserRole.SALES_MANAGER)
    rep_a = await make_user(email="rep-a-export-owner-filter@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-b-export-owner-filter@example.com", role=UserRole.SALES_REP)
    await make_lead(owner_id=rep_a.id, email="owner-a-lead@example.com", company="Owner A Co")
    await make_lead(owner_id=rep_b.id, email="owner-b-lead@example.com", company="Owner B Co")
    headers = auth_headers(manager)

    response = await client.get(LEADS_URL, params={"to_export": "true", "owner_id": rep_a.id}, headers=headers)

    assert response.status_code == 200
    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    data_rows = list(workbook.active.iter_rows(min_row=2, values_only=True))
    companies = {row[3] for row in data_rows}
    assert companies == {"Owner A Co"}


async def test_leads_export_route_no_longer_exists(client: AsyncClient, make_user, auth_headers):
    """"/export" now falls through to GET /leads/{lead_id} and fails int
    path-param validation (422), since the dedicated /export route is gone."""
    owner = await make_user(email="rep-old-export-route@example.com", role=UserRole.SALES_REP)
    response = await client.get(f"{LEADS_URL}/export", headers=auth_headers(owner))
    assert response.status_code == 422


async def test_get_lead_to_export_returns_lead_and_activities_sheets(
    client: AsyncClient, make_user, auth_headers, make_lead
):
    owner = await make_user(email="rep-export-single-lead@example.com", role=UserRole.SALES_REP)
    lead = await make_lead(
        owner_id=owner.id, email="single-export-lead@example.com", company="Single Export Lead Co"
    )
    headers = auth_headers(owner)

    response = await client.get(f"{LEADS_URL}/{lead.id}", params={"to_export": "true"}, headers=headers)

    assert response.status_code == 200
    assert (
        response.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert f"lead_{lead.id}.xlsx" in response.headers["content-disposition"]

    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["Lead", "Activities"]
    lead_sheet = workbook["Lead"]
    field_col = [cell.value for cell in lead_sheet["A"]]
    assert "Company" in field_col
