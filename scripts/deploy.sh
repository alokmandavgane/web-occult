#!/bin/sh
# Push site/ to the Cloudflare Pages project "occult" (Direct Upload) from this machine.
# No git integration, no Actions: build locally, upload with Wrangler via npx (nothing to install).
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
