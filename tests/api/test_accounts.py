"""HTTP-level contract for /api/v1/accounts.

Covers: 201 create as each allowed role, 422 missing required field
(company/domain/tier), 401 no auth, 403 for Delivery SME (list + create) and
for a non-owning Sales Rep (get/update/delete), 200 list scoped by role and by
each filter (owner_id/tier/industry/search-by-company-or-domain), 404 for a
missing account, 200 partial PATCH, 204 DELETE. Every Account response
(create/get/list) carries owner_name plus contact_count/deal_count. Plus
create-time `contacts`: saved to the `contacts` table with the new account's
id as FK, only the first needs a name (422 if it doesn't), later ones
inherit it and just need email and/or phone (422 if neither). Plus GET
/accounts/{account_id}/contacts: 200 scoped to that account's contacts, 404
for a nonexistent account, 403 for a non-owning Sales Rep. Plus GET
/accounts/{account_id}/deals: 200 scoped to that account's deals (gated on
the ACCOUNT's ownership, not deal ownership), 404 for a nonexistent account,
403 for a non-owning Sales Rep on the account.
"""

from httpx import AsyncClient

from tests.support.roles import UserRole

ACCOUNTS_URL = "/api/v1/accounts"


def _account_payload(**overrides) -> dict:
    payload = {
        "company": "Acme Corp",
        "domain": "acme.com",
        "tier": "gold",
        "owner_id": overrides.pop("owner_id"),
    }
    payload.update(overrides)
    return payload


