#!/bin/bash
# ASP Alerts Dashboard - SSL Certificate Setup (Let's Encrypt)
#
# Usage:
#   ./setup_ssl.sh <domain> <email>
#
# Example:
#   ./setup_ssl.sh asp-alerts.example.com admin@example.com

set -e

DOMAIN="$1"
EMAIL="$2"

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo "Usage: $0 <domain> <email>"
    echo "Example: $0 asp-alerts.example.com admin@example.com"
    exit 1
fi

echo "=============================================="
echo "ASP Alerts - SSL Certificate Setup"
echo "=============================================="
echo "Domain: $DOMAIN"
echo "Email:  $EMAIL"
echo ""

# Install certbot if not present
if ! command -v certbot &> /dev/null; then
    echo "Installing certbot..."
    sudo apt update
    sudo apt install -y certbot python3-certbot-nginx
fi

# Create webroot directory for HTTP-01 challenge
sudo mkdir -p /var/www/certbot

# Option 1: HTTP-01 challenge (requires port 80 accessible)
echo ""
echo "Attempting HTTP-01 challenge..."
echo "Note: Port 80 must be accessible from the internet."
echo ""

sudo certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# If successful, update nginx and restart
if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo ""
    echo "SSL certificate obtained successfully!"
    echo ""

    # Reload nginx to use new certificate
    sudo nginx -t && sudo systemctl reload nginx

    echo "Certificate location: /etc/letsencrypt/live/$DOMAIN/"
    echo ""
    echo "Auto-renewal is enabled via systemd timer."
    echo "Test renewal with: sudo certbot renew --dry-run"
else
    echo ""
    echo "Certificate generation failed."
    echo ""
    echo "If port 80 is blocked, try DNS-01 challenge instead:"
    echo "  ./setup_ssl_dns.sh $DOMAIN $EMAIL"
fi
