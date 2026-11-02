#!/bin/sh
# Obsidian MCP for interactive Claude sessions. Key read from .env at runtime; writes limited to wiki/ and outputs/.
KEY=$(grep '^OBSIDIAN_API_KEY=' "$HOME/agentic-os/.env" | cut -d= -f2-)
[ -n "$KEY" ] || { echo "OBSIDIAN_API_KEY missing in ~/agentic-os/.env" >&2; exit 1; }
export OBSIDIAN_API_KEY="$KEY" OBSIDIAN_BASE_URL="https://127.0.0.1:27124" OBSIDIAN_VERIFY_SSL=false \
  OBSIDIAN_WRITE_PATHS="wiki/,outputs/" OBSIDIAN_ENABLE_COMMANDS=false OBSIDIAN_DELETE_ELICITATION=true
exec obsidian-mcp-server
