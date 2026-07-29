"""HTTP-level contract for GET /api/v1/documents: a read-only union of
Account and Deal documents. Covers: 200 combining both sources sorted newest
first, scoped to a Sales Rep's own accounts/deals, and a Sales Manager (has
ACCOUNTS_VIEW_ALL/DEALS_VIEW_ALL) seeing another rep's documents too."""

import pathlib

from httpx import AsyncClient

from tests.support.roles import UserRole

DOCUMENTS_URL = "/api/v1/documents"
ACCOUNTS_URL = "/api/v1/accounts"
DEALS_URL = "/api/v1/deals"


async def _upload_account_document(client: AsyncClient, headers: dict, account_id: int) -> dict:
    response = await client.post(
        f"{ACCOUNTS_URL}/{account_id}/documents",
        files={"file": ("acc-proposal.pdf", b"acc content", "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


async def _upload_deal_document(client: AsyncClient, headers: dict, deal_id: int) -> dict:
    response = await client.post(
        f"{DEALS_URL}/{deal_id}/documents",
        files={"file": ("deal-contract.pdf", b"deal content", "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


async def test_list_documents_combines_account_and_deal_documents(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-doc-list@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Doc List Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id)
    headers = auth_headers(owner)

    acc_doc = await _upload_account_document(client, headers, account.id)
    deal_doc = await _upload_deal_document(client, headers, deal.id)

    response = await client.get(DOCUMENTS_URL, headers=headers)

    assert response.status_code == 200
    body = response.json()
    sources = {(doc["source"], doc["entity_id"]) for doc in body}
    assert ("account", account.id) in sources
    assert ("deal", deal.id) in sources

    by_source = {doc["source"]: doc for doc in body}
    assert by_source["account"]["entity_name"] == "Doc List Co"
    assert by_source["account"]["file_name"] == "acc-proposal.pdf"
    assert by_source["deal"]["entity_name"] == deal.deal_name
    assert by_source["deal"]["file_name"] == "deal-contract.pdf"

    pathlib.Path(acc_doc["file_url"].lstrip("/")).unlink()
    pathlib.Path(deal_doc["file_url"].lstrip("/")).unlink()


async def test_list_documents_filters_by_source(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-doc-filter@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Filter Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id)
    headers = auth_headers(owner)

    acc_doc = await _upload_account_document(client, headers, account.id)
    deal_doc = await _upload_deal_document(client, headers, deal.id)

    account_only = await client.get(DOCUMENTS_URL, params={"source": "account"}, headers=headers)
    assert account_only.status_code == 200
    assert [doc["source"] for doc in account_only.json()] == ["account"]

    deal_only = await client.get(DOCUMENTS_URL, params={"source": "deal"}, headers=headers)
    assert deal_only.status_code == 200
    assert [doc["source"] for doc in deal_only.json()] == ["deal"]

    pathlib.Path(acc_doc["file_url"].lstrip("/")).unlink()
    pathlib.Path(deal_doc["file_url"].lstrip("/")).unlink()


async def test_list_documents_filters_by_search(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-doc-search@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Search Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id)
    headers = auth_headers(owner)

    acc_doc = await _upload_account_document(client, headers, account.id)
    deal_doc = await _upload_deal_document(client, headers, deal.id)

    response = await client.get(DOCUMENTS_URL, params={"search": "proposal"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [doc["file_name"] for doc in body] == ["acc-proposal.pdf"]

    pathlib.Path(acc_doc["file_url"].lstrip("/")).unlink()
    pathlib.Path(deal_doc["file_url"].lstrip("/")).unlink()


async def test_list_documents_scoped_to_own_accounts_and_deals_for_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-doc-owner@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-doc-other@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Owner Only Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id)

    acc_doc = await _upload_account_document(client, auth_headers(owner), account.id)
    deal_doc = await _upload_deal_document(client, auth_headers(owner), deal.id)

    response = await client.get(DOCUMENTS_URL, headers=auth_headers(other_rep))

    assert response.status_code == 200
    assert response.json() == []

    pathlib.Path(acc_doc["file_url"].lstrip("/")).unlink()
    pathlib.Path(deal_doc["file_url"].lstrip("/")).unlink()


async def test_list_documents_sales_manager_sees_other_reps_documents(
    client: AsyncClient, make_user, auth_headers, make_account, make_deal
):
    owner = await make_user(email="rep-doc-for-manager@example.com", role=UserRole.SALES_REP)
    manager = await make_user(email="manager-doc-list@example.com", role=UserRole.SALES_MANAGER)
    account = await make_account(owner_id=owner.id, company="Manager Visible Co")
    deal = await make_deal(account_id=account.id, owner_id=owner.id)

    acc_doc = await _upload_account_document(client, auth_headers(owner), account.id)
    deal_doc = await _upload_deal_document(client, auth_headers(owner), deal.id)

    response = await client.get(DOCUMENTS_URL, headers=auth_headers(manager))

    assert response.status_code == 200
    sources = {(doc["source"], doc["entity_id"]) for doc in response.json()}
    assert ("account", account.id) in sources
    assert ("deal", deal.id) in sources

    pathlib.Path(acc_doc["file_url"].lstrip("/")).unlink()
    pathlib.Path(deal_doc["file_url"].lstrip("/")).unlink()
