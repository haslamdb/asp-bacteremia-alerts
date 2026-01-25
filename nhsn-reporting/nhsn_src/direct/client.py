"""DIRECT protocol client for NHSN submission.

The DIRECT protocol is a secure health information exchange standard
that uses S/MIME encrypted email for transmission. This client supports
submission of CDA documents to NHSN via a Health Information Service
Provider (HISP).

Configuration requires:
- HISP SMTP server and credentials
- NHSN DIRECT address (obtained from NHSN)
- Sender DIRECT address (obtained from HISP)
- Optional: X.509 certificates for S/MIME encryption

Reference: https://www.cdc.gov/nhsn/cdaportal/importingdata.html
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DirectConfig:
    """Configuration for DIRECT protocol submission."""

    # HISP SMTP settings
    hisp_smtp_server: str = ""
    hisp_smtp_port: int = 587
    hisp_smtp_username: str = ""
    hisp_smtp_password: str = ""
    hisp_use_tls: bool = True

    # DIRECT addresses
    sender_direct_address: str = ""  # Your organization's DIRECT address
    nhsn_direct_address: str = ""     # NHSN's DIRECT address for your facility

    # Facility info (for message headers)
    facility_id: str = ""
    facility_name: str = ""

    # Certificate paths (optional, for S/MIME)
    sender_cert_path: str = ""
    sender_key_path: str = ""
    nhsn_cert_path: str = ""  # NHSN's public certificate

    # Submission settings
    timeout_seconds: int = 60
    max_retries: int = 3

    def is_configured(self) -> bool:
        """Check if DIRECT submission is properly configured."""
        required = [
            self.hisp_smtp_server,
            self.hisp_smtp_username,
            self.hisp_smtp_password,
            self.sender_direct_address,
            self.nhsn_direct_address,
        ]
        return all(required)

    def get_missing_config(self) -> list[str]:
        """Get list of missing configuration items."""
        missing = []
        if not self.hisp_smtp_server:
            missing.append("HISP SMTP server")
        if not self.hisp_smtp_username:
            missing.append("HISP SMTP username")
        if not self.hisp_smtp_password:
            missing.append("HISP SMTP password")
        if not self.sender_direct_address:
            missing.append("Sender DIRECT address")
        if not self.nhsn_direct_address:
            missing.append("NHSN DIRECT address")
        return missing


@dataclass
class DirectSubmissionResult:
    """Result of a DIRECT submission attempt."""

    success: bool = False
    message_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    documents_sent: int = 0
    error_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "message_id": self.message_id,
            "timestamp": self.timestamp.isoformat(),
            "documents_sent": self.documents_sent,
            "error_message": self.error_message,
            "details": self.details,
        }


class DirectClient:
    """Client for DIRECT protocol submission to NHSN."""

    def __init__(self, config: DirectConfig):
        """Initialize the DIRECT client.

        Args:
            config: DIRECT configuration
        """
        self.config = config

    def test_connection(self) -> tuple[bool, str]:
        """Test the HISP SMTP connection.

        Returns:
            Tuple of (success, message)
        """
        if not self.config.is_configured():
            missing = self.config.get_missing_config()
            return False, f"Missing configuration: {', '.join(missing)}"

        try:
            with self._get_smtp_connection() as server:
                # Connection successful
                return True, "Connection successful"
        except smtplib.SMTPAuthenticationError as e:
            return False, f"Authentication failed: {e}"
        except smtplib.SMTPConnectError as e:
            return False, f"Connection failed: {e}"
        except Exception as e:
            return False, f"Error: {e}"

    def submit_cda_documents(
        self,
        cda_documents: list[str],
        submission_type: str = "HAI-BSI",
        preparer_name: str = "",
        notes: str = "",
    ) -> DirectSubmissionResult:
        """Submit CDA documents to NHSN via DIRECT protocol.

        Args:
            cda_documents: List of CDA XML strings
            submission_type: Type of submission (for subject line)
            preparer_name: Name of the person preparing the submission
            notes: Optional notes to include

        Returns:
            DirectSubmissionResult with submission status
        """
        result = DirectSubmissionResult()

        if not self.config.is_configured():
            missing = self.config.get_missing_config()
            result.error_message = f"DIRECT not configured: {', '.join(missing)}"
            return result

        if not cda_documents:
            result.error_message = "No CDA documents provided"
            return result

        try:
            # Create the message
            msg = self._create_message(
                cda_documents,
                submission_type,
                preparer_name,
                notes,
            )
            result.message_id = msg["Message-ID"]

            # Send via HISP SMTP
            with self._get_smtp_connection() as server:
                server.send_message(msg)

            result.success = True
            result.documents_sent = len(cda_documents)
            result.details = {
                "submission_type": submission_type,
                "preparer": preparer_name,
                "recipient": self.config.nhsn_direct_address,
            }

            logger.info(
                f"DIRECT submission successful: {len(cda_documents)} documents, "
                f"Message-ID: {result.message_id}"
            )

        except smtplib.SMTPAuthenticationError as e:
            result.error_message = f"HISP authentication failed: {e}"
            logger.error(f"DIRECT authentication error: {e}")
        except smtplib.SMTPRecipientsRefused as e:
            result.error_message = f"NHSN address rejected: {e}"
            logger.error(f"DIRECT recipient refused: {e}")
        except smtplib.SMTPException as e:
            result.error_message = f"SMTP error: {e}"
            logger.error(f"DIRECT SMTP error: {e}")
        except Exception as e:
            result.error_message = f"Submission failed: {e}"
            logger.error(f"DIRECT submission error: {e}")

        return result

    def _get_smtp_connection(self) -> smtplib.SMTP:
        """Get an SMTP connection to the HISP server."""
        server = smtplib.SMTP(
            self.config.hisp_smtp_server,
            self.config.hisp_smtp_port,
            timeout=self.config.timeout_seconds,
        )

        if self.config.hisp_use_tls:
            context = ssl.create_default_context()
            server.starttls(context=context)

        server.login(
            self.config.hisp_smtp_username,
            self.config.hisp_smtp_password,
        )

        return server

    def _create_message(
        self,
        cda_documents: list[str],
        submission_type: str,
        preparer_name: str,
        notes: str,
    ) -> MIMEMultipart:
        """Create the MIME message with CDA attachments.

        Args:
            cda_documents: List of CDA XML strings
            submission_type: Type of submission
            preparer_name: Preparer's name
            notes: Optional notes

        Returns:
            MIME message ready for sending
        """
        msg = MIMEMultipart()

        # Headers
        msg["From"] = self.config.sender_direct_address
        msg["To"] = self.config.nhsn_direct_address
        msg["Subject"] = (
            f"NHSN {submission_type} Submission - "
            f"{self.config.facility_name} ({self.config.facility_id})"
        )

        # Generate unique message ID
        import uuid
        msg["Message-ID"] = f"<{uuid.uuid4()}@{self.config.sender_direct_address.split('@')[-1]}>"

        # Body text
        body = f"""NHSN Healthcare Associated Infection Data Submission

