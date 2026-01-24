"""Guideline Adherence Monitor - Real-time monitoring for bundle compliance.

Monitors active patient episodes for guideline bundle adherence and
generates alerts when elements are not met within their time windows.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

# Add paths for imports
COMMON_PATH = Path(__file__).parent.parent.parent / "common"
GUIDELINE_PATH = Path(__file__).parent.parent
if str(COMMON_PATH) not in sys.path:
    sys.path.insert(0, str(COMMON_PATH))
if str(GUIDELINE_PATH) not in sys.path:
    sys.path.insert(0, str(GUIDELINE_PATH))

from alert_store import AlertStore, AlertType

from guideline_adherence import (
    BundleElement,
    GuidelineBundle,
    GUIDELINE_BUNDLES,
    SEPSIS_BUNDLE,
)

from .config import config
from .models import (
    AlertContent,
    ElementCheckResult,
    ElementCheckStatus,
    EpisodeStatus,
    GuidelineMonitorResult,
)
from .fhir_client import GuidelineFHIRClient, get_fhir_client
from .adherence_db import AdherenceDatabase
from .checkers import LabChecker, MedicationChecker, NoteChecker, FebrileInfantChecker

logger = logging.getLogger(__name__)


class GuidelineAdherenceMonitor:
    """Real-time monitoring for guideline bundle adherence."""

    def __init__(
        self,
        fhir_client: GuidelineFHIRClient | None = None,
        alert_store: AlertStore | None = None,
        db: AdherenceDatabase | None = None,
        bundles: dict[str, GuidelineBundle] | None = None,
    ):
        """Initialize the guideline adherence monitor.

        Args:
            fhir_client: FHIR client for queries.
            alert_store: Alert store for persisting alerts.
            db: Database for tracking adherence.
            bundles: Guideline bundles to monitor.
        """
        self.fhir_client = fhir_client or get_fhir_client()
        self.alert_store = alert_store or AlertStore(db_path=config.ALERT_DB_PATH)
        self.db = db or AdherenceDatabase()
        self.bundles = bundles or GUIDELINE_BUNDLES

        # Initialize checkers
        self.lab_checker = LabChecker(self.fhir_client)
        self.med_checker = MedicationChecker(self.fhir_client)
        self.note_checker = NoteChecker(self.fhir_client)
        self.febrile_infant_checker = FebrileInfantChecker(self.fhir_client)

        # Track alerted elements to prevent duplicates
        self._alerted_elements: set[str] = set()

    def check_active_episodes(
        self,
        bundle_id: str | None = None,
    ) -> list[GuidelineMonitorResult]:
        """Find and check all active episodes.

        Args:
            bundle_id: Optional filter to specific bundle.

        Returns:
            List of monitoring results.
        """
        results = []

        # Determine which bundles to check
        if bundle_id:
            bundles_to_check = {bundle_id: self.bundles[bundle_id]}
        else:
            bundles_to_check = {
                bid: self.bundles[bid]
                for bid in config.ENABLED_BUNDLES
                if bid in self.bundles
            }

        for bid, bundle in bundles_to_check.items():
            logger.info(f"Checking bundle: {bundle.name} ({bid})")

            # Find patients with applicable conditions
            if bid.startswith("sepsis"):
                patients = self._find_sepsis_patients()
            elif bid.startswith("febrile_infant"):
                patients = self._find_febrile_infant_patients()
            else:
                patients = self._find_patients_for_bundle(bundle)

            logger.info(f"Found {len(patients)} patients for {bundle.name}")

            for patient_info in patients:
                result = self._check_patient_episode(patient_info, bundle)
                if result:
                    results.append(result)

                    # Save to database
                    episode_id = self.db.create_or_update_episode(result)
                    self.db.save_element_results(episode_id, result.element_results)

        return results

    def check_new_deviations(
        self,
        bundle_id: str | None = None,
    ) -> list[tuple[GuidelineMonitorResult, str, str]]:
        """Check for new NOT_MET elements and create alerts.

        Args:
            bundle_id: Optional filter to specific bundle.

        Returns:
            List of (result, element_id, alert_id) tuples for new alerts.
        """
        results = self.check_active_episodes(bundle_id)
        new_alerts = []

        for result in results:
            # Check for NOT_MET elements
            for element_result in result.get_not_met_elements():
                # Create unique key for this deviation
                deviation_key = f"{result.patient_id}_{result.bundle_id}_{element_result.element_id}"
                episode_id = f"{result.patient_id}_{result.encounter_id}_{result.bundle_id}"

                # Check if already alerted (in-memory)
                if deviation_key in self._alerted_elements:
                    continue

                # Check if already alerted (database)
                if self.db.has_deviation_alert(episode_id, element_result.element_id):
                    self._alerted_elements.add(deviation_key)
                    continue

                # Check if already alerted (alert store - include resolved)
                source_id = f"{episode_id}_{element_result.element_id}"
                if self.alert_store.check_if_alerted(
                    AlertType.GUIDELINE_DEVIATION,
                    source_id,
                    include_resolved=True,
                ):
                    self._alerted_elements.add(deviation_key)
                    continue

                # Create alert
                try:
                    alert_id = self._create_deviation_alert(result, element_result)
                    new_alerts.append((result, element_result.element_id, alert_id))

                    # Record in database and cache
                    self.db.record_deviation_alert(episode_id, element_result.element_id, alert_id)
                    self._alerted_elements.add(deviation_key)

                    logger.info(
                        f"Created alert for {result.patient_name}: "
                        f"{element_result.element_name} not met"
                    )

                except Exception as e:
                    logger.error(f"Failed to create alert: {e}")

        logger.info(f"Found {len(new_alerts)} new guideline deviations")
        return new_alerts

    def _find_sepsis_patients(self) -> list[dict]:
        """Find patients with active sepsis diagnoses.

        Returns:
            List of patient info dicts.
        """
        return self.fhir_client.get_sepsis_patients()

    def _find_febrile_infant_patients(self) -> list[dict]:
        """Find patients matching febrile infant criteria.

        Criteria (AAP 2021):
        - Age 8-60 days
        - Fever (temperature >= 38.0C)
        - Well-appearing

        Returns:
            List of patient info dicts with age_days included.
        """
        # Query for fever diagnoses in young infants
        # In real implementation, would query FHIR for:
        # - Patients with Condition R50.x AND age <= 60 days
        # - Or patients with vital signs showing temp >= 38.0C

        patients = self.fhir_client.get_patients_by_condition(
            icd10_prefixes=config.FEBRILE_INFANT_ICD10_PREFIXES,
            max_age_days=60,
        )

        # Filter to appropriate age range and calculate age
        result = []
        for patient_info in patients:
            age_days = patient_info.get("age_days")
            if age_days is None:
                # Calculate from birth date
                patient = self.fhir_client.get_patient(patient_info.get("patient_id"))
                if patient and patient.get("birth_date"):
                    onset_time = patient_info.get("onset_time") or datetime.now()
                    age_days = (onset_time.date() - patient["birth_date"]).days
                    patient_info["age_days"] = age_days

            # AAP guideline is for 8-60 days
            if age_days is not None and 8 <= age_days <= 60:
                result.append(patient_info)

        return result

    def _find_patients_for_bundle(self, bundle: GuidelineBundle) -> list[dict]:
        """Find patients with conditions matching a bundle.

        Args:
            bundle: The guideline bundle.

        Returns:
            List of patient info dicts.
        """
        # This would need to query by ICD-10 codes for the bundle
        # For now, return empty - focus on sepsis first
        logger.debug(f"Patient finding for {bundle.bundle_id} not yet implemented")
        return []

    def _check_patient_episode(
        self,
        patient_info: dict,
        bundle: GuidelineBundle,
    ) -> GuidelineMonitorResult | None:
        """Check a single patient episode against a bundle.

        Args:
            patient_info: Dict with patient_id, encounter_id, onset_time, age_days.
            bundle: The guideline bundle to check.

        Returns:
            GuidelineMonitorResult or None if unable to assess.
        """
        patient_id = patient_info.get("patient_id")
        encounter_id = patient_info.get("encounter_id", "")
        trigger_time = patient_info.get("onset_time") or datetime.now()
        age_days = patient_info.get("age_days")

        # Get patient details
        patient = self.fhir_client.get_patient(patient_id)
        if not patient:
            logger.warning(f"Could not find patient {patient_id}")
            patient = {
                "fhir_id": patient_id,
                "mrn": "Unknown",
                "name": "Unknown Patient",
            }

        # Check each element
        element_results = []
        initial_lactate = None  # Track for repeat lactate check

        # Use febrile infant checker for febrile infant bundles
        is_febrile_infant_bundle = bundle.bundle_id.startswith("febrile_infant")

        for element in bundle.elements:
            if is_febrile_infant_bundle:
                # Use specialized febrile infant checker
                result = self.febrile_infant_checker.check(
                    element, patient_id, trigger_time, age_days=age_days
                )
            else:
                result = self._check_element(element, patient_id, trigger_time)
            element_results.append(result)

            # Track initial lactate for repeat check
            if element.element_id == "sepsis_lactate" and result.value:
                try:
                    initial_lactate = float(result.value)
                except (ValueError, TypeError):
                    pass

        # Handle repeat lactate specially (sepsis bundle only)
        if not is_febrile_infant_bundle:
            for i, element in enumerate(bundle.elements):
                if element.element_id == "sepsis_repeat_lactate":
                    result = self.lab_checker.check_repeat_lactate(
                        element, patient_id, trigger_time, initial_lactate
                    )
                    element_results[i] = result

        # Determine episode status
        has_pending = any(r.status == ElementCheckStatus.PENDING for r in element_results)
        episode_status = EpisodeStatus.ACTIVE if has_pending else EpisodeStatus.COMPLETE

        return GuidelineMonitorResult(
            patient_id=patient_id,
            patient_mrn=patient.get("mrn", "Unknown"),
            patient_name=patient.get("name", "Unknown"),
            encounter_id=encounter_id,
            location=None,  # Could get from encounter
            bundle_id=bundle.bundle_id,
            bundle_name=bundle.name,
            trigger_time=trigger_time,
            assessment_time=datetime.now(),
            episode_status=episode_status,
            element_results=element_results,
        )

    def _check_element(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
    ) -> ElementCheckResult:
        """Check a single bundle element using appropriate checker.

        Args:
            element: The bundle element.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.

        Returns:
            ElementCheckResult.
        """
        data_source = element.data_source.lower()

        if data_source in ("lab_orders", "lab_results"):
            return self.lab_checker.check(element, patient_id, trigger_time)
        elif data_source in ("mar", "medication_orders"):
            return self.med_checker.check(element, patient_id, trigger_time)
        elif data_source in ("notes", "nursing_notes", "procedure_orders"):
            return self.note_checker.check(element, patient_id, trigger_time)
        else:
            # Default to pending if unknown data source
            logger.warning(f"Unknown data source for element {element.element_id}: {data_source}")
            return ElementCheckResult(
                element_id=element.element_id,
                element_name=element.name,
                status=ElementCheckStatus.PENDING,
                notes=f"Unknown data source: {data_source}",
            )

    def _create_deviation_alert(
        self,
        result: GuidelineMonitorResult,
        element: ElementCheckResult,
    ) -> str:
        """Create an alert for a guideline deviation.

        Args:
            result: The monitoring result.
            element: The element that was not met.

        Returns:
            Alert ID.
        """
        episode_id = f"{result.patient_id}_{result.encounter_id}_{result.bundle_id}"
        source_id = f"{episode_id}_{element.element_id}"

        # Build recommendation
        recommendation = self._generate_recommendation(result, element)

        content = AlertContent(
            bundle_id=result.bundle_id,
            bundle_name=result.bundle_name,
            trigger_time=result.trigger_time.isoformat() if result.trigger_time else "",
            element_id=element.element_id,
            element_name=element.element_name,
            time_window_hours=element.time_window_hours or 0,
            window_expired_at=element.deadline.isoformat() if element.deadline else "",
            status="not_met",
            recommendation=recommendation,
            overall_adherence_pct=result.overall_adherence_percentage,
            location=result.location,
            episode_id=episode_id,
        )

        stored_alert = self.alert_store.save_alert(
            alert_type=AlertType.GUIDELINE_DEVIATION,
            source_id=source_id,
            severity="warning",
            patient_id=result.patient_id,
            patient_mrn=result.patient_mrn,
            patient_name=result.patient_name,
            title=f"Guideline Deviation: {element.element_name}",
            summary=f"{result.bundle_name}: {element.element_name} not completed within required timeframe",
            content=content.to_dict(),
        )

        return stored_alert.id

    def _generate_recommendation(
        self,
        result: GuidelineMonitorResult,
        element: ElementCheckResult,
    ) -> str:
        """Generate recommendation text for a deviation.

        Args:
            result: The monitoring result.
            element: The element that was not met.

        Returns:
            Recommendation string.
        """
        bundle_name = result.bundle_name
        element_name = element.element_name

        # Element-specific recommendations
        recommendations = {
            # Sepsis bundle
            "sepsis_blood_cx": "Obtain blood cultures before antibiotics if not already collected.",
            "sepsis_lactate": "Obtain serum lactate to assess severity and guide resuscitation.",
            "sepsis_abx_1hr": "Administer broad-spectrum antibiotics immediately.",
            "sepsis_fluid_bolus": "Initiate fluid resuscitation (20 mL/kg crystalloid bolus).",
            "sepsis_repeat_lactate": "Repeat lactate to assess response to treatment.",
            "sepsis_reassess_48h": "Document antibiotic reassessment in clinical notes.",
            # Febrile infant bundle (AAP 2021)
            "fi_ua": "Obtain urinalysis via catheter or suprapubic aspiration.",
            "fi_blood_culture": "Obtain blood culture prior to antibiotic administration.",
            "fi_inflammatory_markers": "Obtain ANC and CRP. Consider procalcitonin if 29-60 days old.",
            "fi_procalcitonin": "Procalcitonin recommended for infants 29-60 days (most useful if fever >6h).",
            "fi_lp_8_21d": "LP required for all febrile infants 8-21 days per AAP 2021.",
            "fi_lp_22_28d_im_abnormal": "LP required for 22-28 day old with abnormal inflammatory markers.",
            "fi_abx_8_21d": "Start parenteral antibiotics for febrile infants 8-21 days.",
            "fi_abx_22_28d_im_abnormal": "Start parenteral antibiotics for abnormal inflammatory markers.",
            "fi_hsv_risk_assessment": "Document HSV risk assessment. Consider acyclovir if risk factors present.",
            "fi_admit_8_21d": "Hospital admission required for all febrile infants 8-21 days.",
            "fi_admit_22_28d_im_abnormal": "Hospital admission required for abnormal inflammatory markers.",
            "fi_safe_discharge_checklist": "Document follow-up plan, contact information, and return precautions.",
        }

        specific_rec = recommendations.get(element.element_id)
        if specific_rec:
            return f"{bundle_name}: {specific_rec}"

        # Generic recommendation
        return f"{bundle_name}: {element_name} not completed within required timeframe. Review and document completion or clinical rationale."

    def mark_alert_sent(self, alert_id: str) -> bool:
        """Mark an alert as sent.

        Args:
            alert_id: The alert ID.

        Returns:
            True if successful.
        """
        if alert_id:
            return self.alert_store.mark_sent(alert_id)
        return False

    def clear_alert_history(self) -> None:
        """Clear in-memory alert cache (for testing)."""
        self._alerted_elements.clear()


def run_guideline_monitor(
    bundle_id: str | None = None,
    dry_run: bool = False,
) -> int:
    """Convenience function to run the guideline adherence monitor.

    Args:
        bundle_id: Optional bundle to check.
        dry_run: If True, don't create alerts.

    Returns:
        Number of new deviations found.
    """
    monitor = GuidelineAdherenceMonitor()

    if dry_run:
        results = monitor.check_active_episodes(bundle_id)
        for result in results:
            logger.info(f"Patient: {result.patient_name} ({result.patient_mrn})")
            logger.info(f"  Bundle: {result.bundle_name}")
            logger.info(f"  Adherence: {result.adherence_percentage}%")
            for er in result.element_results:
                logger.info(f"    - {er.element_name}: {er.status.value}")
        return len(results)
    else:
        alerts = monitor.check_new_deviations(bundle_id)
        for result, element_id, alert_id in alerts:
            if alert_id:
                monitor.mark_alert_sent(alert_id)
        return len(alerts)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("Running guideline adherence monitor (dry run)...")
    count = run_guideline_monitor(dry_run=True)
    print(f"Found {count} episodes")
