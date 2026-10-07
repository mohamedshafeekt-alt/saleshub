"""Account Source Detail: the ordered chain of people (platform Users and/or
Contacts) through whom an account reached us, e.g. Ram -> TT Bhat -> Radhika.

GET/PUT /accounts/{id}/source-detail, plus GET /accounts/source-detail/people
(the picker's User + Contact list with email/phone).
"""

from httpx import AsyncClient

from tests.support.roles import UserRole

ACCOUNTS_URL = "/api/v1/accounts"


async def _setup(make_user, make_account, make_contact, tag):
    rep = await make_user(email=f"rep-sd-{tag}@example.com", role=UserRole.SALES_REP, first_name="Ram")
    account = await make_account(owner_id=rep.id, company=f"SD Co {tag}")
    tt = await make_contact(
        account_id=account.id, first_name="TT", last_name="Bhat", phone="+91 111", is_originator=True
    )
    return rep, account, tt


async def test_source_detail_empty_by_default(client: AsyncClient, make_user, make_account, make_contact, auth_headers):
    rep, account, _ = await _setup(make_user, make_account, make_contact, "empty")

    response = await client.get(f"{ACCOUNTS_URL}/{account.id}/source-detail", headers=auth_headers(rep))

    assert response.status_code == 200
    assert response.json() == []


async def test_put_source_detail_saves_ordered_chain_of_users_and_contacts(
    client: AsyncClient, make_user, make_account, make_contact, auth_headers
):
    rep, account, tt = await _setup(make_user, make_account, make_contact, "chain")
    headers = auth_headers(rep)
    members = [{"type": "user", "id": rep.id}, {"type": "contact", "id": tt.id}]

    put = await client.put(f"{ACCOUNTS_URL}/{account.id}/source-detail", json={"members": members}, headers=headers)

    assert put.status_code == 200
    got = (await client.get(f"{ACCOUNTS_URL}/{account.id}/source-detail", headers=headers)).json()
    assert [(m["type"], m["id"]) for m in got] == [("user", rep.id), ("contact", tt.id)]
    assert got[0]["name"] == "Ram"
    assert got[1]["name"] == "TT Bhat"
    assert got[1]["email"] == tt.email
    assert got[1]["phone"] == "+91 111"

    # Replace + reorder.
    await client.put(
        f"{ACCOUNTS_URL}/{account.id}/source-detail", json={"members": members[::-1]}, headers=headers
    )
    again = (await client.get(f"{ACCOUNTS_URL}/{account.id}/source-detail", headers=headers)).json()
    assert [m["type"] for m in again] == ["contact", "user"]


async def test_put_source_detail_empty_clears_chain(
    client: AsyncClient, make_user, make_account, make_contact, auth_headers
):
    rep, account, tt = await _setup(make_user, make_account, make_contact, "clear")
    headers = auth_headers(rep)
    url = f"{ACCOUNTS_URL}/{account.id}/source-detail"
    await client.put(url, json={"members": [{"type": "user", "id": rep.id}, {"type": "contact", "id": tt.id}]}, headers=headers)

    assert (await client.put(url, json={"members": []}, headers=headers)).status_code == 200
    assert (await client.get(url, headers=headers)).json() == []


async def test_put_source_detail_rejects_duplicates_single_member_and_unknown_people(
    client: AsyncClient, make_user, make_account, make_contact, auth_headers
):
    rep, account, tt = await _setup(make_user, make_account, make_contact, "bad")
    headers = auth_headers(rep)
    url = f"{ACCOUNTS_URL}/{account.id}/source-detail"
    user = {"type": "user", "id": rep.id}
    contact = {"type": "contact", "id": tt.id}

    for members in (
        [user, user],  # duplicate
        [contact, user, contact],  # duplicate, non-adjacent
        [user, {"type": "contact", "id": 999999}],  # unknown contact
        [user, {"type": "user", "id": 999999}],  # unknown user
        [user, {"type": "robot", "id": 1}],  # unknown type
    ):
        response = await client.put(url, json={"members": members}, headers=headers)
        assert response.status_code == 422, members


async def test_put_source_detail_allows_a_single_person(
    client: AsyncClient, make_user, make_account, make_contact, auth_headers
):
    rep, account, _ = await _setup(make_user, make_account, make_contact, "single")
    headers = auth_headers(rep)
    url = f"{ACCOUNTS_URL}/{account.id}/source-detail"

    put = await client.put(url, json={"members": [{"type": "user", "id": rep.id}]}, headers=headers)

    assert put.status_code == 200
    assert [m["name"] for m in (await client.get(url, headers=headers)).json()] == ["Ram"]


async def test_source_detail_404_and_403(client: AsyncClient, make_user, make_account, make_contact, auth_headers):
    rep, account, _ = await _setup(make_user, make_account, make_contact, "acl")
    other = await make_user(email="other-sd-acl@example.com", role=UserRole.SALES_REP)

    assert (await client.get(f"{ACCOUNTS_URL}/999999/source-detail", headers=auth_headers(rep))).status_code == 404
    assert (await client.get(f"{ACCOUNTS_URL}/{account.id}/source-detail", headers=auth_headers(other))).status_code == 403
    assert (
        await client.put(f"{ACCOUNTS_URL}/{account.id}/source-detail", json={"members": []}, headers=auth_headers(other))
    ).status_code == 403


async def test_source_detail_people_lists_users_and_contacts_with_email_phone_and_searches(
    client: AsyncClient, make_user, make_account, make_contact, auth_headers
):
    rep, _, tt = await _setup(make_user, make_account, make_contact, "people")

    everyone = (await client.get(f"{ACCOUNTS_URL}/source-detail/people", headers=auth_headers(rep))).json()
    assert any(p["type"] == "user" and p["id"] == rep.id for p in everyone)
    tt_row = next(p for p in everyone if p["type"] == "contact" and p["id"] == tt.id)
    assert tt_row["name"] == "TT Bhat"
    assert tt_row["email"] == tt.email
    assert tt_row["phone"] == "+91 111"

    plain = await make_contact(account_id=(await make_account(owner_id=rep.id)).id, first_name="Plainone")
    everyone = (await client.get(f"{ACCOUNTS_URL}/source-detail/people", headers=auth_headers(rep))).json()
    assert any(p["type"] == "contact" and p["id"] == plain.id for p in everyone)  # any contact, originator or not

    found = (await client.get(f"{ACCOUNTS_URL}/source-detail/people?search=bhat", headers=auth_headers(rep))).json()
    assert [(p["type"], p["id"]) for p in found] == [("contact", tt.id)]
