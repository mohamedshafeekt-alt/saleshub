"""HTTP-level contract for /api/v1/accounts.

Covers: 201 create as each allowed role, 422 missing required field, 401 no
auth, 403 for Delivery SME (list + create) and for a non-owning Sales Rep
(get/update/delete), 200 list scoped by role and by each filter
(owner_id/tier/search), 404 for a missing account, 200 partial PATCH, 204
DELETE. Plus GET /accounts/{account_id}/contacts: 200 scoped to that
account's contacts, 404 for a nonexistent account, 403 for a non-owning
Sales Rep. Plus GET /accounts/{account_id}/deals: 200 scoped to that
account's deals (gated on the ACCOUNT's ownership, not deal ownership), 404
for a nonexistent account, 403 for a non-owning Sales Rep on the account.
"""

from httpx import AsyncClient

from tests.support.roles import UserRole

ACCOUNTS_URL = "/api/v1/accounts"


def _account_payload(**overrides) -> dict:
    payload = {
        "company": "Acme Corp",
        "tier": "gold",
        "owner_id": overrides.pop("owner_id"),
    }
    payload.update(overrides)
    return payload


async def test_create_account_as_sales_rep_returns_201(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-create-acc@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        ACCOUNTS_URL, json=_account_payload(owner_id=rep.id, company="Rep Co"), headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["company"] == "Rep Co"
    assert body["tier"] == "gold"
    assert body["owner_id"] == rep.id
    assert body["source_lead_id"] is None
    assert "id" in body


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
