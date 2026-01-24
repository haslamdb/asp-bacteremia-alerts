"""HAI Candidate Monitor.

Main service that orchestrates:
1. Rule-based candidate detection
2. Note retrieval for LLM context
3. LLM extraction + rules-based classification
4. Routing to IP review queue
"""

import logging
import time
from datetime import datetime, timedelta

from common.alert_store import AlertStore, AlertType

from .config import Config
from .db import HAIDatabase
from .models import (
    HAICandidate,
    HAIType,
    CandidateStatus,
    ClassificationDecision,
)
from .candidates import CLABSICandidateDetector, SSICandidateDetector, VAECandidateDetector, CAUTICandidateDetector, CDICandidateDetector
from .classifiers import CLABSIClassifierV2, SSIClassifierV2, VAEClassifier, CAUTIClassifier, CDIClassifier
from .notes.retriever import NoteRetriever

logger = logging.getLogger(__name__)


class HAIMonitor:
    """Monitor for HAI candidate detection and classification."""

    def __init__(
        self,
        db: HAIDatabase | None = None,
        alert_store: AlertStore | None = None,
        lookback_hours: int | None = None,
    ):
        """Initialize the monitor.

        Args:
            db: HAI database instance. Creates default if None.
            alert_store: Shared alert store. Creates default if None.
            lookback_hours: Hours to look back for new cultures. Uses config if None.
        """
        self.db = db or HAIDatabase(Config.HAI_DB_PATH)
        self.alert_store = alert_store or AlertStore(db_path=Config.ALERT_DB_PATH)
        self.lookback_hours = lookback_hours or Config.LOOKBACK_HOURS

        # Initialize detectors for each HAI type
        self.detectors = {
            HAIType.CLABSI: CLABSICandidateDetector(),
            HAIType.SSI: SSICandidateDetector(),
            HAIType.VAE: VAECandidateDetector(),
            HAIType.CAUTI: CAUTICandidateDetector(),
            HAIType.CDI: CDICandidateDetector(),
        }

        # Initialize classifiers and note retriever (lazy-loaded)
        self._classifiers: dict[HAIType, CLABSIClassifierV2 | SSIClassifierV2 | VAEClassifier] = {}
        self._note_retriever: NoteRetriever | None = None

        # Track processed cultures to avoid duplicates within session
        self._processed_cultures: set[str] = set()

    def get_classifier(self, hai_type: HAIType) -> CLABSIClassifierV2 | SSIClassifierV2 | VAEClassifier | CDIClassifier:
        """Get classifier for the specified HAI type (lazy-loaded).

        Args:
            hai_type: Type of HAI to get classifier for.

        Returns:
            Appropriate classifier for the HAI type.
        """
        if hai_type not in self._classifiers:
            if hai_type == HAIType.CLABSI:
                self._classifiers[hai_type] = CLABSIClassifierV2(db=self.db)
            elif hai_type == HAIType.SSI:
                self._classifiers[hai_type] = SSIClassifierV2(db=self.db)
            elif hai_type == HAIType.VAE:
                self._classifiers[hai_type] = VAEClassifier(db=self.db)
            elif hai_type == HAIType.CAUTI:
                self._classifiers[hai_type] = CAUTIClassifier()
            elif hai_type == HAIType.CDI:
                self._classifiers[hai_type] = CDIClassifier()
            else:
                # Default to CLABSI classifier for other types for now
                logger.warning(f"No specific classifier for {hai_type}, using CLABSI")
                self._classifiers[hai_type] = CLABSIClassifierV2(db=self.db)
        return self._classifiers[hai_type]

    @property
    def classifier(self) -> CLABSIClassifierV2:
        """Get CLABSI classifier (legacy property for backwards compatibility)."""
        return self.get_classifier(HAIType.CLABSI)

    @property
    def note_retriever(self) -> NoteRetriever:
        """Lazy-load note retriever."""
        if self._note_retriever is None:
            self._note_retriever = NoteRetriever()
        return self._note_retriever

    def run_once(self, dry_run: bool = False) -> int:
        """Run a single detection cycle.

        Args:
            dry_run: If True, don't save candidates or create alerts.

        Returns:
            Number of new candidates identified.
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(hours=self.lookback_hours)

        logger.info(f"Starting detection cycle: {start_date} to {end_date}")

        total_candidates = 0

        for hai_type, detector in self.detectors.items():
            logger.info(f"Running {hai_type.value} detection...")

            try:
                candidates = detector.detect_candidates(start_date, end_date)
                new_count = self._process_candidates(candidates, dry_run=dry_run)
                total_candidates += new_count

                logger.info(
                    f"{hai_type.value}: {len(candidates)} candidates found, "
                    f"{new_count} new"
                )

            except Exception as e:
                logger.error(f"Error in {hai_type.value} detection: {e}", exc_info=True)

        logger.info(f"Detection cycle complete: {total_candidates} new candidates")
        return total_candidates

    def _process_candidates(
        self,
        candidates: list[HAICandidate],
        dry_run: bool = False,
    ) -> int:
        """Process detected candidates.

        Args:
            candidates: List of candidates from detector.
            dry_run: If True, don't persist anything.

        Returns:
            Number of new candidates processed.
        """
        new_count = 0

        for candidate in candidates:
            # Skip if already processed this session
            if candidate.culture.fhir_id in self._processed_cultures:
                continue

            # Check if already in database
            if self.db.check_candidate_exists(
                candidate.hai_type, candidate.culture.fhir_id
            ):
                logger.debug(
                    f"Candidate already exists: {candidate.culture.fhir_id}"
                )
                continue

            # Skip if already alerted in shared store
            if self.alert_store.check_if_alerted(
                AlertType.NHSN_CLABSI, candidate.culture.fhir_id
            ):
                logger.debug(
                    f"Alert already exists for: {candidate.culture.fhir_id}"
                )
                continue

            if dry_run:
                logger.info(
                    f"[DRY RUN] Would create candidate: "
                    f"Patient={candidate.patient.mrn}, "
                    f"Organism={candidate.culture.organism}, "
                    f"Device days={candidate.device_days_at_culture}, "
                    f"Meets criteria={candidate.meets_initial_criteria}"
                )
            else:
                # Save to NHSN database
                self.db.save_candidate(candidate)

                # Create alert in shared store for dashboard visibility
                if candidate.meets_initial_criteria:
                    self._create_alert(candidate)
                    # Send email notification for new HAI candidate
                    self._send_new_candidate_email(candidate)

                logger.info(
                    f"Created candidate: {candidate.id} "
                    f"(Patient={candidate.patient.mrn})"
                )

            self._processed_cultures.add(candidate.culture.fhir_id)
            new_count += 1

        return new_count

    def _create_alert(self, candidate: HAICandidate) -> None:
        """Create alert in shared store for dashboard visibility."""
        # Determine alert type based on HAI type
        if candidate.hai_type == HAIType.SSI:
            alert_type = AlertType.NHSN_SSI
            title = f"SSI Candidate: {candidate.patient.name or candidate.patient.mrn}"
        elif candidate.hai_type == HAIType.VAE:
            alert_type = AlertType.NHSN_VAE
            title = f"VAE Candidate: {candidate.patient.name or candidate.patient.mrn}"
        elif candidate.hai_type == HAIType.CAUTI:
            alert_type = AlertType.NHSN_CAUTI
            title = f"CAUTI Candidate: {candidate.patient.name or candidate.patient.mrn}"
        elif candidate.hai_type == HAIType.CDI:
            alert_type = AlertType.NHSN_CDI
            title = f"CDI Candidate: {candidate.patient.name or candidate.patient.mrn}"
        else:
            alert_type = AlertType.NHSN_CLABSI
            title = f"CLABSI Candidate: {candidate.patient.name or candidate.patient.mrn}"

        summary = self._build_summary(candidate)

        # Build content based on HAI type
        content = {
            "candidate_id": candidate.id,
            "hai_type": candidate.hai_type.value,
            "organism": candidate.culture.organism,
            "culture_date": candidate.culture.collection_date.isoformat(),
        }

        if candidate.hai_type == HAIType.SSI:
            ssi_data = getattr(candidate, "_ssi_data", None)
            if ssi_data:
                content["procedure_name"] = ssi_data.procedure.procedure_name
                content["nhsn_category"] = ssi_data.procedure.nhsn_category
                content["days_post_op"] = ssi_data.days_post_op
        elif candidate.hai_type == HAIType.VAE:
            vae_data = getattr(candidate, "_vae_data", None)
            if vae_data:
                content["vac_onset_date"] = vae_data.vac_onset_date.isoformat() if vae_data.vac_onset_date else None
                content["ventilator_days"] = vae_data.episode.get_ventilator_days() if vae_data.episode else None
                content["baseline_min_fio2"] = vae_data.baseline_min_fio2
                content["baseline_min_peep"] = vae_data.baseline_min_peep
                content["fio2_increase"] = vae_data.fio2_increase
                content["peep_increase"] = vae_data.peep_increase
        elif candidate.hai_type == HAIType.CAUTI:
            cauti_data = getattr(candidate, "_cauti_data", None)
            if cauti_data:
                content["catheter_days"] = cauti_data.catheter_days
                content["catheter_type"] = cauti_data.catheter_episode.catheter_type if cauti_data.catheter_episode else None
                content["culture_cfu_ml"] = cauti_data.culture_cfu_ml
                content["patient_age"] = cauti_data.patient_age
            else:
                content["catheter_days"] = candidate.device_days_at_culture
                content["catheter_type"] = candidate.device_info.device_type if candidate.device_info else None
        elif candidate.hai_type == HAIType.CDI:
            cdi_data = getattr(candidate, "_cdi_data", None)
            if cdi_data:
                content["test_type"] = cdi_data.test_result.test_type
                content["test_date"] = cdi_data.test_result.test_date.isoformat()
                content["specimen_day"] = cdi_data.specimen_day
                content["onset_type"] = cdi_data.onset_type
                content["is_recurrent"] = cdi_data.is_recurrent
                content["is_duplicate"] = cdi_data.is_duplicate
                content["days_since_last_cdi"] = cdi_data.days_since_last_cdi
                content["classification"] = cdi_data.classification
        else:
            content["device_days"] = candidate.device_days_at_culture
            content["device_type"] = candidate.device_info.device_type if candidate.device_info else None

        self.alert_store.save_alert(
            alert_type=alert_type,
            source_id=candidate.culture.fhir_id,
            severity="warning",
            patient_id=candidate.patient.fhir_id,
            patient_mrn=candidate.patient.mrn,
            patient_name=candidate.patient.name,
            title=title,
            summary=summary,
            content=content,
        )

    def _build_summary(self, candidate: HAICandidate) -> str:
        """Build alert summary text."""
        if candidate.hai_type == HAIType.SSI:
            ssi_data = getattr(candidate, "_ssi_data", None)
            if ssi_data:
                parts = [
                    f"{ssi_data.procedure.procedure_name} ({ssi_data.procedure.nhsn_category})",
                    f"day {ssi_data.days_post_op} post-op",
                ]
                if candidate.culture.organism:
                    parts.append(f"- {candidate.culture.organism}")
                return ", ".join(parts)
            else:
                return f"SSI signal detected ({candidate.culture.organism or 'keyword-based'})"
        elif candidate.hai_type == HAIType.VAE:
            vae_data = getattr(candidate, "_vae_data", None)
            if vae_data:
                parts = ["VAC detected"]
                if vae_data.episode:
                    parts.append(f"on ventilator day {vae_data.episode.get_ventilator_days()}")
                if vae_data.fio2_increase:
                    parts.append(f"FiO2 +{vae_data.fio2_increase:.0f}%")
                if vae_data.peep_increase:
                    parts.append(f"PEEP +{vae_data.peep_increase:.0f}")
                return ", ".join(parts)
            else:
                return "Ventilator-associated condition detected"
        elif candidate.hai_type == HAIType.CAUTI:
            cauti_data = getattr(candidate, "_cauti_data", None)
            if cauti_data:
                parts = [
                    f"Positive urine culture ({candidate.culture.organism or 'organism pending'})",
                    f"with urinary catheter in place {cauti_data.catheter_days} days",
                ]
                if cauti_data.culture_cfu_ml:
                    parts.append(f"({cauti_data.culture_cfu_ml:,} CFU/mL)")
                return " ".join(parts)
            else:
                parts = [
                    f"Positive urine culture ({candidate.culture.organism or 'organism pending'})",
                ]
                if candidate.device_days_at_culture:
                    parts.append(f"with catheter in place {candidate.device_days_at_culture} days")
                return " ".join(parts)
        elif candidate.hai_type == HAIType.CDI:
            cdi_data = getattr(candidate, "_cdi_data", None)
            if cdi_data:
                # Onset type display
                onset_display = {
                    "ho": "HO-CDI",
                    "co": "CO-CDI",
                    "co_hcfa": "CO-HCFA-CDI",
                }
                onset = onset_display.get(cdi_data.onset_type, cdi_data.onset_type.upper())

                parts = [f"Positive C. diff {cdi_data.test_result.test_type}"]
                parts.append(f"specimen day {cdi_data.specimen_day}")
                parts.append(f"({onset})")

                if cdi_data.is_recurrent:
                    parts.append(f"RECURRENT ({cdi_data.days_since_last_cdi} days since last)")
                elif cdi_data.is_duplicate:
                    parts.append("DUPLICATE")
                else:
                    parts.append("INCIDENT")

                return ", ".join(parts)
            else:
                return "Positive C. difficile test detected"
        else:
            # CLABSI summary
            parts = [
                f"Positive blood culture ({candidate.culture.organism or 'organism pending'})",
                f"with central line in place {candidate.device_days_at_culture} days",
            ]

            if candidate.device_info:
                parts.append(f"({candidate.device_info.device_type})")

            return " ".join(parts)

    def _send_new_candidate_email(self, candidate: HAICandidate) -> None:
        """Send email notification for new HAI candidate."""
        if not Config.is_email_configured():
            return

        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            # Build HAI-type-specific email content
            hai_type_name = candidate.hai_type.value.upper()

            if candidate.hai_type == HAIType.SSI:
                subject = f"New SSI Candidate: {candidate.patient.mrn} - {candidate.culture.organism or 'Infection Signal'}"
                # Get SSI-specific data
                ssi_data = getattr(candidate, "_ssi_data", None)
                if ssi_data:
                    body = f"""
