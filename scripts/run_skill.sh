#!/bin/sh
# Run a vault skill headless. Usage: run_skill.sh <skill-name>. Token is read from file at runtime, never stored here.
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
case "$1" in
  plan-today|inbox-brief|morning-intel|vault-ingest|vault-lint|weekly-review) ;;
  *) echo "unknown skill: $1" >&2; exit 2 ;;
esac
CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude-review-token")" || exit 1
export CLAUDE_CODE_OAUTH_TOKEN
cd "${AOS_VAULT:-$HOME/Claude+Obsidian}" || exit 1
# Locked down: built-in tools only, no MCP connectors, nothing auto-approved (skills read untrusted email/web text).
exec claude -p "/$1" --model sonnet --strict-mcp-config --permission-mode default \
  --tools "Read,Write,Edit,Glob,Grep,Bash" --allowedTools "Read,Write,Edit,Glob,Grep,Bash(python3 $HOME/agentic-os/scripts/fetch_intel.py),Bash(python3 $HOME/agentic-os/scripts/notion_sync.py)" </dev/null
