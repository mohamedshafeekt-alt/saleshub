"""HTTP-level contract for /api/v1/contacts.

Standalone Contact CRUD -- role-gated only (401/403 via the router's
require_role dependency), no ownership scoping (Contact has no owner_id and
no single owning account -- see contact_service.py's module docstring).
Covers: 201 create as each allowed role, 422 missing required field, 401 no
auth, 403 for Delivery SME, 200 successful get/PATCH partial update, 204
successful DELETE, 404 for a nonexistent contact id.
"""

from httpx import AsyncClient

from tests.support.roles import UserRole

CONTACTS_URL = "/api/v1/contacts"


def _contact_payload(**overrides) -> dict:
    payload = {"first_name": "Jane"}
    payload.update(overrides)
    return payload


async def test_create_contact_as_sales_rep_returns_201(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-create-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        CONTACTS_URL, json=_contact_payload(first_name="Jane", last_name="Doe"), headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["first_name"] == "Jane"
    assert body["last_name"] == "Doe"
    assert "id" in body


async def test_create_contact_as_sales_manager_returns_201(
    client: AsyncClient, make_user, auth_headers
):
    manager = await make_user(email="manager-create-contact@example.com", role=UserRole.SALES_MANAGER)
    headers = auth_headers(manager)

    response = await client.post(CONTACTS_URL, json=_contact_payload(), headers=headers)

    assert response.status_code == 201


async def test_create_contact_as_admin_returns_201(client: AsyncClient, make_user, auth_headers):
    admin = await make_user(email="admin-create-contact@example.com", role=UserRole.ADMIN)
    headers = auth_headers(admin)

    response = await client.post(CONTACTS_URL, json=_contact_payload(), headers=headers)

    assert response.status_code == 201


async def test_create_contact_with_linkedin_and_alternate_phone_returns_201(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-create-contact-extra@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.post(
        CONTACTS_URL,
        json=_contact_payload(linkedin_url="linkedin.com/in/jane", alternate_phone="555-0002"),
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["linkedin_url"] == "linkedin.com/in/jane"
    assert body["alternate_phone"] == "555-0002"


async def test_create_contact_missing_first_name_returns_422(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-missing-name-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    payload = _contact_payload()
    del payload["first_name"]

    response = await client.post(CONTACTS_URL, json=payload, headers=headers)

    assert response.status_code == 422


async def test_create_contact_no_auth_header_returns_401(client: AsyncClient):
    response = await client.post(CONTACTS_URL, json=_contact_payload())

    assert response.status_code == 401


async def test_create_contact_as_delivery_sme_returns_403(
    client: AsyncClient, make_user, auth_headers
):
    sme = await make_user(email="sme-create-contact@example.com", role=UserRole.DELIVERY_SME)
    headers = auth_headers(sme)

    response = await client.post(CONTACTS_URL, json=_contact_payload(), headers=headers)

    assert response.status_code == 403


async def test_get_contact_returns_200(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-get-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    create_response = await client.post(
        CONTACTS_URL, json=_contact_payload(first_name="Getable"), headers=headers
    )
    contact_id = create_response.json()["id"]

    response = await client.get(f"{CONTACTS_URL}/{contact_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == contact_id


async def test_get_contact_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-get-404-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.get(f"{CONTACTS_URL}/999999", headers=headers)

    assert response.status_code == 404


async def test_update_contact_partial_patch_returns_200(
    client: AsyncClient, make_user, auth_headers
):
    rep = await make_user(email="rep-patch-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    create_response = await client.post(
        CONTACTS_URL, json=_contact_payload(first_name="Old", job_title="Old Title"), headers=headers
    )
    contact_id = create_response.json()["id"]

    response = await client.patch(f"{CONTACTS_URL}/{contact_id}", json={"first_name": "New"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "New"
    assert body["job_title"] == "Old Title"


async def test_update_contact_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-patch-404-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.patch(f"{CONTACTS_URL}/999999", json={"first_name": "New"}, headers=headers)

    assert response.status_code == 404


async def test_delete_contact_returns_204(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-delete-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)
    create_response = await client.post(CONTACTS_URL, json=_contact_payload(), headers=headers)
    contact_id = create_response.json()["id"]

    response = await client.delete(f"{CONTACTS_URL}/{contact_id}", headers=headers)

    assert response.status_code == 204

    follow_up = await client.get(f"{CONTACTS_URL}/{contact_id}", headers=headers)
    assert follow_up.status_code == 404


async def test_delete_contact_returns_404_for_nonexistent_id(client: AsyncClient, make_user, auth_headers):
    rep = await make_user(email="rep-delete-404-contact@example.com", role=UserRole.SALES_REP)
    headers = auth_headers(rep)

    response = await client.delete(f"{CONTACTS_URL}/999999", headers=headers)

    assert response.status_code == 404