New SSI Candidate Detected

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

Procedure Information:
  - Procedure: {ssi_data.procedure.procedure_name} ({ssi_data.procedure.nhsn_category})
  - Procedure Date: {ssi_data.procedure.procedure_date.strftime('%Y-%m-%d')}
  - Days Post-Op: {ssi_data.days_post_op}
  - Wound Class: {ssi_data.procedure.wound_class or 'Not specified'}
  - Implant: {'Yes (' + ssi_data.procedure.implant_type + ')' if ssi_data.procedure.implant_used and ssi_data.procedure.implant_type else 'Yes' if ssi_data.procedure.implant_used else 'No'}

Infection Signal:
  - Organism: {ssi_data.wound_culture_organism or 'Keyword-based detection'}
  - Culture Date: {ssi_data.wound_culture_date.strftime('%Y-%m-%d') if ssi_data.wound_culture_date else 'N/A'}

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
                else:
                    body = f"""
New SSI Candidate Detected

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

Infection Signal:
  - Organism: {candidate.culture.organism or 'Keyword-based detection'}
  - Detection Date: {candidate.culture.collection_date.strftime('%Y-%m-%d %H:%M')}

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
            elif candidate.hai_type == HAIType.VAE:
                # VAE-specific email
                vae_data = getattr(candidate, "_vae_data", None)
                subject = f"New VAE Candidate: {candidate.patient.mrn} - VAC Detected"
                if vae_data:
                    body = f"""
