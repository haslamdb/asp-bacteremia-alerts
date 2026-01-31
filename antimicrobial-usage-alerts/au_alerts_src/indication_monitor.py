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

try:
    from cchmc_guidelines import CCHMCGuidelinesEngine, AgentCategory, AgentRecommendation
except ImportError:
    CCHMCGuidelinesEngine = None
    AgentCategory = None
    AgentRecommendation = None

# New taxonomy-based extraction (JC-compliant)
try:
    from indication_extractor import IndicationExtractor as TaxonomyExtractor
    from indication_taxonomy import get_indication_by_synonym, get_never_appropriate_indications
    TAXONOMY_AVAILABLE = True
except ImportError:
    TaxonomyExtractor = None
    get_indication_by_synonym = None
    get_never_appropriate_indications = None
    TAXONOMY_AVAILABLE = False

logger = logging.getLogger(__name__)


class IndicationMonitor:
    """Monitor antibiotic orders for documented indications."""

    def __init__(
        self,
        fhir_client: FHIRClient | None = None,
        classifier: "AntibioticIndicationClassifier | None" = None,
        llm_extractor=None,
        taxonomy_extractor=None,
        alert_store: AlertStore | None = None,
        db: IndicationDatabase | None = None,
        use_taxonomy_first: bool = True,
    ):
        """Initialize the indication monitor.

        Args:
            fhir_client: FHIR client for queries. Uses factory default if None.
            classifier: Antibiotic indication classifier. Loads from CSV if None.
            llm_extractor: Legacy LLM extractor for note analysis. Optional.
            taxonomy_extractor: JC-compliant taxonomy extractor. Loads default if None.
            alert_store: Alert store for persisting alerts. Uses default if None.
            db: Database for indication tracking. Uses default if None.
            use_taxonomy_first: If True, use taxonomy extraction as primary (JC-compliant).
                              If False, use ICD-10 as primary (legacy behavior).
        """
        self.fhir_client = fhir_client or get_fhir_client()
        self.classifier = classifier or self._load_classifier()
        self.llm_extractor = llm_extractor
        self.alert_store = alert_store or AlertStore(db_path=config.ALERT_DB_PATH)
        self.db = db or IndicationDatabase()
        self._alerted_orders: set[str] = set()  # In-memory cache
        self.use_taxonomy_first = use_taxonomy_first

        # Initialize taxonomy extractor (JC-compliant clinical syndrome extraction)
        self.taxonomy_extractor = taxonomy_extractor or self._load_taxonomy_extractor()

        # Initialize CCHMC guidelines engine for agent appropriateness checking
        self.cchmc_engine = self._load_cchmc_engine()

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

    def _load_cchmc_engine(self) -> "CCHMCGuidelinesEngine | None":
        """Load the CCHMC guidelines engine for agent appropriateness checking."""
        if CCHMCGuidelinesEngine is None:
            logger.info(
                "CCHMCGuidelinesEngine not available. "
                "CCHMC agent checking will be disabled."
            )
            return None

        try:
            engine = CCHMCGuidelinesEngine()
            logger.info("Loaded CCHMC guidelines engine")
            return engine
        except Exception as e:
            logger.warning(f"Failed to load CCHMC guidelines engine: {e}")
            return None

    def _load_taxonomy_extractor(self) -> "TaxonomyExtractor | None":
        """Load the JC-compliant taxonomy extractor for clinical syndrome extraction.

        This extractor uses LLM to identify clinical syndromes (CAP, UTI, sepsis)
        from notes, meeting Joint Commission requirements for indication documentation.
        """
        if not TAXONOMY_AVAILABLE or TaxonomyExtractor is None:
            logger.info(
                "Taxonomy extractor not available. "
                "Will use legacy ICD-10 classification."
            )
            return None

        try:
            extractor = TaxonomyExtractor()
            logger.info("Loaded JC-compliant taxonomy extractor")
            return extractor
        except Exception as e:
            logger.warning(f"Failed to load taxonomy extractor: {e}")
            return None

    def auto_accept_old_candidates(self, hours: int = 48) -> int:
        """Auto-accept candidates older than specified hours without human review.

        This prevents the review queue from growing indefinitely. Should be called
        periodically (e.g., every few hours or daily).

        Args:
            hours: Hours after which to auto-accept. Default 48.

        Returns:
            Number of candidates auto-accepted.
        """
        return self.db.auto_accept_old_candidates(hours=hours)

    def check_new_orders(self, since_hours: int = 24, auto_accept_hours: int = 48) -> list[IndicationAssessment]:
        """Check new antibiotic orders for indications.

        Also auto-accepts candidates older than auto_accept_hours to prevent
        queue buildup.

        Args:
            since_hours: How far back to look for new orders.
            auto_accept_hours: Hours after which to auto-accept unreviewed candidates.
                Set to 0 to disable auto-accept.

        Returns:
            List of IndicationAssessment objects.
        """
        # Auto-accept old candidates first
        if auto_accept_hours > 0:
            auto_accepted = self.auto_accept_old_candidates(hours=auto_accept_hours)
            if auto_accepted > 0:
                logger.info(f"Auto-accepted {auto_accepted} old candidates")

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

        Uses taxonomy-based extraction (JC-compliant) as primary, with ICD-10 fallback.
        Clinical notes take priority over ICD-10 codes because:
        - ICD-10 codes may be stale (from previous encounters)
        - Notes reflect real-time clinical reasoning
        - Notes capture nuance that codes cannot
        - Joint Commission requires clinical syndrome documentation at order entry

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

        # Get patient's current encounter info (location, service)
        encounter_info = self.fhir_client.get_patient_encounter_info(order.patient_id)
        location = encounter_info.get("location")
        service = encounter_info.get("service")

        # Get patient's ICD-10 codes (for fallback and validation)
        icd10_codes = self.fhir_client.get_patient_conditions(order.patient_id)
        logger.debug(f"Patient {patient.mrn}: {len(icd10_codes)} ICD-10 codes")

        # ICD-10 classification as baseline/fallback
        icd10_classification = "U"  # Unknown
        icd10_primary = None
        classification_result = None

        if self.classifier:
            classification_result = self.classifier.classify(
                icd10_codes=icd10_codes,
                cpt_codes=[],
                fever_present=False,
            )
            icd10_classification = classification_result.overall_category.value
            icd10_primary = classification_result.primary_indication

        # Initialize taxonomy extraction results
        clinical_syndrome = None
        clinical_syndrome_display = None
        syndrome_category = None
        syndrome_confidence = None
        therapy_intent = None
        guideline_disease_ids = None
        likely_viral = False
        asymptomatic_bacteriuria = False
        indication_not_documented = False
        never_appropriate = False

        # Initialize final classification
        final_classification = icd10_classification
        classification_source = "icd10"
        llm_extracted = None
        llm_classification = None

        # TAXONOMY EXTRACTION (JC-compliant) - PRIMARY METHOD
        if self.use_taxonomy_first and self.taxonomy_extractor:
            logger.debug(f"Attempting taxonomy extraction for {order.fhir_id}")
            try:
                taxonomy_result = self._extract_with_taxonomy(order, patient)
                if taxonomy_result:
                    clinical_syndrome = taxonomy_result.primary_indication
                    clinical_syndrome_display = taxonomy_result.primary_indication_display
                    syndrome_category = taxonomy_result.indication_category
                    syndrome_confidence = taxonomy_result.indication_confidence
                    therapy_intent = taxonomy_result.therapy_intent
                    guideline_disease_ids = taxonomy_result.guideline_disease_ids
                    likely_viral = taxonomy_result.likely_viral
                    asymptomatic_bacteriuria = taxonomy_result.asymptomatic_bacteriuria
                    indication_not_documented = taxonomy_result.indication_not_documented
                    never_appropriate = taxonomy_result.never_appropriate

                    # Map to legacy classification for compatibility
                    llm_classification = self._taxonomy_to_classification(taxonomy_result)
                    llm_extracted = clinical_syndrome_display

                    if llm_classification:
                        final_classification = llm_classification
                        classification_source = "taxonomy"

                        if llm_classification != icd10_classification:
                            logger.info(
                                f"Taxonomy overrides ICD-10 for {order.medication_name}: "
                                f"{icd10_classification} -> {llm_classification} "
                                f"(syndrome: {clinical_syndrome}, confidence: {syndrome_confidence})"
                            )

            except Exception as e:
                logger.warning(f"Taxonomy extraction failed: {e}")

        # LEGACY LLM EXTRACTION - only if taxonomy not used or failed
        elif self.llm_extractor:
            logger.debug(f"Attempting legacy LLM extraction for {order.fhir_id}")
            try:
                extraction = self._extract_from_notes(order, patient)
                if extraction:
                    llm_extracted = "; ".join(extraction.found_indications) if extraction.found_indications else None
                    llm_classification = self._classify_from_extraction(extraction, order.medication_name)

                    if llm_classification:
                        if llm_classification != icd10_classification:
                            logger.info(
                                f"LLM overrides ICD-10 for {order.medication_name}: "
                                f"{icd10_classification} -> {llm_classification} "
                                f"(confidence: {extraction.confidence})"
                            )
                        final_classification = llm_classification
                        classification_source = "llm"

            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}")

        # CCHMC agent appropriateness check
        # Use guideline_disease_ids from taxonomy if available, else fall back to ICD-10
        cchmc_disease_matched = None
        cchmc_agent_category = None
        cchmc_guideline_agents = None
        cchmc_recommendation = None

        if final_classification in ("A", "S", "P", "FN") and self.cchmc_engine:
            try:
                patient_age_months = self._get_patient_age_months(patient)
                patient_allergies = self.fhir_client.get_patient_allergies(order.patient_id) if hasattr(self.fhir_client, 'get_patient_allergies') else None

                agent_rec = self.cchmc_engine.check_agent_appropriateness(
                    icd10_codes=icd10_codes,
                    prescribed_agent=order.medication_name,
                    patient_age_months=patient_age_months,
                    allergies=patient_allergies,
                )

                if agent_rec.disease_matched:
                    cchmc_disease_matched = agent_rec.disease_matched
                    cchmc_agent_category = agent_rec.current_agent_category.value
                    cchmc_guideline_agents = ", ".join(agent_rec.first_line_agents[:3])
                    cchmc_recommendation = agent_rec.recommendation

                    if agent_rec.current_agent_category == AgentCategory.OFF_GUIDELINE:
                        logger.info(
                            f"Off-guideline agent: {order.medication_name} "
                            f"for {cchmc_disease_matched}. "
                            f"Recommended: {cchmc_guideline_agents}"
                        )

            except Exception as e:
                logger.warning(f"CCHMC agent check failed: {e}")

        # Create candidate with all fields
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
            location=location,
            service=service,
            cchmc_disease_matched=cchmc_disease_matched,
            cchmc_agent_category=cchmc_agent_category,
            cchmc_guideline_agents=cchmc_guideline_agents,
            cchmc_recommendation=cchmc_recommendation,
            # JC-compliant taxonomy fields
            clinical_syndrome=clinical_syndrome,
            clinical_syndrome_display=clinical_syndrome_display,
            syndrome_category=syndrome_category,
            syndrome_confidence=syndrome_confidence,
            therapy_intent=therapy_intent,
            guideline_disease_ids=guideline_disease_ids,
            likely_viral=likely_viral,
            asymptomatic_bacteriuria=asymptomatic_bacteriuria,
            indication_not_documented=indication_not_documented,
            never_appropriate=never_appropriate,
        )

        # Save candidate to database
        self.db.save_candidate(candidate)

        # Determine if alert needed
        # Alert for N classifications OR red flags (even if classification is S or A)
        requires_alert = (
            final_classification == "N"
            or never_appropriate
            or likely_viral
            or asymptomatic_bacteriuria
        )

        # Generate recommendation
        recommendation = self._generate_recommendation_v2(
            order=order,
            candidate=candidate,
            classification_result=classification_result,
        )

        # Determine severity
        severity = AlertSeverity.WARNING
        if never_appropriate or likely_viral:
            severity = AlertSeverity.CRITICAL
        elif final_classification == "N" and not icd10_codes:
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

    def _extract_with_taxonomy(self, order: MedicationOrder, patient: Patient):
        """Extract indication using JC-compliant taxonomy extractor.

        Args:
            order: The medication order.
            patient: The patient.

        Returns:
            IndicationExtraction from taxonomy extractor or None.
        """
        if not self.taxonomy_extractor:
            return None

        # Get recent notes
        notes = self.fhir_client.get_recent_notes(
            patient_id=order.patient_id,
            since_hours=48,
        )

        if not notes:
            logger.debug(f"No notes found for patient {patient.mrn}")
            return None

        # Extract note texts
        note_texts = [n.get("text", "") for n in notes if n.get("text")]
        if not note_texts:
            return None

        # Use taxonomy extractor
        return self.taxonomy_extractor.extract(
            notes=note_texts,
            antibiotic=order.medication_name,
            order_date=order.start_date.isoformat() if order.start_date else None,
        )

    def _taxonomy_to_classification(self, taxonomy_result) -> str | None:
        """Map taxonomy extraction to legacy A/S/N/P/FN classification.

        Args:
            taxonomy_result: Result from taxonomy extractor.

        Returns:
            Classification string or None if inconclusive.
        """
        if not taxonomy_result:
            return None

        # Red flags always result in N (no appropriate indication)
        if taxonomy_result.never_appropriate:
            return "N"
        if taxonomy_result.likely_viral:
            return "N"
        if taxonomy_result.asymptomatic_bacteriuria:
            return "N"
        if taxonomy_result.indication_not_documented:
            return "N"

        # Empiric unknown with unclear confidence = no determination
        if taxonomy_result.primary_indication == "empiric_unknown":
            if taxonomy_result.indication_confidence == "unclear":
                return None  # Fall back to ICD-10
            return "S"  # Sometimes appropriate for documented empiric therapy

        # Prophylaxis category
        if taxonomy_result.indication_category == "prophylaxis":
            return "P"

        # Febrile neutropenia
        if taxonomy_result.primary_indication == "febrile_neutropenia":
            return "FN"

        # Map confidence to classification
        confidence = taxonomy_result.indication_confidence
        if confidence == "definite":
            return "A"  # Always appropriate
        elif confidence == "probable":
            return "S"  # Sometimes appropriate
        else:
            return None  # Fall back to ICD-10

    def _generate_recommendation_v2(
        self,
        order: MedicationOrder,
        candidate: IndicationCandidate,
        classification_result=None,
    ) -> str:
        """Generate recommendation using taxonomy data.

        Args:
            order: The medication order.
            candidate: The indication candidate with all fields.
            classification_result: ICD-10 classification result (optional).

        Returns:
            Recommendation string.
        """
        med_name = order.medication_name

        # Red flag recommendations take priority
        if candidate.never_appropriate:
            return (
                f"⚠️ {med_name} prescribed for {candidate.clinical_syndrome_display or 'indication'} "
                f"where antibiotics are rarely/never appropriate. Consider discontinuation."
            )

        if candidate.likely_viral:
            return (
                f"⚠️ Notes suggest viral illness. {med_name} may not be indicated. "
                "Review for possible discontinuation."
            )

        if candidate.asymptomatic_bacteriuria:
            return (
                f"⚠️ Possible asymptomatic bacteriuria. {med_name} may not be indicated "
                "unless patient is pregnant or pre-urologic procedure."
            )

        if candidate.indication_not_documented:
            return (
                f"No documented indication for {med_name}. "
                "Per Joint Commission, document clinical syndrome at order entry."
            )

        # Classification-based recommendations
        final = candidate.final_classification

        if final == "N":
            return (
                f"No documented indication for {med_name}. "
                "Consider discontinuation or document indication."
            )

        if final == "U":
            return (
                f"Unable to classify indication for {med_name}. "
                "Manual review required."
            )

        # For documented indications (A, S, P, FN)
        if candidate.clinical_syndrome_display:
            syndrome = candidate.clinical_syndrome_display
            confidence = candidate.syndrome_confidence or "documented"

            if final in ("A", "FN"):
                return f"{med_name} indicated for {syndrome} ({confidence})."
            elif final == "S":
                return f"{med_name} may be appropriate for {syndrome}. Clinical review recommended."
            elif final == "P":
                return f"{med_name} prescribed for prophylaxis ({syndrome})."

        # Fallback to ICD-10 based recommendation
        if candidate.icd10_primary_indication:
            return f"{med_name} indicated for {candidate.icd10_primary_indication}."

        return f"Unable to assess indication for {med_name}."

    def _get_patient_age_months(self, patient: Patient) -> int | None:
        """Calculate patient age in months from birth date.

        Args:
            patient: Patient object with birth_date.

        Returns:
            Age in months or None if birth date not available.
        """
        if not patient or not hasattr(patient, 'birth_date') or not patient.birth_date:
            return None

        try:
            today = datetime.now().date()
            birth = patient.birth_date
            if isinstance(birth, datetime):
                birth = birth.date()

            # Calculate months
            months = (today.year - birth.year) * 12 + (today.month - birth.month)
            if today.day < birth.day:
                months -= 1
            return max(0, months)
        except Exception:
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

        # Import NoteWithMetadata here to avoid circular imports
        from .llm_extractor import NoteWithMetadata

        # Get recent notes
        notes = self.fhir_client.get_recent_notes(
            patient_id=order.patient_id,
            since_hours=48,
        )

        if not notes:
            logger.debug(f"No notes found for patient {patient.mrn}")
            return None

        # Convert to NoteWithMetadata objects
        notes_with_meta = []
        for n in notes:
            text = n.get("text", "")
            if not text:
                continue

            # Extract metadata from FHIR note structure
            note_type = n.get("type", n.get("category", "UNKNOWN"))
            note_date = n.get("date")
            author = n.get("author", n.get("practitioner"))
            note_id = n.get("id")

            # Normalize date format if needed
            if note_date and hasattr(note_date, "isoformat"):
                note_date = note_date.isoformat()[:10]
            elif note_date and len(str(note_date)) > 10:
                note_date = str(note_date)[:10]

            notes_with_meta.append(
                NoteWithMetadata(
                    text=text,
                    note_type=note_type,
                    note_date=note_date,
                    author=author,
                    note_id=note_id,
                )
            )

        if not notes_with_meta:
            return None

        # Call LLM extractor with metadata
        return self.llm_extractor.extract(
            notes=notes_with_meta,
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
