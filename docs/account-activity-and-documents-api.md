# Account Activity & Account Documents API

For the frontend team. Covers the two new tabs on the Account detail page:
**Activity** (log of notes/meetings/calls/comments/follow-ups) and
**Documents** (supporting files uploaded against an Account).

All endpoints are nested under an existing Account, require auth, and share
the same permission gate as the rest of `/accounts` (`accounts.access`, plus
`accounts.view_all` to reach accounts you don't own).

## Auth

Every request needs:

```
Authorization: Bearer <access_token>
```

Same token you already use for the other `/accounts` endpoints.

## Common errors

| Status | When |
|---|---|
| 401 | Missing/invalid token |
| 403 | You don't own this account and lack `accounts.view_all` (or, for activity edit/delete, the specific rule below) |
| 404 | Account / activity / document id doesn't exist |
| 400 | Document upload: unsupported file type |
| 422 | Request body fails validation (e.g. empty `note`, bad `type` enum value) |

Error body shape (standard FastAPI):
```json
{ "detail": "human-readable message" }
```

---

## Activity

### Create an activity
`POST /accounts/{account_id}/activities`

Body:
```json
{
  "type": "note",
  "note": "Called to confirm renewal timeline."
}
```
`type` is one of: `note`, `meeting`, `call`, `comment`, `follow_up`.

201 response:
```json
{
  "id": 12,
  "account_id": 4,
  "type": "note",
  "note": "Called to confirm renewal timeline.",
  "created_by": 7,
  "created_at": "2026-07-24T10:15:00Z",
  "updated_by": null,
  "updated_at": "2026-07-24T10:15:00Z"
}
```

### List activities
`GET /accounts/{account_id}/activities`

Query params (all optional):
- `types` — repeat for multiple, e.g. `?types=note&types=call`
- `date_from` — ISO date, inclusive
- `date_to` — ISO date, exclusive

Returns newest-first, and includes display names (for "Logged by / Edited by"):
```json
[
  {
    "id": 12,
    "account_id": 4,
    "type": "note",
    "note": "Called to confirm renewal timeline.",
    "created_by": 7,
    "created_at": "2026-07-24T10:15:00Z",
    "updated_by": null,
    "updated_at": "2026-07-24T10:15:00Z",
    "created_by_name": "Priya Nair",
    "updated_by_name": null
  }
]
```

### Update an activity
`PATCH /accounts/{account_id}/activities/{activity_id}`

Body (partial — send only fields you're changing):
```json
{ "note": "Updated note text" }
```
**Only the account's owner can edit** its activities — others get 403, even
with `accounts.view_all`. Returns the same shape as list (with names).

### Delete an activity
`DELETE /accounts/{account_id}/activities/{activity_id}` → 204, empty body.

**Delete is Admin-only** (the `accounts.delete_any_activity` permission) —
not even the account owner can delete an activity via this endpoint.
(Editing is owner-restricted; deleting is stricter, admin-only — same
convention already used for Deal and Lead activity.)

---

## Documents

There is **no separate download or view endpoint**. Uploaded files are served
from the app's public static file mount at `/media/...`. The list/upload
response includes `file_url` — use it directly:
- **View inline**: use `file_url` as an `<iframe>`/`<img>`/link `href` — the
  browser renders PDFs/images inline.
- **Download**: use the same `file_url` on an `<a href={file_url} download>`
  to force a save-as instead of inline view.

`file_url` is a relative path (e.g. `/media/account_documents/4_ab12....pdf`)
— prefix it with your API base URL.

### Upload a document
`POST /accounts/{account_id}/documents` — `multipart/form-data`, field name `file`.

Allowed content types: `application/pdf`, `application/msword` (.doc),
`application/vnd.openxmlformats-officedocument.wordprocessingml.document` (.docx),
`image/png`, `image/jpeg`. Anything else → 400.

201 response:
```json
{
  "id": 3,
  "account_id": 4,
  "file_name": "MSA_Draft.pdf",
  "file_url": "/media/account_documents/4_9f2c8a1e....pdf",
  "content_type": "application/pdf",
  "uploaded_by": 7,
  "created_at": "2026-07-24T10:20:00Z"
}
```

### List documents
`GET /accounts/{account_id}/documents` → array of the same shape as above, newest-first.

### Delete a document
`DELETE /accounts/{account_id}/documents/{document_id}` → 204, empty body.
Removes both the DB row and the file on disk. Anyone who can access the
account (owner, or `accounts.view_all`) can delete — same rule as deleting
the Account record itself.

---

## Quick reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/accounts/{account_id}/activities` | Log an activity |
| GET | `/accounts/{account_id}/activities` | List activities (filterable) |
| PATCH | `/accounts/{account_id}/activities/{activity_id}` | Edit (owner only) |
| DELETE | `/accounts/{account_id}/activities/{activity_id}` | Delete (admin only) |
| POST | `/accounts/{account_id}/documents` | Upload a document |
| GET | `/accounts/{account_id}/documents` | List documents |
| DELETE | `/accounts/{account_id}/documents/{document_id}` | Delete a document |

Full request/response schemas are also live in Swagger at `/docs` once the
server's running.
