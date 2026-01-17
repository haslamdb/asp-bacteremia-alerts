# Antimicrobial Usage Alerts

Monitors broad-spectrum antibiotic usage duration and alerts when medications exceed configurable thresholds. Part of the [ASP Alerts](../README.md) system.

## Overview

This module tracks active medication orders for broad-spectrum antibiotics (meropenem, vancomycin, etc.) and generates alerts when usage duration exceeds a configurable threshold (default: 72 hours). This supports antimicrobial stewardship by prompting review of prolonged broad-spectrum therapy.

## Features

- **Duration monitoring** - Tracks time since medication start date
- **Configurable thresholds** - Default 72 hours, adjustable per site
- **Severity escalation** - Warning at threshold, Critical at 2x threshold
- **Persistent deduplication** - SQLite-backed tracking prevents re-alerting
- **Multi-channel alerts** - Email and Teams with action buttons
- **Dashboard integration** - View, acknowledge, snooze, and resolve alerts

## Quick Start

```bash
# From the asp-alerts root directory
cd antimicrobial-usage-alerts

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.template .env
# Edit .env with your settings

# Run once (dry-run mode)
python -m src.runner --once --dry-run

# Run once (send alerts)
python -m src.runner --once

# Run continuous monitoring
python -m src.runner
```

## Configuration

Copy `.env.template` to `.env` and configure:

### FHIR Server

```bash
# Local development
FHIR_BASE_URL=http://localhost:8081/fhir

# Epic production
EPIC_FHIR_BASE_URL=https://epicfhir.yoursite.org/api/FHIR/R4
EPIC_CLIENT_ID=your-client-id
EPIC_PRIVATE_KEY_PATH=./keys/epic_private_key.pem
```

### Alert Channels

```bash
# Microsoft Teams (recommended)
TEAMS_WEBHOOK_URL=https://prod-XX.westus.logic.azure.com:443/workflows/...

# Email
SMTP_SERVER=smtp.yoursite.org
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
ALERT_EMAIL_FROM=asp-alerts@yoursite.org
ALERT_EMAIL_TO=asp-team@yoursite.org
```

### Monitoring Settings

```bash
# Alert threshold (hours)
ALERT_THRESHOLD_HOURS=72

# Add additional medications to monitor (RxNorm code:Name)
EXTRA_MONITORED_MEDICATIONS=4053:Piperacillin-tazobactam,5479:Linezolid

# Poll interval (seconds)
POLL_INTERVAL=300
```

### Dashboard Integration

```bash
# Dashboard URL for Teams action buttons
DASHBOARD_BASE_URL=http://your-dashboard:5000

# API key for secure callbacks
DASHBOARD_API_KEY=your-secret-key

# Alert database path (shared with dashboard)
ALERT_DB_PATH=/path/to/alerts.db
```

## Monitored Medications

Default monitored medications (by RxNorm code):

| RxNorm Code | Medication |
|-------------|------------|
| 29561 | Meropenem |
| 11124 | Vancomycin |

Add more via `EXTRA_MONITORED_MEDICATIONS` environment variable.

## Alert Severity

| Severity | Condition | Actions |
|----------|-----------|---------|
| **Warning** | Duration >= threshold | Teams + Email |
| **Critical** | Duration >= 2x threshold | Teams + Email (urgent styling) |

## CLI Usage

```bash
# Single check, dry run (no alerts sent)
python -m src.runner --once --dry-run

# Single check, send alerts
python -m src.runner --once

# Show all patients exceeding threshold (no dedup)
python -m src.runner --once --all

# Continuous monitoring (daemon mode)
python -m src.runner

# Verbose logging
python -m src.runner --once --verbose
```

## Architecture

```
antimicrobial-usage-alerts/
├── src/
│   ├── alerters/
│   │   ├── email_alerter.py    # Email notifications
│   │   └── teams_alerter.py    # Teams with action buttons
│   ├── config.py               # Environment configuration
│   ├── fhir_client.py          # FHIR API client
│   ├── models.py               # Data models
│   ├── monitor.py              # BroadSpectrumMonitor class
│   └── runner.py               # CLI entry point
├── tests/                      # Unit tests
├── .env.template               # Configuration template
└── requirements.txt            # Python dependencies
```

## Data Models

### UsageAssessment

```python
@dataclass
class UsageAssessment:
    patient: Patient
    medication: MedicationOrder
    duration_hours: float
    threshold_hours: float
    exceeds_threshold: bool
    recommendation: str
    severity: AlertSeverity
```

### Alert Lifecycle

1. **Monitor** detects medication exceeding threshold
2. **Alert created** in persistent store (status: PENDING)
3. **Alert sent** via configured channels (status: SENT)
4. **User action** via Teams button or dashboard:
   - Acknowledge (status: ACKNOWLEDGED)
   - Snooze 4h (status: SNOOZED, with expiration)
   - Resolve (status: RESOLVED, with reason/notes)

## Integration with Dashboard

Teams alerts include action buttons that link to the dashboard:

- **Acknowledge** - Mark as seen, stays in active list
- **Snooze 4h** - Temporarily suppress, auto-reactivates
- **View Details** - Open alert in dashboard

The dashboard provides:
- Active alert list with filters
- Resolution workflow with reasons and notes
- Historical view of resolved alerts
- Audit trail for compliance

## Testing

```bash
# Generate test data
cd ../scripts
python generate_pediatric_data.py --count 5

# Run with verbose output
cd ../antimicrobial-usage-alerts
python -m src.runner --once --verbose --dry-run
```

## Troubleshooting

### No alerts generated

1. Check FHIR server is accessible: `curl $FHIR_BASE_URL/metadata`
2. Verify monitored medications exist in FHIR
3. Check threshold setting in .env
4. Use `--verbose` flag for detailed logging

### Teams alerts not sending

1. Test webhook: `python -c "from common.channels.teams import test_webhook; test_webhook('YOUR_URL')"`
2. Verify webhook URL in .env
3. Check Teams channel permissions

### Duplicate alerts

- Alerts are deduplicated by medication order FHIR ID
- Clear alert store to reset: delete alerts.db or resolve all alerts
- Use `--all` flag to bypass deduplication (for testing)

## Related Documentation

- [ASP Alerts Overview](../README.md)
- [Bacteremia Alerts](../asp-bacteremia-alerts/README.md)