New VAE Candidate Detected (Ventilator-Associated Condition)

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

Ventilator Information:
  - Intubation Date: {vae_data.episode.intubation_date.strftime('%Y-%m-%d') if vae_data.episode and vae_data.episode.intubation_date else 'Unknown'}
  - Ventilator Days: {vae_data.episode.get_ventilator_days() if vae_data.episode else 'Unknown'}

VAC Details:
  - VAC Onset Date: {vae_data.vac_onset_date.strftime('%Y-%m-%d') if vae_data.vac_onset_date else 'Unknown'}
  - Baseline Period: {vae_data.baseline_start_date.strftime('%Y-%m-%d') if vae_data.baseline_start_date else 'Unknown'} to {vae_data.baseline_end_date.strftime('%Y-%m-%d') if vae_data.baseline_end_date else 'Unknown'}
  - Baseline FiO2: {vae_data.baseline_min_fio2}%
  - Baseline PEEP: {vae_data.baseline_min_peep} cmH2O
  - FiO2 Increase: +{vae_data.fio2_increase:.0f}% (threshold: 20%)
  - PEEP Increase: +{vae_data.peep_increase:.0f} cmH2O (threshold: 3)

IVAC/VAP classification requires clinical review.

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
                else:
                    body = f"""
New VAE Candidate Detected (Ventilator-Associated Condition)

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

A Ventilator-Associated Condition (VAC) was detected. IVAC/VAP classification requires clinical review.

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
            elif candidate.hai_type == HAIType.CAUTI:
                # CAUTI-specific email
                cauti_data = getattr(candidate, "_cauti_data", None)
                subject = f"New CAUTI Candidate: {candidate.patient.mrn} - {candidate.culture.organism or 'Organism Pending'}"
                if cauti_data:
                    body = f"""
