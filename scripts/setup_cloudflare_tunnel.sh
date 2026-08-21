#!/usr/bin/env bash
# Setup a Cloudflare tunnel to expose the Neighborhood Rhythm dashboard at
# rhythm.srdkn.com (hidden URL, no port forwarding, no exposed IP).
# Run this on the Pi: bash scripts/setup_cloudflare_tunnel.sh
set -e

echo "=== 1. Install cloudflared ==="
if ! command -v cloudflared &>/dev/null; then
  sudo apt update && sudo apt install -y cloudflared
fi

echo "=== 2. Authenticate (opens a browser to link srdkn.com) ==="
cloudflared tunnel login
# This blocks until you authenticate in the browser. Select srdkn.com.

echo "=== 3. Create the tunnel ==="
TUNNEL_ID=$(cloudflared tunnel create rhythm | grep -oP '(?<=Created tunnel )[a-f0-9-]+' || true)
if [ -z "$TUNNEL_ID" ]; then
  echo "tunnel creation failed — check cloudflared tunnel create rhythm output"
  exit 1
fi
echo "tunnel id: $TUNNEL_ID"

echo "=== 4. Create the DNS route (rhythm.srdkn.com -> tunnel) ==="
cloudflared tunnel route dns rhythm rhythm.srdkn.com

echo "=== 5. Write config ==="
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << YAML
tunnel: $TUNNEL_ID
credentials-file: $home/.cloudflared/$TUNNEL_ID.json
ingress:
  - hostname: rhythm.srdkn.com
    service: http://localhost:8000
  - service: http_status:404
YAML

echo "=== 6. Install as a service ==="
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

echo "=== 7. Add API auth (so the dashboard isn't public-readable) ==="
echo "Add to ~/neighborhood-rhythm/config_local.py:"
echo "  API_TOKEN = \"$(openssl rand -hex 24)\""
echo "Then restart the web service:"
echo "  sudo systemctl restart neighborhood-rhythm-web.service"
echo ""
echo "=== Done. The dashboard is at https://rhythm.srdkn.com ==="
echo "(Add the API token to the Authorization: Bearer header to access /api/*)"
