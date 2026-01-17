# Notifications

The ASP Bacteremia Alerts system supports multiple notification channels with severity-based routing.

## Notification Channels

### Console (Default)
Always enabled. Prints alerts to stdout for development and logging.

### Email (SMTP)
Sends formatted HTML/plain-text emails with full alert details.

### Microsoft Teams (Workflows Webhook)
Sends Adaptive Card alerts to Teams channels via Power Automate Workflows.

## Severity-Based Routing

Alerts are automatically classified by severity:

| Severity | Criteria | Channels |
|----------|----------|----------|
| **CRITICAL** | MRSA, VRE, Pseudomonas, Candida, ESBL, CRE | Console + Email + Teams |
| **WARNING** | Other organisms with inadequate coverage | Console + Email + Teams |
| **INFO** | Informational (future: daily summaries) | Console + Email |

## Configuration

### Email Setup

```bash
# .env
SMTP_SERVER=smtp.yourserver.com
SMTP_PORT=587
SMTP_USERNAME=alerts@hospital.org
SMTP_PASSWORD=your-password

ALERT_EMAIL_FROM=asp-alerts@hospital.org
ALERT_EMAIL_TO=asp-team@hospital.org,pharmacist@hospital.org
```

### Teams Setup (Workflows Webhook)

1. In your Teams channel, click `...` > **Workflows**
2. Search for "Post to a channel when a webhook request is received"
3. Select team/channel and click **Add workflow**
4. Copy the webhook URL

```bash
# .env
TEAMS_WEBHOOK_URL=https://prod-XX.westus.logic.azure.com:443/workflows/...
```

**Test your webhook:**
```bash
python test_teams_webhook.py "YOUR_WEBHOOK_URL"
```

## Example Alert Messages

### Email (HTML)

```
Subject: [ASP Alert] Bacteremia Coverage - TEST001 - MRSA

┌─────────────────────────────────────────────┐
│  BACTEREMIA COVERAGE ALERT                  │
├─────────────────────────────────────────────┤
│  Patient:   Alice Johnson (TEST001)         │
│  Location:  5NW                             │
│  Organism:  MRSA                            │
│  Current:   Cefazolin 2g IV                 │
│  Status:    INADEQUATE                      │
│                                             │
│  Recommendation:                            │
│  Add vancomycin or daptomycin for MRSA      │
│  coverage                                   │
└─────────────────────────────────────────────┘
```

### Teams (Adaptive Card)

```
🔴 BACTEREMIA COVERAGE ALERT
───────────────────────────────
Patient:      Alice Johnson (TEST001)
Location:     5NW
Organism:     MRSA
Current Abx:  Cefazolin 2g IV
Status:       ⚠️ INADEQUATE

Recommendation: Add vancomycin or daptomycin for MRSA coverage
```

## Testing Notifications

### Test Email
```python
from src.alerters.email import EmailAlerter
from src.models import Patient, CultureResult, CoverageAssessment, CoverageStatus

# Create test assessment
patient = Patient(fhir_id="1", mrn="TEST", name="Test Patient")
culture = CultureResult(fhir_id="1", patient_id="1", organism="Test Organism")
assessment = CoverageAssessment(
    patient=patient,
    culture=culture,
    coverage_status=CoverageStatus.INADEQUATE,
    recommendation="Test recommendation"
)

# Send test email
alerter = EmailAlerter()
alerter.send_alert(assessment)
```

### Test Teams
```bash
# Quick test with URL
python test_teams_webhook.py "YOUR_WEBHOOK_URL"

# Or from Python
from src.alerters.teams import test_webhook
test_webhook("YOUR_WEBHOOK_URL")
```

## Extending Notifications

To add a new notification channel:

1. Create new file in `src/alerters/`
2. Inherit from `BaseAlerter`
3. Implement `send_alert()` and `get_alert_count()`
4. Add to `src/alerters/__init__.py`
5. Update `MultiChannelAlerter` if needed

Example skeleton:

```python
from .base import BaseAlerter
from ..models import CoverageAssessment

class MyAlerter(BaseAlerter):
    def __init__(self, **config):
        self.alert_count = 0
        # Initialize your service

    def send_alert(self, assessment: CoverageAssessment) -> bool:
        # Send notification
        # Return True on success
        self.alert_count += 1
        return True

    def get_alert_count(self) -> int:
        return self.alert_count

    def is_configured(self) -> bool:
        # Check if properly configured
        return True
```

## Future Enhancements

- Slack webhooks
- PagerDuty/Opsgenie for on-call escalation
- Epic In Basket via FHIR Communication resource
- Daily summary emails