New CAUTI Candidate Detected (Catheter-Associated Urinary Tract Infection)

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}
  - Age: {cauti_data.patient_age or 'Unknown'} years

Catheter Information:
  - Catheter Type: {cauti_data.catheter_episode.catheter_type if cauti_data.catheter_episode else 'Unknown'}
  - Catheter Days at Culture: {cauti_data.catheter_days}
  - Insertion Date: {cauti_data.catheter_episode.insertion_date.strftime('%Y-%m-%d') if cauti_data.catheter_episode and cauti_data.catheter_episode.insertion_date else 'Unknown'}

Urine Culture:
  - Organism: {candidate.culture.organism or 'Pending identification'}
  - CFU/mL: {cauti_data.culture_cfu_ml:,} if cauti_data.culture_cfu_ml else 'Not specified'
  - Collection Date: {candidate.culture.collection_date.strftime('%Y-%m-%d %H:%M')}

NHSN CAUTI Criteria:
  - Catheter >2 days: {'Yes' if cauti_data.catheter_days > 2 else 'No'} ({cauti_data.catheter_days} days)
  - CFU threshold met: {'Yes' if cauti_data.culture_cfu_ml and cauti_data.culture_cfu_ml >= 100000 else 'Check required'}

Symptom documentation requires clinical review.

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
                else:
                    body = f"""
New CAUTI Candidate Detected (Catheter-Associated Urinary Tract Infection)

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

Urine Culture:
  - Organism: {candidate.culture.organism or 'Pending identification'}
  - Collection Date: {candidate.culture.collection_date.strftime('%Y-%m-%d %H:%M')}

Catheter Information:
  - Catheter Days: {candidate.device_days_at_culture or 'Unknown'}

Symptom documentation requires clinical review.

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
            elif candidate.hai_type == HAIType.CDI:
                # CDI-specific email
                cdi_data = getattr(candidate, "_cdi_data", None)
                subject = f"New CDI Candidate: {candidate.patient.mrn} - {cdi_data.onset_type.upper() if cdi_data else 'C. diff Positive'}"
                if cdi_data:
                    # Onset type display
                    onset_display = {
                        "ho": "Healthcare-Facility Onset (HO-CDI)",
                        "co": "Community Onset (CO-CDI)",
                        "co_hcfa": "Community Onset, Healthcare Facility-Associated (CO-HCFA)",
                    }
                    onset = onset_display.get(cdi_data.onset_type, cdi_data.onset_type.upper())

                    recurrence_status = "INCIDENT"
                    if cdi_data.is_recurrent:
                        recurrence_status = f"RECURRENT ({cdi_data.days_since_last_cdi} days since last event)"
                    elif cdi_data.is_duplicate:
                        recurrence_status = "DUPLICATE (within 14-day window, not reportable)"

                    body = f"""
