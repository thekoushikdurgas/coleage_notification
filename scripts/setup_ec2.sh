#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_ec2.sh – Fresh EC2 Environment Setup Script (Ubuntu 22.04 LTS)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "=== Starting EC2 System Setup ==="

# 1. Update system packages
echo "--> Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y curl git gnupg ca-certificates lsb-release nginx certbot python3-certbot-nginx

# 2. Install Docker and Docker Compose plugin
echo "--> Installing Docker..."
if ! command -v docker &> /dev/null; then
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
    echo "  Docker already installed."
fi

# 3. Configure Docker permissions for the current user
echo "--> Configuring user groups for Docker..."
if ! groups "$USER" | grep &>/dev/null '\bdocker\b'; then
    sudo usermod -aG docker "$USER"
    echo "  Added $USER to docker group. Note: You will need to log out and log back in (or run 'newgrp docker') for group changes to take effect."
fi

# 4. Enable Docker service
sudo systemctl enable docker
sudo systemctl start docker

echo "=== EC2 Environment Setup Complete ==="
echo "Please re-authenticate your SSH session or run 'newgrp docker' before running deployment scripts."
