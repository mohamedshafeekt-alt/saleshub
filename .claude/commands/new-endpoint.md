---
description: Scaffold a new resource end-to-end — model, schema, service, route, tests — following project conventions.
---

Build a complete new resource for: $ARGUMENTS

Follow this exact order (TDD, per CLAUDE.md):

1. Confirm the resource's fields against `docs/phase1-kickoff-email.md`
   first, `docs/scope-and-user-stories.md` second if a field isn't
   mentioned in the email. Flag any conflict instead of guessing.
2. Write the SQLAlchemy model in `app/models/`.
3. Write the Pydantic schemas (Create/Update/Read) in `app/schemas/`.
4. Write failing tests in `tests/api/` covering happy path, validation,
   and RBAC.
5. Implement the route in `app/api/v1/` and any service logic in
   `app/services/`.
6. Run `.claude/hooks/post-edit.sh` and fix until green.
7. Add a line to `README.md` under "Implemented".
8. Give a one-paragraph product-owner-perspective summary of what this
   resource now lets users do.
