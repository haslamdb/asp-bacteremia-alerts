"""Multi-channel alerter with severity-based routing.

Routes alerts to appropriate channels based on severity:
- CRITICAL: SMS + Email (immediate notification)
- WARNING: Email only
- INFO: Email only (or skip)
"""

from datetime import datetime

from .base import BaseAlerter
from .console import ConsoleAlerter
from .email import EmailAlerter
from .sms import SMSAlerter
from .sms_email import SMSEmailAlerter
from ..models import AlertSeverity, CoverageAssessment
from ..config import config


def determine_severity(assessment: CoverageAssessment) -> AlertSeverity:
    """
    Determine alert severity based on organism and coverage status.

    CRITICAL: Resistant organisms (MRSA, VRE, Pseudomonas) with inadequate coverage
    WARNING: Other organisms with inadequate coverage
    INFO: Informational (adequate coverage, resolved)
    """
    organism = (assessment.culture.organism or "").lower()
    gram_stain = (assessment.culture.gram_stain or "").lower()

    # Critical organisms - resistant or high-risk
    critical_organisms = [
        "mrsa", "methicillin resistant",
        "vre", "vancomycin resistant",
        "pseudomonas",
        "candida",  # Candidemia always serious
        "esbl",
        "carbapenem resistant",
        "cre",
    ]

    is_critical_organism = any(org in organism for org in critical_organisms)

    # GPC in clusters without MRSA coverage is critical
    if "gram positive cocci" in gram_stain and "cluster" in gram_stain:
        is_critical_organism = True

    if is_critical_organism:
        return AlertSeverity.CRITICAL
    else:
        return AlertSeverity.WARNING


class MultiChannelAlerter(BaseAlerter):
    """Route alerts to appropriate channels based on severity."""

    def __init__(
        self,
        enable_console: bool = True,
        enable_email: bool = True,
        enable_sms: bool = True,
        sms_on_warning: bool = False,  # Only SMS for critical by default
    ):
        """
        Initialize multi-channel alerter.

        Args:
            enable_console: Always print to console
            enable_email: Send email alerts
            enable_sms: Send SMS alerts for critical
            sms_on_warning: Also send SMS for warning severity (default: False)
        """
        self.enable_console = enable_console
        self.enable_email = enable_email
        self.enable_sms = enable_sms
        self.sms_on_warning = sms_on_warning

        # Initialize channels
        self.console = ConsoleAlerter() if enable_console else None
        self.email = EmailAlerter() if enable_email else None
        self.sms = SMSAlerter() if enable_sms else None

        self.alert_count = 0
        self.alerts_by_severity: dict[AlertSeverity, int] = {
            AlertSeverity.CRITICAL: 0,
            AlertSeverity.WARNING: 0,
            AlertSeverity.INFO: 0,
        }

    def send_alert(self, assessment: CoverageAssessment) -> bool:
        """Send alert through appropriate channels based on severity."""
        severity = determine_severity(assessment)
        success = False

        print(f"\n  Alert Severity: {severity.value.upper()}")

        # Console always (if enabled)
        if self.console:
            self.console.send_alert(assessment)
            success = True

        # Email for all severities (if enabled and configured)
        if self.email and self.email.is_configured():
            if self.email.send_alert(assessment):
                success = True

        # SMS only for critical (or warning if configured)
        if self.sms and self.sms.is_configured():
            should_sms = (
                severity == AlertSeverity.CRITICAL or
                (severity == AlertSeverity.WARNING and self.sms_on_warning)
            )
            if should_sms:
                if self.sms.send_alert(assessment):
                    success = True

        if success:
            self.alert_count += 1
            self.alerts_by_severity[severity] += 1

        return success

    def get_alert_count(self) -> int:
        """Return total number of alerts sent."""
        return self.alert_count

    def get_summary(self) -> dict:
        """Get summary of alerts by severity."""
        return {
            "total": self.alert_count,
            "critical": self.alerts_by_severity[AlertSeverity.CRITICAL],
            "warning": self.alerts_by_severity[AlertSeverity.WARNING],
            "info": self.alerts_by_severity[AlertSeverity.INFO],
            "channels": {
                "console": self.console.get_alert_count() if self.console else 0,
                "email": self.email.get_alert_count() if self.email else 0,
                "sms": self.sms.get_alert_count() if self.sms else 0,
            },
        }

    def print_summary(self):
        """Print alert summary."""
        summary = self.get_summary()
        print("\n" + "=" * 50)
        print("ALERT SUMMARY")
        print("=" * 50)
        print(f"  Total Alerts:    {summary['total']}")
        print(f"    Critical:      {summary['critical']}")
        print(f"    Warning:       {summary['warning']}")
        print(f"    Info:          {summary['info']}")
        print(f"  Channels Used:")
        print(f"    Console:       {summary['channels']['console']}")
        print(f"    Email:         {summary['channels']['email']}")
        print(f"    SMS:           {summary['channels']['sms']}")
        print("=" * 50)


def create_alerter_from_config() -> BaseAlerter:
    """
    Factory function to create appropriate alerter based on configuration.

    Returns MultiChannelAlerter if email or SMS configured,
    otherwise returns ConsoleAlerter.
    """
    email_configured = bool(config.SMTP_SERVER and config.ALERT_EMAIL_TO)

    # Check for Twilio SMS
    twilio_configured = bool(
        config.TWILIO_ACCOUNT_SID and
        config.TWILIO_AUTH_TOKEN and
        config.TWILIO_FROM_NUMBER and
        config.ALERT_SMS_TO_NUMBERS
    )

    # Check for SMS-via-email (alternative to Twilio)
    sms_email_configured = bool(config.SMTP_SERVER and config.SMS_EMAIL_RECIPIENTS)

    sms_configured = twilio_configured or sms_email_configured

    if email_configured or sms_configured:
        alerter = MultiChannelAlerter(
            enable_console=True,
            enable_email=email_configured,
            enable_sms=twilio_configured,  # Twilio SMS
        )

        # Add SMS-via-email if configured (uses SMTP, not Twilio)
        if sms_email_configured and not twilio_configured:
            sms_email = SMSEmailAlerter(recipients=config.SMS_EMAIL_RECIPIENTS)
            alerter.sms = sms_email
            print(f"SMS via email configured for {len(config.SMS_EMAIL_RECIPIENTS)} recipient(s)")

        return alerter
    else:
        print("No email or SMS configured - using console alerter only")
        return ConsoleAlerter()
