#!/usr/bin/env bash
# Runs once, when Claude is about to end its turn — not after every edit.
# This is the "is this task actually done" gate: full typecheck + full
# test suite. Exit 2 blocks Claude from stopping and feeds the failure
# back so it keeps working instead of handing back red code.
# Claude Code overrides a Stop hook after 8 consecutive blocks, so this
# can't trap a session in an infinite loop.
set -uo pipefail

echo "==> mypy (typecheck)"
uv run mypy app || exit 2

echo "==> pytest (unit + integration tests)"
uv run pytest -q || exit 2

echo "==> all checks passed"