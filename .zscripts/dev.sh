#!/bin/bash
# ============================================================
# Custom Development Script
# ============================================================
#
# This script is executed by start.sh when present, replacing
# the default bun install + bun run dev flow.
#
# It runs as user 'z' via: sudo -u z bash /home/z/my-project/.zscripts/dev.sh
#
# Use this for custom project initialization, database setup,
# or alternative dev server startup procedures.
#
# The start.sh script waits for the ZAI Agent Engine to be ready
# before starting Caddy, so this script should start any
# development servers needed for the project.
# ============================================================

set -e

echo "[custom-dev] Starting custom development flow..."

# Example: Install dependencies
if [ -f "/home/z/my-project/package.json" ]; then
  echo "[custom-dev] Running bun install..."
  cd /home/z/my-project
  bun install
fi

# Example: Database migration
# bun run db:push

# Example: Start development server
# bun run dev &

echo "[custom-dev] Custom development flow complete."
