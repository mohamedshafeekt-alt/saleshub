"""HTTP-level contract for /api/v1/contacts.

Covers: 201 create as each allowed role (owning Sales Rep, Manager, Admin),
422 missing required field, 401 no auth, 403 for Delivery SME on create, 404
for creating a contact under a nonexistent account_id, 403 for a Sales Rep
creating a contact under an account they don't own, 200 successful
get/PATCH partial update, 204 successful DELETE, 404 for a nonexistent
contact id, 403 for a non-owning Sales Rep on get/patch/delete of an
existing contact (access is gated via the contact's parent account).
"""

from httpx import AsyncClient

from app.models.user import UserRole

CONTACTS_URL = "/api/v1/contacts"
ACCOUNTS_URL = "/api/v1/accounts"


def _contact_payload(**overrides) -> dict:
    payload = {
        "first_name": "Jane",
        "account_id": overrides.pop("account_id"),
    }
    payload.update(overrides)
    return payload


async def test_create_contact_as_owning_sales_rep_returns_201(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-create-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Rep Contact Co")
    headers = auth_headers(rep)

    response = await client.post(
        CONTACTS_URL,
        json=_contact_payload(account_id=account.id, first_name="Jane", last_name="Doe"),
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["first_name"] == "Jane"
    assert body["last_name"] == "Doe"
    assert body["account_id"] == account.id
    assert "id" in body


async def test_create_contact_as_sales_manager_returns_201(
    client: AsyncClient, make_user, auth_headers, make_account
):
    manager = await make_user(email="manager-create-contact@example.com", role=UserRole.SALES_MANAGER)
    rep = await make_user(email="rep-owned-by-manager-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Manager Contact Co")
    headers = auth_headers(manager)

    response = await client.post(
        CONTACTS_URL, json=_contact_payload(account_id=account.id), headers=headers
    )

    assert response.status_code == 201


async def test_create_contact_as_admin_returns_201(
    client: AsyncClient, make_user, auth_headers, make_account
):
    admin = await make_user(email="admin-create-contact@example.com", role=UserRole.ADMIN)
    rep = await make_user(email="rep-owned-by-admin-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Admin Contact Co")
    headers = auth_headers(admin)

    response = await client.post(
        CONTACTS_URL, json=_contact_payload(account_id=account.id), headers=headers
    )

    assert response.status_code == 201


async def test_create_contact_missing_first_name_returns_422(
    client: AsyncClient, make_user, auth_headers, make_account
):
    rep = await make_user(email="rep-missing-name-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="Missing Name Co")
    headers = auth_headers(rep)
    payload = _contact_payload(account_id=account.id)
    del payload["first_name"]

    response = await client.post(CONTACTS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_contact_no_auth_header_returns_401(
    client: AsyncClient, make_user, make_account
):
    rep = await make_user(email="rep-no-auth-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=rep.id, company="No Auth Co")

    response = await client.post(CONTACTS_URL, json=_contact_payload(account_id=account.id))

    assert response.status_code == 401


async def test_create_contact_as_delivery_sme_returns_403(
    client: AsyncClient, make_user, auth_headers, make_account
):
    sme = await make_user(email="sme-create-contact@example.com", role=UserRole.DELIVERY_SME)
    other_rep = await make_user(email="rep-for-sme-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=other_rep.id, company="SME Contact Co")
    headers = auth_headers(sme)

    response = await client.post(
        CONTACTS_URL, json=_contact_payload(account_id=account.id), headers=headers
    )

    assert response.status_code == 403


async def test_create_contact_returns_404_for_nonexistent_account(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-404-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        CONTACTS_URL, json=_contact_payload(account_id=999_999), headers=headers
    )

    assert response.status_code == 404


async def test_create_contact_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account
):
    owner = await make_user(email="owner-create-forbidden-contact@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(
        email="other-rep-create-forbidden-contact@example.com", role=UserRole.SALES_REP
    )
    account = await make_account(owner_id=owner.id, company="Create Forbidden Co")
    headers = auth_headers(other_rep)

    response = await client.post(
        CONTACTS_URL, json=_contact_payload(account_id=account.id), headers=headers
    )

    assert response.status_code == 403


async def test_get_contact_returns_200_for_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-get-ok-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Get Ok Contact Co")
    contact = await make_contact(account_id=account.id, first_name="Getable")
    headers = auth_headers(owner)

    response = await client.get(f"{CONTACTS_URL}/{contact.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == contact.id


async def test_get_contact_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-get-404-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{CONTACTS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_get_contact_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-owns-get-contact@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-get-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Get Forbidden Contact Co")
    contact = await make_contact(account_id=account.id)
    headers = auth_headers(other_rep)

    response = await client.get(f"{CONTACTS_URL}/{contact.id}", headers=headers)

    assert response.status_code == 403


async def test_update_contact_partial_patch_returns_200(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-patch-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Contact Co")
    contact = await make_contact(account_id=account.id, first_name="Old", job_title="Old Title")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{CONTACTS_URL}/{contact.id}", json={"first_name": "New"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "New"
    assert body["job_title"] == "Old Title"


async def test_update_contact_ignores_account_id_in_payload(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    # A contact must not be reassignable to a different account via PATCH --
    # doing so would bypass account-ownership checks on the destination
    # account entirely. ContactUpdate has no account_id field, so a client
    # sending one is silently ignored rather than acted on.
    owner = await make_user(email="rep-patch-reparent@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Original Co")
    other_account = await make_account(owner_id=owner.id, company="Other Co")
    contact = await make_contact(account_id=account.id, first_name="Stays Put")
    headers = auth_headers(owner)

    response = await client.patch(
        f"{CONTACTS_URL}/{contact.id}",
        json={"first_name": "Still Stays Put", "account_id": other_account.id},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Still Stays Put"
    assert body["account_id"] == account.id


async def test_update_contact_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-patch-404-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.patch(f"{CONTACTS_URL}/999999", json={"first_name": "New"}, headers=headers)

    assert response.status_code == 404


async def test_update_contact_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-owns-patch-contact@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-patch-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Patch Forbidden Contact Co")
    contact = await make_contact(account_id=account.id)
    headers = auth_headers(other_rep)

    response = await client.patch(
        f"{CONTACTS_URL}/{contact.id}", json={"first_name": "New"}, headers=headers
    )

    assert response.status_code == 403


async def test_delete_contact_returns_204(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-delete-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Delete Contact Co")
    contact = await make_contact(account_id=account.id)
    headers = auth_headers(owner)

    response = await client.delete(f"{CONTACTS_URL}/{contact.id}", headers=headers)

    assert response.status_code == 204

    follow_up = await client.get(f"{CONTACTS_URL}/{contact.id}", headers=headers)
    assert follow_up.status_code == 404


async def test_delete_contact_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-delete-404-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{CONTACTS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_delete_contact_returns_403_for_non_owning_sales_rep(
    client: AsyncClient, make_user, auth_headers, make_account, make_contact
):
    owner = await make_user(email="rep-owns-delete-contact@example.com", role=UserRole.SALES_REP)
    other_rep = await make_user(email="rep-not-owner-delete-contact@example.com", role=UserRole.SALES_REP)
    account = await make_account(owner_id=owner.id, company="Delete Forbidden Contact Co")
    contact = await make_contact(account_id=account.id)
    headers = auth_headers(other_rep)

    response = await client.delete(f"{CONTACTS_URL}/{contact.id}", headers=headers)

    assert response.status_code == 403
