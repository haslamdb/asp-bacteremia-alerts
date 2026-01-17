#!/bin/bash
# ASP Alerts Dashboard - Production Setup Script
#
# Usage:
#   ./setup_production.sh [domain]
#
# Example:
#   ./setup_production.sh asp-alerts.example.com

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DOMAIN="${1:-asp-alerts.local}"

echo "=============================================="
echo "ASP Alerts Dashboard - Production Setup"
echo "=============================================="
echo "Domain: $DOMAIN"
echo "Project: $PROJECT_DIR"
echo ""

# Check if running as appropriate user
if [ "$EUID" -eq 0 ]; then
    echo "Warning: Running as root. Service will run as user 'david'."
fi

# Create logs directory
echo "Creating logs directory..."
mkdir -p "$PROJECT_DIR/logs"

# Create .env if it doesn't exist
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "Creating .env from template..."
    cp "$PROJECT_DIR/.env.template" "$PROJECT_DIR/.env"
    echo "  Please edit $PROJECT_DIR/.env with your settings"
fi

# Install systemd service
echo "Installing systemd service..."
sudo cp "$SCRIPT_DIR/asp-alerts.service" /etc/systemd/system/
sudo systemctl daemon-reload

# Determine nginx config to use
if [ "$DOMAIN" = "asp-alerts.local" ] || [[ "$DOMAIN" =~ ^192\. ]] || [[ "$DOMAIN" =~ ^10\. ]]; then
    NGINX_CONF="nginx-asp-alerts-local.conf"
    echo "Using local nginx configuration..."
else
    NGINX_CONF="nginx-asp-alerts-external.conf"
    echo "Using external nginx configuration..."

    # Replace domain placeholder
    sed "s/YOUR_DOMAIN/$DOMAIN/g" "$SCRIPT_DIR/$NGINX_CONF" > "/tmp/asp-alerts-nginx.conf"
    NGINX_CONF="/tmp/asp-alerts-nginx.conf"
fi

# Install nginx configuration
echo "Installing nginx configuration..."
if [ -f "/tmp/asp-alerts-nginx.conf" ]; then
    sudo cp "/tmp/asp-alerts-nginx.conf" /etc/nginx/sites-available/asp-alerts
else
    sudo cp "$SCRIPT_DIR/$NGINX_CONF" /etc/nginx/sites-available/asp-alerts
fi

# Enable site
if [ ! -L /etc/nginx/sites-enabled/asp-alerts ]; then
    sudo ln -s /etc/nginx/sites-available/asp-alerts /etc/nginx/sites-enabled/
fi

# Test nginx configuration
echo "Testing nginx configuration..."
sudo nginx -t

# Start/restart services
echo "Starting services..."
sudo systemctl enable asp-alerts
sudo systemctl restart asp-alerts
sudo systemctl reload nginx

# Check status
echo ""
echo "=============================================="
echo "Setup complete!"
echo "=============================================="
echo ""
echo "Service status:"
sudo systemctl status asp-alerts --no-pager -l | head -15
echo ""
echo "Access URLs:"
if [ "$DOMAIN" = "asp-alerts.local" ]; then
    echo "  Local: http://asp-alerts.local/"
    echo "  IP:    http://$(hostname -I | awk '{print $1}')/"
else
    echo "  https://$DOMAIN/"
fi
echo ""
echo "Useful commands:"
echo "  sudo systemctl status asp-alerts   # Check service status"
echo "  sudo systemctl restart asp-alerts  # Restart service"
echo "  sudo journalctl -u asp-alerts -f   # View live logs"
echo "  tail -f $PROJECT_DIR/logs/asp-alerts.log"
