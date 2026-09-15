#!/bin/sh
# Manual fallback: upload site/ to the Cloudflare Pages project "occult" from this machine. Normally a push to
# main publishes it (the project's Git integration; no Actions). Wrangler runs via npx (nothing to install).
#
#   ./scripts/deploy.sh            # rebuilds site/ then deploys
#   ./scripts/deploy.sh --no-build # deploys site/ as it is
#
# First time only:  npx wrangler login   (browser OAuth; stored in ~/.wrangler) — or export
# CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID for a non-interactive run.
set -eu
cd "$(dirname "$0")/.."
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
[ "${1:-}" = "--no-build" ] || $PY scripts/build_pages.py
npx --yes wrangler@latest pages deploy site --project-name=occult --branch=main --commit-dirty=true
