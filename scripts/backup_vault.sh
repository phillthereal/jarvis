#!/bin/sh
# Nightly vault backup: local git commit if anything changed. Usage: backup_vault.sh [vault_dir]
V="${1:-$HOME/Claude+Obsidian}"
cd "$V" || { echo "no vault at $V"; exit 1; }
[ -d .git ] || { echo "$V is not a git repo"; exit 1; }
git add -A
if git diff --cached --name-only | grep -Eq '^\.obsidian/plugins/[^/]+/data\.json$'; then
  git reset -q
  echo "ABORT: plugin data.json staged"; exit 2
fi
if git diff --cached --quiet; then echo "no changes"; exit 0; fi
git commit -q -m "backup $(date +%Y-%m-%d)" && echo "committed backup $(date +%Y-%m-%d)"
