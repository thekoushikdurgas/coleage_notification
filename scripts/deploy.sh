#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh – AWS EC2 Application Deployment Script
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo "=== Starting FormsADDA Deployment ==="

# 1. Ensure .env exists and is populated
if [ ! -f .env ]; then
    echo "--> .env file not found. Creating from .env.example..."
    cp .env.example .env
    
    # Generate a strong random Flask SECRET_KEY
    RAND_SECRET=$(openssl rand -hex 32)
    sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$RAND_SECRET/" .env
    
    # Generate a strong random PostgreSQL password
    RAND_DB_PASS=$(openssl rand -hex 16)
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$RAND_DB_PASS/" .env

    echo "  Generated default production keys and passwords in .env."
    echo "  Please open .env and set GEMINI_API_KEY if needed."
fi

# 2. Build and run containers
echo "--> Starting database container..."
docker compose up db -d

echo "--> Running database seeder..."
docker compose run --rm seeder

echo "--> Launching Flask application server..."
docker compose up web -d

# 3. Configure Host Nginx
echo "--> Configuring Nginx reverse proxy..."
if [ -f nginx/formsadda.conf ]; then
    # Prompt for domain / public IP
    read -rp "Enter your Domain or Public IP (e.g. example.com or 54.210.1.2) [localhost]: " SERVER_NAME
    SERVER_NAME="${SERVER_NAME:-localhost}"

    # Prepare temp configuration with replaced server name
    TEMP_CONF=$(mktemp)
    sed "s/server_name localhost;/server_name $SERVER_NAME;/" nginx/formsadda.conf > "$TEMP_CONF"
    
    sudo cp "$TEMP_CONF" /etc/nginx/sites-available/formsadda.conf
    rm -f "$TEMP_CONF"

    # Remove default Nginx site config if present to avoid conflicts
    sudo rm -f /etc/nginx/sites-enabled/default

    # Enable formsadda config
    sudo ln -sf /etc/nginx/sites-available/formsadda.conf /etc/nginx/sites-enabled/formsadda.conf

    echo "--> Testing and reloading Nginx..."
    sudo nginx -t
    sudo systemctl reload nginx
    echo "  Nginx updated and reloaded."
else
    echo "  WARNING: nginx/formsadda.conf not found. Skipping Nginx config."
fi

# 4. Optional SSL Setup
if [ "${SERVER_NAME:-localhost}" != "localhost" ]; then
    read -rp "Would you like to configure SSL (HTTPS) via Let's Encrypt Certbot? (y/n): " CONFIGURE_SSL
    if [[ "$CONFIGURE_SSL" =~ ^[Yy]$ ]]; then
        read -rp "Enter contact email for Let's Encrypt: " CERT_EMAIL
        sudo certbot --nginx -d "$SERVER_NAME" --non-interactive --agree-tos -m "$CERT_EMAIL"
        echo "--> Reloading Nginx after SSL integration..."
        sudo systemctl reload nginx
    fi
fi

echo "=== FormsADDA Deployment Successfully Completed ==="
