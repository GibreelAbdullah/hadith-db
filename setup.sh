#!/usr/bin/env bash
# One-time local setup for the hadith-db repo.
#
# Configures the "ours" merge driver referenced by .gitattributes so that
# conflicts on generated metadata.json files auto-resolve to the current
# branch's version. The correct content is regenerated from the .txt sources
# by convert.py (and by CI on push to master), so the conflicting side is
# noise and safe to discard.
#
# Git config lives in .git/config and is NOT committed, so every fresh clone
# must run this once. Safe to re-run (idempotent).
set -euo pipefail

# Move to the repo root (directory of this script).
cd "$(dirname "$0")"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "error: not inside a git repository" >&2
  exit 1
fi

git config merge.ours.driver true
echo "Configured merge.ours.driver = true"
echo "metadata.json merge conflicts will now auto-resolve to the current branch."
