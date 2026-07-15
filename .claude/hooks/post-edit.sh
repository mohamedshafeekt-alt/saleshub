#!/usr/bin/env bash
# Self-validation loop — runs after every Edit/Write/MultiEdit.
# Any failure here should be treated as a blocker: fix before moving on.
set -uo pipefail

echo "==> ruff (lint + format check)"
uv run ruff check . || exit 1

echo "==> mypy (typecheck)"
uv run mypy app || exit 1

echo "==> pytest (unit + integration tests)"
uv run pytest -q || exit 1

echo "==> all checks passed"
