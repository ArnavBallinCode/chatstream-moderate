#!/usr/bin/env bash
# Deploy script for chatstream-moderate on Toolforge.
# Run from anywhere: bash ~/chatstream-moderate/deploy.sh

set -euo pipefail

echo "==> Pulling latest changes..."
cd ~/chatstream-moderate
git pull

echo "==> Applying database migrations..."
~/www/python/venv/bin/python -m flask db upgrade

echo "==> Restarting web service..."
cd ~
toolforge webservice --backend=kubernetes python3.13 restart

echo "==> Done."
