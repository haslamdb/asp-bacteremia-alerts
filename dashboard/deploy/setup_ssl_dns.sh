#!/bin/bash
# ASP Alerts Dashboard - SSL Certificate Setup (DNS-01 Challenge)
#
# Use this when port 80 is not accessible from the internet.
# Requires manually adding a TXT record to your DNS.
#
# Usage:
#   ./setup_ssl_dns.sh <domain> <email>
#
# Example:
#   ./setup_ssl_dns.sh asp-alerts.example.com admin@example.com

set -e

DOMAIN="$1"
EMAIL="${2:-dbhaslam@gmail.com}"

if [ -z "$DOMAIN" ]; then
    echo "Usage: $0 <domain> [email]"
    echo "Example: $0 asp-alerts.example.com admin@example.com"
    exit 1
fi

echo "=============================================="
echo "ASP Alerts - SSL Certificate Setup (DNS-01)"
echo "=============================================="
echo "Domain: $DOMAIN"
echo "Email:  $EMAIL"
echo ""

# Install certbot if not present
if ! command -v certbot &> /dev/null; then
    echo "Installing certbot..."
    sudo apt update
    sudo apt install -y certbot
fi

echo "This will use DNS-01 challenge (manual TXT record)."
echo ""
echo "You will be prompted to add a TXT record to your DNS."
echo "The record will look like:"
echo "  _acme-challenge.$DOMAIN  TXT  <random-string>"
echo ""
echo "Press Enter to continue..."
read

sudo certbot certonly \
    --manual \
    --preferred-challenges dns \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN"

# If successful
if [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    echo ""
    echo "=============================================="
    echo "SSL certificate obtained successfully!"
    echo "=============================================="
    echo ""
    echo "Certificate: /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    echo "Private key: /etc/letsencrypt/live/$DOMAIN/privkey.pem"
    echo ""

    # Reload nginx
    sudo nginx -t && sudo systemctl reload nginx

    echo "IMPORTANT: DNS-01 certificates require manual renewal!"
    echo "Set a reminder to renew before expiration (90 days)."
    echo ""
    echo "To renew: sudo certbot renew --manual"
else
    echo ""
    echo "Certificate generation failed. Check the error messages above."
fi