async def test_create_account_as_sales_rep_returns_201(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-create-acc@example.com", role=UserRole.SALES_REP, first_name="Karthick")
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL, json=_account_payload(owner_id=rep.id, company="Rep Co"), headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["company"] == "Rep Co"
    assert body["tier"] == "gold"
    assert body["owner_id"] == rep.id
    assert body["owner_name"] == "Karthick"
    assert body["contact_count"] == 0
    assert body["deal_count"] == 0
    assert body["source_lead_id"] is None
    assert "id" in body


async def test_get_account_includes_owner_name_and_deal_count(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-get-acc-counts@example.com", role=UserRole.SALES_REP, first_name="Vishnu")
    account = await make_account(owner_id=owner.id, company="Counts Co")
    await make_deal(account_id=account.id, owner_id=owner.id)
    headers = auth_headers(owner)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["owner_name"] == "Vishnu"
    assert body["deal_count"] == 1
    assert body["contact_count"] == 0


async def test_list_accounts_filters_by_industry(client: AsyncClient, make_user, auth_headers, make_account):
    rep = await make_user(email="rep-filter-industry-acc@example.com", role=UserRole.SALES_REP)
    software = await make_account(owner_id=rep.id, company="Software Co", industry="Software")
    await make_account(owner_id=rep.id, company="Healthcare Co", industry="Healthcare")
    headers = auth_headers(rep)

    response = await client.get(ACCOUNTS_URL, params={"industry": "Software"}, headers=headers)

    assert response.status_code == 200
    assert [account["id"] for account in response.json()["items"]] == [software.id]


async def test_list_accounts_search_matches_domain(client: AsyncClient, make_user, auth_headers, make_account):
    rep = await make_user(email="rep-filter-search-domain-acc@example.com", role=UserRole.SALES_REP)
    match = await make_account(owner_id=rep.id, company="Domain Match Co", domain="rocketship.io")
    await make_account(owner_id=rep.id, company="No Match Co", domain="other.io")
    headers = auth_headers(rep)

    response = await client.get(ACCOUNTS_URL, params={"search": "rocketship"}, headers=headers)

    assert response.status_code == 200
    assert [account["id"] for account in response.json()["items"]] == [match.id]


async def test_create_account_as_sales_manager_returns_201(client: AsyncClient, make_user, auth_headers):
    manager = await make_user(email="manager-create-acc@example.com", role=UserRole.SALES_MANAGER)
    rep = await make_user(email="rep-owned-by-manager-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(manager)

    response = await client.post(
        ACCOUNTS_URL, json=_account_payload(owner_id=rep.id, company="Manager Created Co"), headers=headers
    )

    assert response.status_code == 201


async def test_create_account_as_admin_returns_201(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-create-acc@example.com", role=UserRole.ADMIN)
    rep = await make_user(email="rep-owned-by-admin-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(admin)

    response = await client.post(
        ACCOUNTS_URL, json=_account_payload(owner_id=rep.id, company="Admin Created Co"), headers=headers
    )

    assert response.status_code == 201


async def test_create_account_with_industry_city_description_returns_201(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-extra-fields@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL,
        json=_account_payload(
            owner_id=rep.id,
            company="Extra Fields Co",
            industry="Software",
            city="Austin",
            description="A promising account",
        ),
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["industry"] == "Software"
    assert body["city"] == "Austin"
    assert body["description"] == "A promising account"


async def test_create_account_without_industry_city_description_returns_201_with_nulls(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-no-extra-fields@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL, json=_account_payload(owner_id=rep.id, company="No Extra Fields Co"), headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["industry"] is None
    assert body["city"] is None
    assert body["description"] is None


async def test_update_account_can_update_industry_city_description(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-patch-acc-extra-fields@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Extra Fields Co")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{ACCOUNTS_URL}/{account.id}",
        json={"industry": "Healthcare", "city": "Denver", "description": "Updated description"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["industry"] == "Healthcare"
    assert body["city"] == "Denver"
    assert body["description"] == "Updated description"


async def test_create_account_with_linkedin_url_returns_201(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-create-acc-linkedin@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL,
        json=_account_payload(
            owner_id=rep.id,
            company="LinkedIn Co",
            linkedin_url="https://linkedin.com/company/linkedin-co",
        ),
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["linkedin_url"] == "https://linkedin.com/company/linkedin-co"


async def test_create_account_without_linkedin_url_returns_201_with_null(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-no-linkedin@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL, json=_account_payload(owner_id=rep.id, company="No LinkedIn Co"), headers=headers
    )

    assert response.status_code == 201
    assert response.json()["linkedin_url"] is None


async def test_create_account_missing_company_returns_422(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-missing-company-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    payload = _account_payload(owner_id=rep.id)
    del payload["company"]

    response = await client.post(ACCOUNTS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_account_missing_domain_returns_422(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-missing-domain-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    payload = _account_payload(owner_id=rep.id)
    del payload["domain"]

    response = await client.post(ACCOUNTS_URL, json=payload, headers=headers)

    assert response.status_code == 422


# --- create-time contacts -----------------------------------------------------


async def test_create_account_saves_contacts_with_shared_name(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-contacts@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    create_response = await client.post(
        ACCOUNTS_URL,
        json=_account_payload(
            owner_id=rep.id,
            company="Contacts Co",
            contacts=[
                {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
                {"email": "jane-work@example.com", "phone": "+1-555-0100"},
            ],
        ),
        headers=headers,
    )
    assert create_response.status_code == 201
    account_id = create_response.json()["id"]

    contacts_response = await client.get(f"{ACCOUNTS_URL}/{account_id}/contacts", headers=headers)

    assert contacts_response.status_code == 200
    contacts = contacts_response.json()["items"]
    assert len(contacts) == 2
    assert all(contact["first_name"] == "Jane" for contact in contacts)
    emails = {contact["email"] for contact in contacts}
    assert emails == {"jane@example.com", "jane-work@example.com"}


async def test_create_account_without_contacts_creates_none(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-no-contacts@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    create_response = await client.post(
        ACCOUNTS_URL, json=_account_payload(owner_id=rep.id, company="No Contacts Co"), headers=headers
    )
    assert create_response.status_code == 201
    account_id = create_response.json()["id"]

    contacts_response = await client.get(f"{ACCOUNTS_URL}/{account_id}/contacts", headers=headers)

    assert contacts_response.status_code == 200
    assert contacts_response.json()["items"] == []


async def test_create_account_first_contact_missing_first_name_returns_422(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-unnamed-first@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL,
        json=_account_payload(owner_id=rep.id, contacts=[{"email": "no-name@example.com"}]),
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_account_second_contact_without_email_or_phone_returns_422(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-bad-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL,
        json=_account_payload(
            owner_id=rep.id,
            contacts=[
                {"first_name": "Jane", "email": "jane@example.com"},
                {"email": None, "phone": None},
            ],
        ),
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_account_bad_tier_enum_value_returns_422(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-bad-tier-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL,
        json=_account_payload(owner_id=rep.id, tier="not_a_real_tier"),
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_account_no_auth_header_returns_401(client: AsyncClient, make_user):
    rep = await make_user(email="rep-no-auth-acc@example.com", role=UserRole.SALES_REP)

    response = await client.post(ACCOUNTS_URL, json=_account_payload(owner_id=rep.id))

    assert response.status_code == 401


async def test_create_account_as_delivery_sme_returns_403(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-create-acc@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.post(ACCOUNTS_URL, json=_account_payload(owner_id=sme.id), headers=headers)

    assert response.status_code == 403


async def test_list_accounts_as_delivery_sme_returns_403(client: AsyncClient, make_user, auth_headers):
    sme = await make_user(email="sme-list-acc@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.get(ACCOUNTS_URL, headers=headers)

    assert response.status_code == 403


async def test_list_accounts_sales_rep_only_sees_own_accounts(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep_a = await make_user(email="rep-list-a-acc@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-b-acc@example.com", role=UserRole.SALES_REP)
    own_account = await make_account(owner_id=rep_a.id, company="Own List Co")
    await make_account(owner_id=rep_b.id, company="Other List Co")
    headers = auth_headers(rep_a)

    response = await client.get(ACCOUNTS_URL, params={"owner_id": rep_b.id}, headers=headers)

    assert response.status_code == 200
    body = response.json()["items"]
    assert [account["id"] for account in body] == [own_account.id]


async def test_list_accounts_manager_sees_all_accounts(
    client: AsyncClient, make_user, auth_headers, make_account
):
    manager = await make_user(email="manager-list-acc@example.com", role=UserRole.SALES_MANAGER)
    rep_a = await make_user(email="rep-list-c-acc@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-list-d-acc@example.com", role=UserRole.SALES_REP)
    account_a = await make_account(owner_id=rep_a.id, company="List Co A")
    account_b = await make_account(owner_id=rep_b.id, company="List Co B")
    headers = auth_headers(manager)

    response = await client.get(ACCOUNTS_URL, headers=headers)

    assert response.status_code == 200
    ids = {account["id"] for account in response.json()["items"]}
    assert {account_a.id, account_b.id} <= ids


async def test_list_accounts_admin_sees_all_accounts(
    client: AsyncClient, make_user, auth_headers, make_account
):
    admin = await make_user(email="admin-list-acc@example.com", role=UserRole.ADMIN)
    rep_a = await make_user(email="rep-list-e-acc@example.com", role=UserRole.SALES_REP)
    account_a = await make_account(owner_id=rep_a.id, company="List Co E")
    headers = auth_headers(admin)

    response = await client.get(ACCOUNTS_URL, headers=headers)

    assert response.status_code == 200
    ids = {account["id"] for account in response.json()["items"]}
    assert account_a.id in ids


async def test_list_accounts_total_reflects_full_filtered_count_not_page_size(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-total-count-acc@example.com", role=UserRole.SALES_REP)
    for i in range(3):
        await make_account(owner_id=rep.id, company=f"Total Count Co {i}")
    headers = auth_headers(rep)

    response = await client.get(ACCOUNTS_URL, params={"limit": 2, "offset": 0}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3


async def test_list_accounts_filters_by_owner_id(
    client: AsyncClient, make_user, auth_headers, make_account
):
    manager = await make_user(email="manager-list-owner-acc@example.com", role=UserRole.SALES_MANAGER)
    rep_a = await make_user(email="rep-filter-owner-a-acc@example.com", role=UserRole.SALES_REP)
    rep_b = await make_user(email="rep-filter-owner-b-acc@example.com", role=UserRole.SALES_REP)
    account_a = await make_account(owner_id=rep_a.id, company="Filter Owner Co A")
    await make_account(owner_id=rep_b.id, company="Filter Owner Co B")
    headers = auth_headers(manager)

    response = await client.get(ACCOUNTS_URL, params={"owner_id": rep_a.id}, headers=headers)

    assert response.status_code == 200
    assert [account["id"] for account in response.json()["items"]] == [account_a.id]


async def test_list_accounts_filters_by_tier(client: AsyncClient, make_user, auth_headers, make_account):
    rep = await make_user(email="rep-filter-tier-acc@example.com", role=UserRole.SALES_REP)
    gold_account = await make_account(owner_id=rep.id, company="Filter Tier Gold Co", tier="gold")
    await make_account(owner_id=rep.id, company="Filter Tier Bronze Co", tier="bronze")
    headers = auth_headers(rep)

    response = await client.get(ACCOUNTS_URL, params={"tier": "gold"}, headers=headers)

    assert response.status_code == 200
    assert [account["id"] for account in response.json()["items"]] == [gold_account.id]


async def test_list_accounts_filters_by_search(client: AsyncClient, make_user, auth_headers, make_account):
    rep = await make_user(email="rep-filter-search-acc@example.com", role=UserRole.SALES_REP)
    match = await make_account(owner_id=rep.id, company="Searchable Widgets Inc")
    await make_account(owner_id=rep.id, company="Nothing Co")
    headers = auth_headers(rep)

    response = await client.get(ACCOUNTS_URL, params={"search": "searchable"}, headers=headers)

    assert response.status_code == 200
    assert [account["id"] for account in response.json()["items"]] == [match.id]


async def test_get_account_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-get-404-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{ACCOUNTS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_get_account_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-owns-get-acc@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-get-acc@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Get Forbidden Co")
    headers = auth_headers(other_rep)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}", headers=headers)

    assert response.status_code == 403


async def test_get_account_returns_200_for_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-owns-get-ok-acc@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Get Ok Co")
    headers = auth_headers(owner)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == account.id


# --- GET /accounts/{account_id}/overview -------------------------------------


async def test_get_account_overview_returns_200_with_computed_fields(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal, make_contact
):
    owner = await make_user(email="rep-overview@example.com", role=UserRole.SALES_REP, first_name="Karthick")
    account = await make_account(
        owner_id=owner.id, company="Overview Co", industry="IT Services", city="San Francisco"
    )
    await make_contact(account_id=account.id, first_name="Sarah", job_title="CTO")
    await make_deal(account_id=account.id, owner_id=owner.id, deal_name="Cloud Migration", value=650_000)
    await make_deal(
        account_id=account.id,
        owner_id=owner.id,
        deal_name="Closed Deal",
        value=999_999,
        stage="closed_won",
    )
    headers = auth_headers(owner)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}/overview", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["company"] == "Overview Co"
    assert body["owner_name"] == "Karthick"
    assert body["industry"] == "IT Services"
    assert body["open_deal_value"] == 650_000
    assert [deal["deal_name"] for deal in body["active_deals"]] == ["Cloud Migration"]
    assert [contact["first_name"] for contact in body["key_contacts"]] == ["Sarah"]
    assert body["last_activity"] is None
    assert body["next_step"] is None
    assert body["total_arr"] is None


async def test_get_account_overview_returns_404_for_nonexistent_id(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-overview-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{ACCOUNTS_URL}/999999/overview", headers=headers)

    assert response.status_code == 404


async def test_get_account_overview_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-owns-overview@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-overview@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Overview Forbidden Co")
    headers = auth_headers(other_rep)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}/overview", headers=headers)

    assert response.status_code == 403


async def test_update_account_partial_patch_returns_200(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-patch-acc@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Old Patch Co", domain="old-patch.example.com")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{ACCOUNTS_URL}/{account.id}", json={"company": "New Patch Co"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company"] == "New Patch Co"
    assert body["domain"] == "old-patch.example.com"


async def test_update_account_adds_contacts_returns_200(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-patch-acc-contacts@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Contacts Co")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{ACCOUNTS_URL}/{account.id}",
        json={
            "contacts": [
                {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
                {"email": "jane-work@example.com", "phone": "+1-555-0100"},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["contact_count"] == 2

    contacts_response = await client.get(f"{ACCOUNTS_URL}/{account.id}/contacts", headers=headers)
    contacts = contacts_response.json()["items"]
    assert len(contacts) == 2
    assert all(contact["first_name"] == "Jane" for contact in contacts)


async def test_update_account_first_contact_missing_first_name_returns_422(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-patch-acc-unnamed@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Unnamed Co")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{ACCOUNTS_URL}/{account.id}",
        json={"contacts": [{"email": "no-name@example.com"}]},
        headers=headers,
    )

    assert response.status_code == 422


async def test_update_account_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-patch-404-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.patch(f"{ACCOUNTS_URL}/999999", json={"company": "New Co"}, headers=headers)

    assert response.status_code == 404


async def test_update_account_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-owns-patch-acc@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-patch-acc@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Forbidden Co")
    headers = auth_headers(other_rep)

    response = await client.patch(f"{ACCOUNTS_URL}/{account.id}", json={"company": "New Co"}, headers=headers)

    assert response.status_code == 403


async def test_delete_account_returns_204(client: AsyncClient, make_user, auth_headers, make_account):
    owner = await make_user(email="rep-delete-acc@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Delete Me Co")
    headers = auth_headers(owner)

    response = await client.delete(f"{ACCOUNTS_URL}/{account.id}", headers=headers)

    assert response.status_code == 204

    follow_up = await client.get(f"{ACCOUNTS_URL}/{account.id}", headers=headers)
    assert follow_up.status_code == 404


async def test_delete_account_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-delete-404-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{ACCOUNTS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_delete_account_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-owns-delete-acc@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-delete-acc@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Delete Forbidden Co")
    headers = auth_headers(other_rep)

    response = await client.delete(f"{ACCOUNTS_URL}/{account.id}", headers=headers)

    assert response.status_code == 403


# --- GET /accounts/{account_id}/contacts -------------------------------------


async def test_list_contacts_for_account_returns_200_with_scoped_contacts(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-list-contacts-acc@example.com", role=UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="Contacts Co A")
    account_b = await make_account(owner_id=owner.id, company="Contacts Co B")
    contact_a = await make_contact(account_id=account_a.id, first_name="Scoped Contact")
    await make_contact(account_id=account_b.id, first_name="Other Account Contact")
    headers = auth_headers(owner)

    response = await client.get(f"{ACCOUNTS_URL}/{account_a.id}/contacts", headers=headers)

    assert response.status_code == 200
    body = response.json()["items"]
    assert [contact["id"] for contact in body] == [contact_a.id]


async def test_list_contacts_for_account_total_reflects_full_count_not_page_size(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-contacts-total@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Contacts Total Co")
    for i in range(3):
        await make_contact(account_id=account.id, first_name=f"Contact {i}")
    headers = auth_headers(owner)

    response = await client.get(
        f"{ACCOUNTS_URL}/{account.id}/contacts", params={"limit": 2, "offset": 0}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3


async def test_list_contacts_for_account_returns_404_for_nonexistent_account(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-list-contacts-404-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{ACCOUNTS_URL}/999999/contacts", headers=headers)

    assert response.status_code == 404


async def test_list_contacts_for_account_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-owns-list-contacts-acc@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(
        email="rep-not-owner-list-contacts-acc@example.com", role=UserRole.SALES_REP
    )
    account = await make_account(owner_id=owner.id, company="Contacts Forbidden Co")
    await make_contact(account_id=account.id)
    headers = auth_headers(other_rep)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}/contacts", headers=headers)

    assert response.status_code == 403


async def test_list_contacts_for_account_includes_is_primary(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-list-contacts-primary@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Primary Flag Co")
    await make_contact(account_id=account.id, first_name="Primary One", is_primary=True)
    await make_contact(account_id=account.id, first_name="Not Primary")
    headers = auth_headers(owner)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}/contacts", headers=headers)

    assert response.status_code == 200
    by_name = {c["first_name"]: c["is_primary"] for c in response.json()["items"]}
    assert by_name == {"Primary One": True, "Not Primary": False}


# --- POST /accounts/{account_id}/contacts (Add/Edit Contact modal, upsert) --


async def test_create_account_contact_returns_201(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-create-acc-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Add Contact Co")
    headers = auth_headers(owner)

    response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={
            "first_name": "Sarah",
            "last_name": "Jenkins",
            "job_title": "Chief Technology Officer",
            "linkedin_url": "https://linkedin.com/in/sarahjenkins",
            "email": "sarah.jenkins@nexbridge.io",
            "phone": "+91 98765 43210",
            "alternate_phone": "+1 555 000 0000",
            "is_primary": True,
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["first_name"] == "Sarah"
    assert body["job_title"] == "Chief Technology Officer"
    assert body["linkedin_url"] == "https://linkedin.com/in/sarahjenkins"
    assert body["alternate_phone"] == "+1 555 000 0000"
    assert body["is_primary"] is True
    assert "id" in body


async def test_create_account_contact_missing_first_name_returns_422(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-create-acc-contact-422@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Missing Name Co")
    headers = auth_headers(owner)

    response = await client.post(f"{ACCOUNTS_URL}/{account.id}/contacts", json={}, headers=headers)

    assert response.status_code == 422


async def test_create_account_contact_returns_404_for_nonexistent_account(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-acc-contact-404@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        f"{ACCOUNTS_URL}/999999/contacts", json={"first_name": "Jane"}, headers=headers
    )

    assert response.status_code == 404


async def test_create_account_contact_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-owns-create-acc-contact@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(
        email="rep-not-owner-create-acc-contact@example.com", role=UserRole.SALES_REP
    )
    account = await make_account(owner_id=owner.id, company="Create Contact Forbidden Co")
    headers = auth_headers(other_rep)

    response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts", json={"first_name": "Jane"}, headers=headers
    )

    assert response.status_code == 403


async def test_create_account_contact_returns_409_when_primary_already_exists(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-create-acc-contact-409@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Primary Conflict Co")
    headers = auth_headers(owner)
    first = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"first_name": "First", "is_primary": True},
        headers=headers,
    )
    assert first.status_code == 201

    response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"first_name": "Second", "is_primary": True},
        headers=headers,
    )

    assert response.status_code == 409


# --- same route, contact_id present -> update path ---------------------------


async def test_upsert_account_contact_with_contact_id_returns_200(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-update-acc-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Update Contact Co")
    headers = auth_headers(owner)
    create_response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"first_name": "Old", "job_title": "Old Title"},
        headers=headers,
    )
    contact_id = create_response.json()["id"]

    response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"contact_id": contact_id, "first_name": "New", "is_primary": True},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "New"
    assert body["job_title"] == "Old Title"
    assert body["is_primary"] is True


async def test_upsert_account_contact_returns_404_for_nonexistent_contact_id(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-update-acc-contact-404@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Update 404 Co")
    headers = auth_headers(owner)

    response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"contact_id": 999999, "first_name": "New"},
        headers=headers,
    )

    assert response.status_code == 404


async def test_upsert_account_contact_with_contact_id_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-owns-update-acc-contact@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(
        email="rep-not-owner-update-acc-contact@example.com", role=UserRole.SALES_REP
    )
    account = await make_account(owner_id=owner.id, company="Update Forbidden Co")
    headers = auth_headers(owner)
    create_response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts", json={"first_name": "Jane"}, headers=headers
    )
    contact_id = create_response.json()["id"]

    response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"contact_id": contact_id, "first_name": "New"},
        headers=auth_headers(other_rep),
    )

    assert response.status_code == 403


async def test_upsert_account_contact_returns_409_promoting_second_primary(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-update-acc-contact-409@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Promote Conflict Co")
    headers = auth_headers(owner)
    await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"first_name": "Existing", "is_primary": True},
        headers=headers,
    )
    second = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts", json={"first_name": "Second"}, headers=headers
    )
    second_id = second.json()["id"]

    response = await client.post(
        f"{ACCOUNTS_URL}/{account.id}/contacts",
        json={"contact_id": second_id, "is_primary": True},
        headers=headers,
    )

    assert response.status_code == 409


async def test_upsert_account_contact_creates_link_for_existing_contact_new_account(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="rep-relink-acc-contact@example.com", role=UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="Origin Co")
    account_b = await make_account(owner_id=owner.id, company="Destination Co")
    headers = auth_headers(owner)
    create_response = await client.post(
        f"{ACCOUNTS_URL}/{account_a.id}/contacts", json={"first_name": "Shared"}, headers=headers
    )
    contact_id = create_response.json()["id"]

    response = await client.post(
        f"{ACCOUNTS_URL}/{account_b.id}/contacts", json={"contact_id": contact_id}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["id"] == contact_id

    list_response = await client.get(f"{ACCOUNTS_URL}/{account_b.id}/contacts", headers=headers)
    assert [c["id"] for c in list_response.json()["items"]] == [contact_id]


# --- GET /accounts/{account_id}/deals ----------------------------------------


async def test_list_deals_for_account_returns_200_with_scoped_deals(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-list-deals-acc@example.com", role=UserRole.SALES_REP)
    account_a = await make_account(owner_id=owner.id, company="Deals Co A")
    account_b = await make_account(owner_id=owner.id, company="Deals Co B")
    deal_a = await make_deal(account_id=account_a.id, owner_id=owner.id, deal_name="Scoped Deal")
    await make_deal(account_id=account_b.id, owner_id=owner.id, deal_name="Other Account Deal")
    headers = auth_headers(owner)

    response = await client.get(f"{ACCOUNTS_URL}/{account_a.id}/deals", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [deal["id"] for deal in body] == [deal_a.id]


async def test_list_deals_for_account_returns_404_for_nonexistent_account(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-list-deals-404-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{ACCOUNTS_URL}/999999/deals", headers=headers)

    assert response.status_code == 404


async def test_list_deals_for_account_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-owns-list-deals-acc@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-list-deals-acc@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Deals Forbidden Co")
    await make_deal(account_id=account.id, owner_id=owner.id)
    headers = auth_headers(other_rep)

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}/deals", headers=headers)

    assert response.status_code == 403
