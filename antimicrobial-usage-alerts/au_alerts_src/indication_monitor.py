"""Antibiotic indication monitor.

Monitors new antibiotic orders for documented indications using ICD-10
classification (Chua et al.) and LLM extraction from clinical notes.
Only "Never appropriate" (N) classifications generate ASP alerts.
"""

import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

from .config import config
from .fhir_client import FHIRClient, get_fhir_client
from .models import (
    AlertSeverity,
    IndicationAssessment,
    IndicationCandidate,
    IndicationExtraction,
    MedicationOrder,
    Patient,
)
from .indication_db import IndicationDatabase

from common.alert_store import AlertStore, AlertType, StoredAlert

# Import the classifier from abx-indications module
# Add path if needed
ABX_INDICATIONS_PATH = Path(__file__).parent.parent.parent / "abx-indications"
if str(ABX_INDICATIONS_PATH) not in sys.path:
    sys.path.insert(0, str(ABX_INDICATIONS_PATH))

try:
    from pediatric_abx_indications import AntibioticIndicationClassifier, IndicationCategory
except ImportError:
    AntibioticIndicationClassifier = None
    IndicationCategory = None

logger = logging.getLogger(__name__)


class IndicationMonitor:
    """Monitor antibiotic orders for documented indications."""

    def __init__(
        self,
        fhir_client: FHIRClient | None = None,
        classifier: "AntibioticIndicationClassifier | None" = None,
        llm_extractor=None,
        alert_store: AlertStore | None = None,
        db: IndicationDatabase | None = None,
    ):
        """Initialize the indication monitor.

        Args:
            fhir_client: FHIR client for queries. Uses factory default if None.
            classifier: Antibiotic indication classifier. Loads from CSV if None.
            llm_extractor: LLM extractor for note analysis. Optional.
            alert_store: Alert store for persisting alerts. Uses default if None.
            db: Database for indication tracking. Uses default if None.
        """
        self.fhir_client = fhir_client or get_fhir_client()
        self.classifier = classifier or self._load_classifier()
        self.llm_extractor = llm_extractor
        self.alert_store = alert_store or AlertStore(db_path=config.ALERT_DB_PATH)
        self.db = db or IndicationDatabase()
        self._alerted_orders: set[str] = set()  # In-memory cache

    def _load_classifier(self) -> "AntibioticIndicationClassifier | None":
        """Load the antibiotic indication classifier from CSV."""
        if AntibioticIndicationClassifier is None:
            logger.error(
                "AntibioticIndicationClassifier not available. "
                "Make sure abx-indications module is installed."
            )
            return None

        csv_path = Path(config.CHUA_CSV_PATH).expanduser()
        if not csv_path.exists():
            logger.error(f"Chua classification CSV not found: {csv_path}")
            return None

        try:
            return AntibioticIndicationClassifier(str(csv_path))
        except Exception as e:
            logger.error(f"Failed to load classifier: {e}")
            return None

    def check_new_orders(self, since_hours: int = 24) -> list[IndicationAssessment]:
        """Check new antibiotic orders for indications.

        Args:
            since_hours: How far back to look for new orders.

        Returns:
            List of IndicationAssessment objects.
        """
        if self.classifier is None:
            logger.error("Classifier not available, cannot check orders")
            return []

        # Get new antibiotic orders from past N hours
        rxnorm_codes = list(config.INDICATION_MONITORED_MEDICATIONS.keys())
        orders = self.fhir_client.get_recent_medication_requests(
            since_hours=since_hours,
            rxnorm_codes=rxnorm_codes,
        )
        logger.info(f"Found {len(orders)} antibiotic orders in past {since_hours}h")

        assessments = []
        for order in orders:
            assessment = self._assess_order(order)
            if assessment:
                assessments.append(assessment)

        # Log summary
        n_count = sum(1 for a in assessments if a.candidate.final_classification == "N")
        logger.info(
            f"Assessed {len(assessments)} orders: {n_count} with no documented indication"
        )

        return assessments

    def check_new_alerts(self) -> list[tuple[IndicationAssessment, str]]:
        """Check for new alerts (orders not previously alerted).

        Returns:
            List of (IndicationAssessment, alert_id) tuples for new alerts.
        """
        assessments = self.check_new_orders()

        new_alerts = []
        for assessment in assessments:
            if not assessment.requires_alert:
                continue

            order_id = assessment.candidate.medication.fhir_id

            # Check persistent store first (include resolved to prevent re-alerting)
            if self.alert_store.check_if_alerted(
                AlertType.ABX_NO_INDICATION,
                order_id,
                include_resolved=True,
            ):
                continue

            # Check in-memory cache
            if order_id in self._alerted_orders:
                continue

            # Create alert in store
            try:
                stored_alert = self._create_alert(assessment)
                new_alerts.append((assessment, stored_alert.id))
                self._alerted_orders.add(order_id)

                # Update candidate with alert ID
                assessment.candidate.alert_id = stored_alert.id
                assessment.candidate.status = "alerted"
                self.db.save_candidate(assessment.candidate)

            except Exception as e:
                logger.error(f"Failed to save alert for order {order_id}: {e}")
                new_alerts.append((assessment, None))
                self._alerted_orders.add(order_id)

        logger.info(f"Found {len(new_alerts)} new alerts")
        return new_alerts

    def _assess_order(self, order: MedicationOrder) -> IndicationAssessment | None:
        """Assess a single medication order.

        Clinical notes take priority over ICD-10 codes because:
        - ICD-10 codes may be stale (from previous encounters)
        - Notes reflect real-time clinical reasoning
        - Notes capture nuance that codes cannot

        Args:
            order: The medication order to assess.

        Returns:
            IndicationAssessment or None if assessment fails.
        """
        # Get patient info
        patient = self.fhir_client.get_patient(order.patient_id)
        if not patient:
            logger.warning(f"Could not find patient {order.patient_id}")
            patient = Patient(
                fhir_id=order.patient_id,
                mrn="Unknown",
                name="Unknown Patient",
            )

        # Get patient's ICD-10 codes
        icd10_codes = self.fhir_client.get_patient_conditions(order.patient_id)
        logger.debug(f"Patient {patient.mrn}: {len(icd10_codes)} ICD-10 codes")

        # Classify with Chua (ICD-10 based)
        classification_result = self.classifier.classify(
            icd10_codes=icd10_codes,
            cpt_codes=[],  # Could add procedure codes if available
            fever_present=False,  # Could detect from vital signs
        )

        icd10_classification = classification_result.overall_category.value
        icd10_primary = classification_result.primary_indication

        # Start with ICD-10 classification as baseline
        final_classification = icd10_classification
        classification_source = "icd10"

        llm_extracted = None
        llm_classification = None

        # ALWAYS attempt LLM extraction if extractor available
        # Notes take priority over ICD-10 codes
        if self.llm_extractor:
            logger.debug(f"Attempting LLM extraction for {order.fhir_id}")
            try:
                extraction = self._extract_from_notes(order, patient)
                if extraction:
                    llm_extracted = "; ".join(extraction.found_indications) if extraction.found_indications else None

                    # Determine LLM classification based on extraction
                    llm_classification = self._classify_from_extraction(extraction, order.medication_name)

                    if llm_classification:
                        # Notes override ICD-10
                        if llm_classification != icd10_classification:
                            logger.info(
                                f"Note overrides ICD-10 for {order.medication_name}: "
                                f"{icd10_classification} -> {llm_classification} "
                                f"(confidence: {extraction.confidence})"
                            )
                        final_classification = llm_classification
                        classification_source = "llm"

            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}")

        # Create candidate
        candidate = IndicationCandidate(
            id=str(uuid.uuid4()),
            patient=patient,
            medication=order,
            icd10_codes=icd10_codes,
            icd10_classification=icd10_classification,
            icd10_primary_indication=icd10_primary,
            llm_extracted_indication=llm_extracted,
            llm_classification=llm_classification,
            final_classification=final_classification,
            classification_source=classification_source,
            status="pending",
        )

        # Save candidate to database
        self.db.save_candidate(candidate)

        # Determine if alert needed (only for N classifications)
        requires_alert = final_classification == "N"

        # Generate recommendation
        recommendation = self._generate_recommendation(
            order, icd10_classification, icd10_primary, classification_result.recommendations
        )

        # Determine severity
        severity = AlertSeverity.WARNING
        if icd10_classification == "N" and not icd10_codes:
            # No ICD-10 codes at all - more concerning
            severity = AlertSeverity.CRITICAL

        return IndicationAssessment(
            candidate=candidate,
            requires_alert=requires_alert,
            recommendation=recommendation,
            severity=severity,
        )

    def _classify_from_extraction(
        self,
        extraction: IndicationExtraction,
        medication_name: str,
    ) -> str | None:
        """Determine classification based on LLM extraction.

        Args:
            extraction: The LLM extraction result.
            medication_name: Name of the antibiotic.

        Returns:
            Classification string (A, S, N) or None if inconclusive.
        """
        if not extraction:
            return None

        # Check for explicit inappropriate use signals
        inappropriate_signals = [
            "viral",
            "not indicated",
            "no indication",
            "inappropriate",
            "likely viral",
            "viral etiology",
            "antibiotics not indicated",
            "no bacterial",
            "no clear indication",
        ]

        # Check for appropriate use signals
        appropriate_signals = [
            "pneumonia",
            "bacterial pneumonia",
            "sepsis",
            "bacterial sepsis",
            "urinary tract infection",
            "uti",
            "pyelonephritis",
            "cellulitis",
            "meningitis",
            "bacteremia",
            "osteomyelitis",
            "abscess",
            "peritonitis",
            "endocarditis",
        ]

        # Combine indications and quotes for analysis
        all_text = " ".join(extraction.found_indications + extraction.supporting_quotes).lower()

        # Check for inappropriate signals first (they indicate explicit concern)
        for signal in inappropriate_signals:
            if signal in all_text:
                logger.debug(f"Found inappropriate signal in notes: '{signal}'")
                return "N"

        # Check for appropriate signals
        for signal in appropriate_signals:
            if signal in all_text:
                logger.debug(f"Found appropriate signal in notes: '{signal}'")
                # HIGH confidence = Always, MEDIUM = Sometimes
                if extraction.confidence == "HIGH":
                    return "A"
                elif extraction.confidence == "MEDIUM":
                    return "S"
                else:
                    return "S"  # Default to Sometimes if low confidence

        # If indications found but not matching our signals, classify based on confidence
        if extraction.found_indications:
            if extraction.confidence == "HIGH":
                return "A"
            elif extraction.confidence == "MEDIUM":
                return "S"

        # Inconclusive - return None to fall back to ICD-10
        return None

    def _extract_from_notes(
        self, order: MedicationOrder, patient: Patient
    ) -> IndicationExtraction | None:
        """Extract indication from clinical notes using LLM.

        Args:
            order: The medication order.
            patient: The patient.

        Returns:
            IndicationExtraction or None.
        """
        if not self.llm_extractor:
            return None

        # Get recent notes
        notes = self.fhir_client.get_recent_notes(
            patient_id=order.patient_id,
            since_hours=48,
        )

        if not notes:
            logger.debug(f"No notes found for patient {patient.mrn}")
            return None

        # Extract text from notes
        note_texts = [n.get("text", "") for n in notes if n.get("text")]
        if not note_texts:
            return None

        # Call LLM extractor
        return self.llm_extractor.extract(
            notes=note_texts,
            medication=order.medication_name,
        )

    def _generate_recommendation(
        self,
        order: MedicationOrder,
        classification: str,
        primary_indication: str | None,
        classifier_recommendations: list[str],
    ) -> str:
        """Generate recommendation based on classification.

        Args:
            order: The medication order.
            classification: The classification (A, S, N, etc.).
            primary_indication: Primary indication if found.
            classifier_recommendations: Recommendations from classifier.

        Returns:
            Recommendation string.
        """
        med_name = order.medication_name

        if classification == "N":
            base = f"No documented indication for {med_name}. "
            if classifier_recommendations:
                return base + classifier_recommendations[0]
            return base + "Consider discontinuation or document indication."

        elif classification == "U":
            return (
                f"Unable to classify indication for {med_name}. "
                "Manual review required - diagnosis codes not found in classification."
            )

        elif classification == "S":
            if primary_indication:
                return (
                    f"{med_name} may be appropriate for {primary_indication}. "
                    "Clinical judgment needed to confirm indication."
                )
            return f"Review {med_name} indication - may or may not be appropriate."

        elif classification in ("A", "P", "FN"):
            if primary_indication:
                return f"{med_name} indicated for {primary_indication}."
            return f"{med_name} has documented indication."

        return f"Unable to assess indication for {med_name}."

    def _create_alert(self, assessment: IndicationAssessment) -> StoredAlert:
        """Create an alert in the alert store.

        Args:
            assessment: The indication assessment.

        Returns:
            The stored alert.
        """
        candidate = assessment.candidate
        patient = candidate.patient
        medication = candidate.medication

        content = {
            "medication_name": medication.medication_name,
            "medication_code": f"RxNorm:{medication.rxnorm_code}" if medication.rxnorm_code else None,
            "order_date": medication.start_date.isoformat() if medication.start_date else None,
            # ICD-10 track
            "icd10_codes": candidate.icd10_codes,
            "icd10_classification": candidate.icd10_classification,
            "icd10_primary_indication": candidate.icd10_primary_indication,
            # LLM track
            "llm_attempted": self.llm_extractor is not None,
            "llm_found_indication": bool(candidate.llm_extracted_indication),
            "llm_extracted_text": candidate.llm_extracted_indication,
            # Final
            "final_classification": candidate.final_classification,
            "recommendation": assessment.recommendation,
            "candidate_id": candidate.id,
            "location": patient.location,
            "department": patient.department,
        }

        return self.alert_store.save_alert(
            alert_type=AlertType.ABX_NO_INDICATION,
            source_id=medication.fhir_id,
            severity=assessment.severity.value,
            patient_id=patient.fhir_id,
            patient_mrn=patient.mrn,
            patient_name=patient.name,
            title=f"No Indication: {medication.medication_name}",
            summary=f"No documented indication for {medication.medication_name}",
            content=content,
        )

    def mark_alert_sent(self, alert_id: str) -> bool:
        """Mark an alert as successfully sent.

        Args:
            alert_id: The alert ID.

        Returns:
            True if successful.
        """
        if alert_id:
            return self.alert_store.mark_sent(alert_id)
        return False

    def clear_alert_history(self) -> None:
        """Clear the set of alerted orders (useful for testing)."""
        self._alerted_orders.clear()

    def alert_pending_n_candidates(self) -> list[tuple[str, str]]:
        """Create alerts for pending N candidates that were missed.

        This catches candidates that were classified as N but never alerted,
        possibly due to incomplete processing.

        Returns:
            List of (candidate_id, alert_id) tuples for newly alerted candidates.
        """
        # Get pending candidates with N classification
        pending_n = self.db.list_candidates(status="pending", classification="N")
        logger.info(f"Found {len(pending_n)} pending N candidates to check")

        newly_alerted = []
        for candidate in pending_n:
            order_id = candidate.medication.fhir_id

            # Check if already alerted (by source_id)
            if self.alert_store.check_if_alerted(
                AlertType.ABX_NO_INDICATION,
                order_id,
                include_resolved=True,
            ):
                # Already alerted - just update status
                candidate.status = "alerted"
                # Try to find the existing alert ID
                existing = self.alert_store.get_alert_by_source(
                    AlertType.ABX_NO_INDICATION, order_id
                )
                if existing:
                    candidate.alert_id = existing.id
                self.db.save_candidate(candidate)
                logger.info(f"Updated status for {candidate.patient.mrn} (already alerted)")
                continue

            # Create new alert
            try:
                # Build assessment for alert creation
                recommendation = self._generate_recommendation(
                    candidate.medication,
                    candidate.final_classification,
                    candidate.icd10_primary_indication,
                    [],
                )

                assessment = IndicationAssessment(
                    candidate=candidate,
                    requires_alert=True,
                    recommendation=recommendation,
                    severity=AlertSeverity.WARNING,
                )

                stored_alert = self._create_alert(assessment)
                candidate.alert_id = stored_alert.id
                candidate.status = "alerted"
                self.db.save_candidate(candidate)

                newly_alerted.append((candidate.id, stored_alert.id))
                logger.info(
                    f"Created alert for {candidate.patient.mrn} - "
                    f"{candidate.medication.medication_name}"
                )

            except Exception as e:
                logger.error(f"Failed to create alert for {candidate.id}: {e}")

        logger.info(f"Newly alerted: {len(newly_alerted)} candidates")
        return newly_alerted


def run_indication_monitor(since_hours: int = 24, dry_run: bool = False) -> int:
    """Convenience function to run the indication monitor.

    Args:
        since_hours: How far back to look for orders.
        dry_run: If True, don't create alerts.

    Returns:
        Number of new alerts found.
    """
    monitor = IndicationMonitor()

    # First, fix any pending N candidates that were missed
    if not dry_run:
        monitor.alert_pending_n_candidates()

    # Then check for new alerts
    alert_tuples = monitor.check_new_alerts()

    if dry_run:
        for assessment, alert_id in alert_tuples:
            logger.info(
                f"[DRY RUN] Would alert: {assessment.candidate.patient.name} - "
                f"{assessment.candidate.medication.medication_name} "
                f"(classification: {assessment.candidate.final_classification})"
            )
    else:
        for assessment, alert_id in alert_tuples:
            if alert_id:
                monitor.mark_alert_sent(alert_id)

    return len(alert_tuples)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("Running antibiotic indication monitor...")
    count = run_indication_monitor(dry_run=True)
    print(f"Found {count} orders requiring attention")
