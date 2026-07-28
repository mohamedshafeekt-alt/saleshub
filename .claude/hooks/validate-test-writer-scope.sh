#!/bin/bash
# Used as a PreToolUse hook in test-writer's frontmatter.
# Makes "do not implement the feature" a hard rule instead of an
# instruction the subagent could ignore: blocks Edit/Write outside tests/.
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -n "$FILE_PATH" ] && [[ "$FILE_PATH" != *"/tests/"* ]] && [[ "$FILE_PATH" != tests/* ]]; then
  echo "Blocked: test-writer may only write files under tests/. Hand implementation work to backend-implementer instead." >&2
  exit 2
fi

exit 0