New CDI Candidate Detected (Clostridioides difficile Infection)

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

C. difficile Test:
  - Test Type: {cdi_data.test_result.test_type}
  - Result: {cdi_data.test_result.result.upper()}
  - Test Date: {cdi_data.test_result.test_date.strftime('%Y-%m-%d %H:%M')}

Classification:
  - Specimen Day: {cdi_data.specimen_day} (Day 1 = admission)
  - Onset Type: {onset}
  - Recurrence Status: {recurrence_status}

Admission Information:
  - Admission Date: {cdi_data.admission_date.strftime('%Y-%m-%d') if cdi_data.admission_date else 'Unknown'}

NHSN CDI LabID Criteria:
  - Positive toxin/PCR test: Yes
  - Onset classification: {onset}
  - Specimen day > 3: {'Yes (HO-CDI)' if cdi_data.specimen_day > 3 else 'No (CO-CDI)'}

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
                else:
                    body = f"""
New CDI Candidate Detected (Clostridioides difficile Infection)

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

C. difficile Test:
  - Result: Positive
  - Test Date: {candidate.culture.collection_date.strftime('%Y-%m-%d %H:%M')}

This candidate requires IP review to determine onset classification.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""
            else:
                # CLABSI and other HAI types
                subject = f"New {hai_type_name} Candidate: {candidate.patient.mrn} - {candidate.culture.organism or 'Organism Pending'}"
                body = f"""
