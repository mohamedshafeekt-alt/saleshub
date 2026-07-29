#!/usr/bin/env bash
# Fast self-validation — runs after every Edit/Write.
# Lint only: kept fast so it doesn't slow down every single edit.
# Full typecheck + test suite run once per turn, via stop-check.sh instead.
# Exit 2 is required (not 1) so Claude Code treats this as a blocking
# error and feeds the full output back to Claude — see PostToolUse
# exit-code behavior in the Claude Code hooks reference.
set -uo pipefail

echo "==> ruff (lint + format check)"
uv run ruff check . || exit 2

echo "==> lint passed"