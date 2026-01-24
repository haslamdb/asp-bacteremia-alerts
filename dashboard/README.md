# AEGIS Dashboard

Web-based dashboard for the AEGIS (Automated Evaluation and Guidance for Infection Surveillance) system. Provides a unified interface for antimicrobial stewardship alerts, HAI detection, and NHSN reporting.

> **Disclaimer:** All patient data displayed is **simulated**. No actual patient data is available through this dashboard.

## Live Demo

**URL:** [https://aegis-asp.com](https://aegis-asp.com)

## Dashboard Structure

The AEGIS dashboard is organized into four main sections accessible from the landing page:

| Section | URL | Description |
|---------|-----|-------------|
| **ASP Alerts** | `/asp-alerts/` | Antimicrobial stewardship alerts (bacteremia, usage monitoring) |
| **HAI Detection** | `/hai-detection/` | HAI candidate screening (CLABSI, CAUTI, SSI, VAE, CDI) and IP review workflow |
| **NHSN Reporting** | `/nhsn-reporting/` | AU, AR, and HAI data aggregation with NHSN submission |
| **Dashboards** | `/dashboards/` | Analytics dashboards (coming soon) |

## Features

### ASP Alerts (`/asp-alerts/`)
- **Active Alerts** - View pending, sent, acknowledged, and snoozed alerts
- **History** - Browse resolved alerts with resolution details
- **Alert Detail** - Full patient and clinical information with action buttons
- **Reports** - Alert volume, resolution times, resolution breakdown

### HAI Detection (`/hai-detection/`)
- **Dashboard** - HAI candidates (CLABSI, CAUTI, SSI, VAE, CDI) awaiting IP review
- **History** - Resolved candidates (confirmed and rejected)
- **Reports** - HAI analytics and LLM override stats
- **Supported HAI Types**:
  - CLABSI - Central Line-Associated Bloodstream Infections
  - CAUTI - Catheter-Associated Urinary Tract Infections
  - SSI - Surgical Site Infections (Superficial, Deep, Organ/Space)
  - VAE - Ventilator-Associated Events (VAC, IVAC, Possible/Probable VAP)
  - CDI - Clostridioides difficile Infections (HO-CDI, CO-CDI, CO-HCFA)

### NHSN Reporting (`/nhsn-reporting/`)
- **Dashboard** - Overview with AU, AR, and HAI summaries
- **AU Detail** - Days of therapy by location and antimicrobial
- **AR Detail** - Resistance phenotypes and rates by organism
- **HAI Detail** - Confirmed HAI events by type and location
- **Denominators** - Patient days and device days by location
- **Submission** - Unified page for AU, AR, and HAI NHSN submission

### Dashboards (`/dashboards/`)
- Coming soon: Interactive analytics for trends, outcomes, and operational insights

## Alert Management

### Actions
- **Acknowledge** - Mark alert as seen (remains in active list)
- **Snooze** - Temporarily suppress for 4 hours
- **Resolve** - Close alert with resolution reason and notes

### Resolution Tracking
Track how alerts were handled:
- Acknowledged (no action needed)
- Messaged Team
- Discussed with Team
- Therapy Changed
- Therapy Stopped
- Patient Discharged
- Other

### Reports & Analytics
- Alert volume over time
- Average alerts per day
- Resolution rate
- Time to acknowledge/resolve
- Resolution reason breakdown with percentages
- Alerts by severity and status
- Alerts by day of week

### Filtering
- Filter by alert type (Bacteremia, Antimicrobial Usage)
- Filter by severity (Critical, Warning, Info)
- Filter by resolution reason
- Search by patient MRN

### Additional Features
- **Auto-refresh** - Active alerts page refreshes every 30 seconds
- **Relative timestamps** - "2 hours ago" format for easy scanning
- **Audit trail** - Full history of actions on each alert
- **Help page** - Built-in demo workflow guide
- **CCHMC branding** - Cincinnati Children's color scheme

## Quick Start

### Development

```bash
cd aegis/dashboard

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.template .env
# Edit .env with your settings

# Run development server
flask run

# Visit http://localhost:5000
```

### Production Deployment

The dashboard is deployed at `aegis-asp.com` using:
- **Gunicorn** - WSGI server
- **nginx** - Reverse proxy with SSL
- **systemd** - Service management
- **Let's Encrypt** - SSL certificates

See [deploy/](deploy/) for configuration files.

#### Deployment Commands

```bash
# Copy static files to web root
sudo cp static/style.css /var/www/aegis/static/

# Restart the service
sudo systemctl restart aegis

# Check status
sudo systemctl status aegis

# View logs
sudo journalctl -u aegis -f
```

## Configuration

Copy `.env.template` to `.env` and configure:

```bash
# Flask settings
FLASK_ENV=production
FLASK_DEBUG=false
FLASK_SECRET_KEY=your-secret-key

# Server
PORT=8082

# Dashboard URL (for Teams button callbacks)
DASHBOARD_BASE_URL=https://aegis-asp.com

# Alert database (shared with monitors)
ALERT_DB_PATH=~/.aegis/alerts.db

# App display name
APP_NAME=ASP Alerts
```

## Architecture

```
dashboard/
├── app.py                 # Flask application factory
├── config.py              # Configuration management
├── routes/
│   ├── views.py           # HTML page routes
│   └── api.py             # API endpoints for Teams callbacks
├── templates/
│   ├── base.html          # Base layout with navigation
│   ├── alerts_active.html # Active alerts list
│   ├── alerts_history.html# Historical alerts
│   ├── alert_detail.html  # Single alert view
│   ├── reports.html       # Analytics dashboard
│   └── help.html          # Demo workflow guide
├── static/
│   └── style.css          # CCHMC-themed styles
└── deploy/
    ├── aegis.service      # systemd service
    └── nginx-aegis.conf   # nginx config
```

## API Endpoints

### Teams Callbacks (GET - redirect after action)
- `GET /api/ack/<alert_id>` - Acknowledge alert
- `GET /api/snooze/<alert_id>?hours=4` - Snooze alert

### Form Actions (POST - from dashboard)
- `POST /api/alerts/<id>/acknowledge` - Acknowledge
- `POST /api/alerts/<id>/snooze` - Snooze
- `POST /api/alerts/<id>/resolve` - Resolve with reason/notes
- `POST /api/alerts/<id>/note` - Add note

### JSON API
- `GET /api/alerts` - List alerts (with filters)
- `GET /api/alerts/<id>` - Get single alert
- `GET /api/stats` - Get alert statistics

## Pages

### Landing Page
| Route | Description |
|-------|-------------|
| `/` | Landing page with 4 section cards |

### ASP Alerts
| Route | Description |
|-------|-------------|
| `/asp-alerts/` | Active (non-resolved) alerts |
| `/asp-alerts/history` | Resolved alerts |
| `/asp-alerts/<id>` | Single alert detail |
| `/asp-alerts/reports` | Analytics and reports |
| `/asp-alerts/help` | Demo workflow guide |

### HAI Detection
| Route | Description |
|-------|-------------|
| `/hai-detection/` | CLABSI candidates dashboard |
| `/hai-detection/candidate/<id>` | Candidate detail with IP review |
| `/hai-detection/history` | Resolved candidates |
| `/hai-detection/reports` | HAI analytics |
| `/hai-detection/help` | Help guide |

### NHSN Reporting
| Route | Description |
|-------|-------------|
| `/nhsn-reporting/` | AU/AR/HAI overview dashboard |
| `/nhsn-reporting/au` | Antibiotic usage detail |
| `/nhsn-reporting/ar` | Antimicrobial resistance detail |
| `/nhsn-reporting/hai` | HAI events detail |
| `/nhsn-reporting/denominators` | Patient days by location |
| `/nhsn-reporting/submission` | Unified NHSN submission (AU, AR, HAI) |
| `/nhsn-reporting/help` | Help guide |

### Dashboards
| Route | Description |
|-------|-------------|
| `/dashboards/` | Analytics dashboards (coming soon) |

## Related Documentation

- [AEGIS Overview](../README.md)
- [Demo Workflow](../docs/demo-workflow.md)
- [Bacteremia Alerts](../asp-bacteremia-alerts/README.md)
- [Antimicrobial Usage Alerts](../antimicrobial-usage-alerts/README.md)