New {hai_type_name} Candidate Detected

Patient Information:
  - Name: {candidate.patient.name or 'Unknown'}
  - MRN: {candidate.patient.mrn}
  - Location: {candidate.patient.location or 'Unknown'}

Culture Information:
  - Organism: {candidate.culture.organism or 'Pending identification'}
  - Collection Date: {candidate.culture.collection_date.strftime('%Y-%m-%d %H:%M')}

Central Line Information:
  - Device Type: {candidate.device_info.device_type if candidate.device_info else 'Unknown'}
  - Device Days at Culture: {candidate.device_days_at_culture}
  - Insertion Date: {candidate.device_info.insertion_date.strftime('%Y-%m-%d') if candidate.device_info and candidate.device_info.insertion_date else 'Unknown'}

This candidate requires IP review.

Review in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""

            # Parse recipient list (can be comma-separated)
            recipients = [
                email.strip()
                for email in Config.NHSN_NOTIFICATION_EMAIL.split(',')
                if email.strip()
            ]

            msg = MIMEMultipart()
            msg['From'] = f"{Config.SENDER_NAME} <{Config.SENDER_EMAIL}>"
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
                server.starttls()
                # Login if credentials provided
                if Config.SMTP_USERNAME and Config.SMTP_PASSWORD:
                    server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
                server.sendmail(Config.SENDER_EMAIL, recipients, msg.as_string())

            logger.info(f"Sent email notification for candidate {candidate.id} to {recipients}")

        except Exception as e:
            logger.warning(f"Failed to send email notification: {e}")

    def run_continuous(self, interval_seconds: int | None = None) -> None:
        """Run continuous monitoring loop.

        Args:
            interval_seconds: Seconds between checks. Uses config if None.
        """
        interval = interval_seconds or Config.POLL_INTERVAL
        logger.info(f"Starting continuous monitoring (interval: {interval}s)")

        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in monitoring cycle: {e}", exc_info=True)

            logger.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)

    def get_pending_candidates(
        self, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get candidates pending classification.

        Args:
            hai_type: Filter by HAI type. All types if None.

        Returns:
            List of pending candidates.
        """
        return self.db.get_candidates_by_status(CandidateStatus.PENDING, hai_type)

    def get_candidates_for_review(
        self, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get candidates pending IP review.

        Args:
            hai_type: Filter by HAI type. All types if None.

        Returns:
            List of candidates pending review.
        """
        return self.db.get_candidates_by_status(CandidateStatus.PENDING_REVIEW, hai_type)

    def get_recent_candidates(
        self, limit: int = 100, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get recent candidates for dashboard display.

        Args:
            limit: Maximum number to return.
            hai_type: Filter by HAI type. All types if None.

        Returns:
            List of recent candidates.
        """
        return self.db.get_recent_candidates(limit, hai_type)

    def get_stats(self) -> dict:
        """Get summary statistics for dashboard."""
        return self.db.get_summary_stats()

    def classify_pending(
        self,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Classify pending candidates using LLM extraction + rules engine.

        Args:
            limit: Maximum number of candidates to classify. None for all.
            dry_run: If True, don't save classifications.

        Returns:
            Dict with classification summary.
        """
        logger.info("Starting classification of pending candidates...")

        # Get pending candidates
        candidates = self.db.get_candidates_by_status(CandidateStatus.PENDING)

        if limit:
            candidates = candidates[:limit]

        if not candidates:
            logger.info("No pending candidates to classify")
            return {"classified": 0, "errors": 0}

        logger.info(f"Found {len(candidates)} pending candidates")

        classified_count = 0
        error_count = 0
        results = {
            "classified": 0,
            "errors": 0,
            "by_decision": {},
            "details": [],
        }

        for candidate in candidates:
            try:
                # Retrieve clinical notes for this patient
                notes = self.note_retriever.get_notes_for_candidate(candidate)

                if not notes:
                    logger.warning(
                        f"No notes found for candidate {candidate.id} "
                        f"(patient {candidate.patient.mrn})"
                    )
                    # Still run classification - will get low confidence
                    notes = []

                logger.info(
                    f"Classifying {candidate.hai_type.value} candidate {candidate.id}: "
                    f"patient={candidate.patient.mrn}, "
                    f"organism={candidate.culture.organism}, "
                    f"notes={len(notes)}"
                )

                # Get the appropriate classifier for this HAI type
                classifier = self.get_classifier(candidate.hai_type)

                # Run classification
                classification = classifier.classify(candidate, notes)

                if dry_run:
                    logger.info(
                        f"[DRY RUN] Would classify {candidate.id} as "
                        f"{classification.decision.value} "
                        f"(confidence={classification.confidence:.2f})"
                    )
                else:
                    # Save classification
                    self.db.save_classification(classification)

                    # Update candidate status based on decision
                    new_status = self._determine_status(classification)
                    self.db.update_candidate_status(candidate.id, new_status)

                    # Create review entry so it appears in pending reviews queue
                    self._create_review_entry(candidate, classification)

                    logger.info(
                        f"Classified {candidate.id} as {classification.decision.value} "
                        f"(confidence={classification.confidence:.2f}, status={new_status.value})"
                    )

                # Track results
                decision = classification.decision.value
                results["by_decision"][decision] = results["by_decision"].get(decision, 0) + 1
                results["details"].append({
                    "candidate_id": candidate.id,
                    "patient_mrn": candidate.patient.mrn,
                    "organism": candidate.culture.organism,
                    "decision": decision,
                    "confidence": classification.confidence,
                })

                classified_count += 1

            except Exception as e:
                logger.error(
                    f"Error classifying candidate {candidate.id}: {e}",
                    exc_info=True
                )
                error_count += 1

        results["classified"] = classified_count
        results["errors"] = error_count

        logger.info(
            f"Classification complete: {classified_count} classified, "
            f"{error_count} errors"
        )

        return results

    def _determine_status(self, classification) -> CandidateStatus:
        """Determine candidate status based on classification result.

        All classified candidates go to pending_review for IP final decision.
        The LLM provides classification and confidence, but IP always reviews.
        """
        # All cases go to pending_review - IP makes the final call
        return CandidateStatus.PENDING_REVIEW

    def _create_review_entry(self, candidate: HAICandidate, classification) -> None:
        """Create a review queue entry for IP review.

        Args:
            candidate: The HAI candidate
            classification: The LLM classification result
        """
        import uuid
        from datetime import datetime
        from .models import Review, ReviewQueueType

        review = Review(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            classification_id=classification.id,
            queue_type=ReviewQueueType.IP_REVIEW,
            reviewed=False,
            created_at=datetime.now(),
        )
        self.db.save_review_object(review)
        logger.debug(f"Created review entry {review.id} for candidate {candidate.id}")

    def run_full_pipeline(self, dry_run: bool = False) -> dict:
        """Run full pipeline: detection + classification.

        Args:
            dry_run: If True, don't persist anything.

        Returns:
            Dict with pipeline results.
        """
        results = {
            "detection": {},
            "classification": {},
        }

        # Step 1: Detection
        logger.info("=== Step 1: Detection ===")
        detection_count = self.run_once(dry_run=dry_run)
        results["detection"]["new_candidates"] = detection_count

        # Step 2: Classification (only if not dry run for detection)
        if not dry_run:
            logger.info("=== Step 2: Classification ===")
            classification_results = self.classify_pending(dry_run=dry_run)
            results["classification"] = classification_results

        return results
