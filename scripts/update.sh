#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# update.sh – Git Pull and Docker Container Update Script for EC2
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "=== Starting Git Update and Docker Rebuild ==="

# 1. Pull latest code from Git
echo "--> Pulling latest changes from git repository..."
git pull

# 2. Rebuild and restart docker containers
echo "--> Rebuilding web service and recreating containers..."
# Rebuild the web image to pick up code/dependency changes, then launch in background
docker compose up --build -d web

# 3. Clean up unused/dangling Docker images to save disk space on EC2
echo "--> Cleaning up unused Docker resources..."
docker image prune -f

echo "=== Update and Rebuild Successfully Completed ==="
