#!/usr/bin/env bash
# Deploy script for chatstream-moderate on Toolforge.
# Run from anywhere: bash ~/chatstream-moderate/deploy.sh

set -euo pipefail

echo "==> Pulling latest changes..."
cd ~/chatstream-moderate
git pull

echo "==> Syncing dependencies..."
~/www/python/venv/bin/pip install -e ~/chatstream-moderate

echo "==> Restarting web service..."
cd ~
toolforge webservice --backend=kubernetes python3.11 restart

echo "==> Done."
