#!/usr/bin/env bash
set -euo pipefail

: "${DEPLOY_DIR:=/opt/carecoordinator}"
: "${DEPLOY_USER:=$USER}"

sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
sudo usermod -aG docker "$DEPLOY_USER"
sudo install -d -m 0750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$DEPLOY_DIR/secrets"

echo "Docker and deployment directory are ready. Sign out and back in before using Docker without sudo."
