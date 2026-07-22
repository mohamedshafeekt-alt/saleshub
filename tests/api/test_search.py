"""HTTP-level contract for /api/v1/search.

Covers: matches by name across leads/accounts/deals/contacts, no-match,
blank query, 401 no auth.
"""

from httpx import AsyncClient

SEARCH_URL = "/api/v1/search"


async def test_search_matches_lead_by_name(client: AsyncClient, make_user, make_lead, auth_headers):
    user = await make_user(email="searcher1@example.com")
    lead = await make_lead(owner_id=user.id, first_name="Rahul", last_name="Nexus", email="rahul@nexera.com")

    response = await client.get(SEARCH_URL, params={"q": "nexus"}, headers=auth_headers(user))

    assert response.status_code == 200
    results = response.json()
    assert {"id": lead.id, "label": "Lead", "name": "Rahul Nexus"} in results


async def test_search_matches_account_by_company(client: AsyncClient, make_user, make_account, auth_headers):
    user = await make_user(email="searcher2@example.com")
    account = await make_account(owner_id=user.id, company="Nexbridge Tech")

    response = await client.get(SEARCH_URL, params={"q": "nexbridge"}, headers=auth_headers(user))

    assert response.status_code == 200
    results = response.json()
    assert {"id": account.id, "label": "Account", "name": "Nexbridge Tech"} in results


async def test_search_matches_deal_by_name(
    client: AsyncClient, make_user, make_account, make_deal, auth_headers
):
    user = await make_user(email="searcher3@example.com")
    account = await make_account(owner_id=user.id, company="Acme Corp")
    deal = await make_deal(account_id=account.id, owner_id=user.id, deal_name="Nexbridge Expansion")

    response = await client.get(SEARCH_URL, params={"q": "nexbridge"}, headers=auth_headers(user))

    assert response.status_code == 200
    results = response.json()
    assert {"id": deal.id, "label": "Deal", "name": "Nexbridge Expansion"} in results


async def test_search_matches_contact_by_name(
    client: AsyncClient, make_user, make_account, make_contact, auth_headers
):
    user = await make_user(email="searcher4@example.com")
    account = await make_account(owner_id=user.id, company="Acme Corp")
    contact = await make_contact(account_id=account.id, first_name="Nikhil", last_name="Menon")

    response = await client.get(SEARCH_URL, params={"q": "nikhil"}, headers=auth_headers(user))

    assert response.status_code == 200
    results = response.json()
    assert {"id": contact.id, "label": "Contact", "name": "Nikhil Menon"} in results


async def test_search_no_match_returns_empty_list(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="searcher5@example.com")

    response = await client.get(SEARCH_URL, params={"q": "zzz-no-such-thing"}, headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json() == []


async def test_search_blank_query_returns_empty_list(client: AsyncClient, make_user, auth_headers):
    user = await make_user(email="searcher6@example.com")

    response = await client.get(SEARCH_URL, params={"q": "  "}, headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json() == []


async def test_search_requires_auth(client: AsyncClient):
    response = await client.get(SEARCH_URL, params={"q": "nex"})

    assert response.status_code == 401
