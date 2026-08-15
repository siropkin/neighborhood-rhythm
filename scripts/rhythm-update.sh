#!/usr/bin/env bash
# Self-update: checks GitHub for a newer release tag; if found, pulls + restarts.
# Runs on the Pi via the update-rhythm systemd timer (every 5 min).
set -euo pipefail

REPO="${RHYTHM_REPO:-siropkin/neighborhood-rhythm}"
STATE_DIR="${RHYTHM_STATE_DIR:-/var/lib/neighborhood-rhythm}"
STATE_FILE="$STATE_DIR/latest_tag"
APP_DIR="${RHYTHM_APP_DIR:-/home/siropkin/neighborhood-rhythm}"
VENV="${RHYTHM_VENV:-/home/siropkin/lightcontrol_venv/bin/python}"

mkdir -p "$STATE_DIR"
touch "$STATE_FILE"
CURRENT="$(cat "$STATE_FILE" 2>/dev/null || echo "")"

LATEST="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
  | grep -m1 '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/' || echo "")"

if [ -z "$LATEST" ]; then
  echo "could not fetch latest release; skipping"; exit 0
fi
if [ "$LATEST" = "$CURRENT" ]; then
  echo "up to date ($LATEST)"; exit 0
fi

echo "new release: $LATEST (was ${CURRENT:-none}) — updating..."

cd "$APP_DIR"
# repo owned by siropkin but this runs as root — safe.directory + chown back.
git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
git fetch --tags origin
git reset --hard "$LATEST"
git checkout "$LATEST"
chown -R siropkin:siropkin "$APP_DIR"

sudo systemctl restart neighborhood-rhythm-web.service
sudo systemctl restart neighborhood-rhythm-collector.timer

( cd "$APP_DIR" && "$VENV" reclassify.py ) || echo "reclassify skipped"

echo "$LATEST" > "$STATE_FILE"
echo "updated to $LATEST"