Facility: {self.config.facility_name}
Facility ID: {self.config.facility_id}
Submission Type: {submission_type}
Documents: {len(cda_documents)}
Submitted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Prepared by: {preparer_name or 'System'}

{notes if notes else ''}

This message was automatically generated by the ASP-Alerts NHSN Reporting Module.
"""
        msg.attach(MIMEText(body, "plain"))

        # Attach CDA documents
        for i, cda_xml in enumerate(cda_documents, 1):
            attachment = MIMEBase("application", "xml")
            attachment.set_payload(cda_xml.encode("utf-8"))
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition",
                f"attachment; filename=hai_report_{i:03d}.xml"
            )
            attachment.add_header(
                "Content-Type",
                "application/xml; charset=utf-8"
            )
            msg.attach(attachment)

        return msg


def load_direct_config_from_env() -> DirectConfig:
    """Load DIRECT configuration from environment variables.

    Environment variables:
        NHSN_HISP_SMTP_SERVER
        NHSN_HISP_SMTP_PORT
        NHSN_HISP_SMTP_USERNAME
        NHSN_HISP_SMTP_PASSWORD
        NHSN_HISP_USE_TLS
        NHSN_SENDER_DIRECT_ADDRESS
        NHSN_DIRECT_ADDRESS
        NHSN_FACILITY_ID
        NHSN_FACILITY_NAME
        NHSN_SENDER_CERT_PATH
        NHSN_SENDER_KEY_PATH
        NHSN_CERT_PATH

    Returns:
        DirectConfig populated from environment
    """
    import os

    return DirectConfig(
        hisp_smtp_server=os.getenv("NHSN_HISP_SMTP_SERVER", ""),
        hisp_smtp_port=int(os.getenv("NHSN_HISP_SMTP_PORT", "587")),
        hisp_smtp_username=os.getenv("NHSN_HISP_SMTP_USERNAME", ""),
        hisp_smtp_password=os.getenv("NHSN_HISP_SMTP_PASSWORD", ""),
        hisp_use_tls=os.getenv("NHSN_HISP_USE_TLS", "true").lower() == "true",
        sender_direct_address=os.getenv("NHSN_SENDER_DIRECT_ADDRESS", ""),
        nhsn_direct_address=os.getenv("NHSN_DIRECT_ADDRESS", ""),
        facility_id=os.getenv("NHSN_FACILITY_ID", ""),
        facility_name=os.getenv("NHSN_FACILITY_NAME", ""),
        sender_cert_path=os.getenv("NHSN_SENDER_CERT_PATH", ""),
        sender_key_path=os.getenv("NHSN_SENDER_KEY_PATH", ""),
        nhsn_cert_path=os.getenv("NHSN_CERT_PATH", ""),
    )
