#!/bin/bash
set -e

cd /opt/digest_bot

echo "=== Pulling latest code ==="
git pull origin master

echo "=== Building and restarting ==="
docker compose down --remove-orphans
docker compose up -d --build

echo "=== Cleaning old images ==="
docker image prune -f

echo "=== Deploy complete ==="
docker compose ps
