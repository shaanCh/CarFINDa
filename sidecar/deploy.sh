#!/usr/bin/env bash
set -euo pipefail

# Deploy Sift Browser Sidecar to Fly.io
#
# Prerequisites:
#   1. flyctl installed and authenticated
#   2. Secrets set:
#      TOKEN=$(openssl rand -hex 32)
#      fly secrets set -a sift-browser SIDECAR_TOKEN=$TOKEN
#      fly secrets set -a sift-backend-app BROWSER_SIDECAR_TOKEN=$TOKEN

APP="sift-browser"
REGION="dfw"
VOLUME="sift_browser_data"

cd "$(dirname "$0")"

echo "==> Creating app $APP (if needed)..."
fly apps create "$APP" --org personal 2>/dev/null || echo "    App already exists."

echo "==> Checking for volume $VOLUME..."
if ! fly volumes list -a "$APP" 2>/dev/null | grep -q "$VOLUME"; then
  echo "    Creating 1GB volume in $REGION..."
  fly volumes create "$VOLUME" -a "$APP" -r "$REGION" -s 1 -y
else
  echo "    Volume already exists."
fi

echo "==> Deploying $APP..."
fly deploy -a "$APP" --config fly.toml --remote-only

echo ""
echo "==> Deploy complete!"
echo "    Verify sidecar:"
echo "      fly status -a $APP"
echo "      fly ssh console -a $APP -C 'curl -s http://localhost:3000/'"
echo ""
echo "    Verify backend can reach sidecar:"
echo "      fly ssh console -a sift-backend-app -C 'curl -s http://sift-browser.internal:3000/'"
