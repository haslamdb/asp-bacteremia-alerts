# Notifications

The ASP Bacteremia Alerts system supports multiple notification channels with severity-based routing.

## Notification Channels

### Console (Default)
Always enabled. Prints alerts to stdout for development and logging.

### Email (SMTP)
Sends formatted HTML/plain-text emails with full alert details.

### SMS (Twilio)
Sends text messages for critical alerts. Supports HIPAA-conscious options:
- **With PHI**: Includes MRN, location, organism (default)
- **Without PHI**: Just "check Epic" notification

## Severity-Based Routing

Alerts are automatically classified by severity:

| Severity | Criteria | Channels |
|----------|----------|----------|
| **CRITICAL** | MRSA, VRE, Pseudomonas, Candida, ESBL, CRE | Console + Email + SMS |
| **WARNING** | Other organisms with inadequate coverage | Console + Email |
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

### SMS Setup (Twilio)

1. Create account at [twilio.com](https://twilio.com)
2. Get Account SID and Auth Token from console
3. Purchase a phone number

```bash
# .env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+15135551234

# Recipient phone numbers (E.164 format)
ALERT_SMS_TO_NUMBERS=+15135559876,+15135555555

# Set to false for HIPAA-safe "check Epic" messages
ALERT_SMS_INCLUDE_PHI=true
```

**Twilio pricing**: ~$0.0079 per SMS. For 10 alerts/day = ~$2.40/month.

## HIPAA Considerations

Standard SMS is not encrypted. Options:

1. **No PHI (safest)**: Set `ALERT_SMS_INCLUDE_PHI=false`
   - Message: "ASP Alert: New bacteremia coverage concern detected. Check Epic In Basket for details."

2. **Minimal PHI (common practice)**: Set `ALERT_SMS_INCLUDE_PHI=true`
   - Message includes: MRN, location, organism, current antibiotics

3. **HIPAA-compliant SMS**: Use services like TigerConnect, Imprivata Cortext, or OhMD instead of Twilio.

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

### SMS (with PHI)

```
ASP Bacteremia Alert
MRN: TEST001
Loc: 5NW
Organism: MRSA
Abx: Cefazolin 2g IV
Action: Add vancomycin or daptomycin for MRSA coverage
```

### SMS (without PHI)

```
ASP Alert: New bacteremia coverage concern detected. Check Epic In Basket for details.
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

### Test SMS
```python
from src.alerters.sms import SMSAlerter

alerter = SMSAlerter()
if alerter.is_configured():
    alerter.send_alert(assessment)
else:
    print("SMS not configured")
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

- Microsoft Teams webhooks
- Slack webhooks
- PagerDuty/Opsgenie for on-call escalation
- Epic In Basket via FHIR Communication resource
- Daily summary emails
