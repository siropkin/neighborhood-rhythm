#!/usr/bin/env bash
# Setup a Cloudflare tunnel to expose the Neighborhood Rhythm dashboard at
# rhythm.srdkn.com (hidden URL, no port forwarding, no exposed IP).
#
# Uses a Cloudflare API token (not `cloudflared tunnel login`, which requires
# a browser and doesn't save the cert reliably on a headless Pi).
#
# Prereqs:
#   1. cloudflared installed:  sudo apt install -y cloudflared
#   2. A Cloudflare API token at ~/.cloudflared_token with:
#        Account → Cloudflare Tunnel → Edit
#        Zone → DNS → Edit  (for srdkn.com)
#   3. srdkn.com added as a zone in Cloudflare (nameservers switched at GoDaddy
#      to Cloudflare's — the zone must be active, not pending).
#
# Run on the Pi: bash scripts/setup_cloudflare_tunnel.sh
set -e

TOKEN=$(cat ~/.cloudflared_token)
ACCT=$(curl -s "https://api.cloudflare.com/client/v4/zones?name=srdkn.com" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['result'][0]['account']['id'])")
ZID=$(curl -s "https://api.cloudflare.com/client/v4/zones?name=srdkn.com" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['result'][0]['id'])")

echo "=== 1. Create the tunnel ==="
TUNNEL_SECRET=$(openssl rand -hex 32)
TUNNEL_ID=$(curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCT/cfd_tunnel" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"name\":\"rhythm\",\"tunnel_secret\":\"$TUNNEL_SECRET\",\"config_src\":\"cloudflare\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['id'])")
echo "tunnel id: $TUNNEL_ID"

TUNNEL_TOKEN=$(curl -s -X GET "https://api.cloudflare.com/client/v4/accounts/$ACCT/cfd_tunnel/$TUNNEL_ID" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['result']['token'])")

echo "=== 2. Create the DNS route (rhythm.srdkn.com -> tunnel) ==="
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"type\":\"CNAME\",\"name\":\"rhythm\",\"content\":\"${TUNNEL_ID}.cfargotunnel.com\",\"proxied\":true}" | python3 -m json.tool | head -5

echo "=== 3. Configure ingress (rhythm.srdkn.com -> http://localhost:8000) ==="
curl -s -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCT/cfd_tunnel/${TUNNEL_ID}/configurations" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"config\":{\"ingress\":[{\"hostname\":\"rhythm.srdkn.com\",\"service\":\"http://localhost:8000\"},{\"service\":\"http_status:404\"}]}}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('ingress configured' if d['success'] else d['errors'])"

echo "=== 4. Save tunnel token ==="
mkdir -p ~/.cloudflared
echo "$TUNNEL_TOKEN" > ~/.cloudflared/tunnel_token
chmod 600 ~/.cloudflared/tunnel_token

echo "=== 5. Install as a systemd service ==="
sudo tee /etc/systemd/system/cloudflared.service > /dev/null << UNIT
[Unit]
Description=Cloudflare Tunnel (Neighborhood Rhythm)
After=network-online.target
Wants=network-online.target

[Service]
TimeoutStartSec=0
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run --token ${TUNNEL_TOKEN}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

echo "=== 6. Add API auth (so the dashboard isn't public-readable) ==="
API_TOKEN=$(openssl rand -hex 24)
sudo sed -i '/^Environment=RHYTHM_API_TOKEN/d' /etc/systemd/system/neighborhood-rhythm-web.service
sudo sed -i "/^Environment=RHYTHM_SENSOR_ID/a Environment=RHYTHM_API_TOKEN=$API_TOKEN" /etc/systemd/system/neighborhood-rhythm-web.service
sudo systemctl daemon-reload
sudo systemctl restart neighborhood-rhythm-web.service

echo ""
echo "=== Done. The dashboard is at https://rhythm.srdkn.com/?t=$API_TOKEN ==="
echo "(API token for integrations: $API_TOKEN — use as Authorization: Bearer or ?token=)"
