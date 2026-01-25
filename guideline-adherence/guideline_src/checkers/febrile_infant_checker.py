"""Febrile Infant bundle element checker.

Implements the AAP 2021 guideline for evaluation of well-appearing
febrile infants 8-60 days old. Handles:
- Age-stratified workup requirements (8-21d, 22-28d, 29-60d)
- Conditional logic based on inflammatory markers
- CSF-based decision branches
"""

from datetime import datetime
from enum import Enum
from typing import Optional
import logging
import sys
from pathlib import Path

# Add parent paths for imports
GUIDELINE_ADHERENCE_PATH = Path(__file__).parent.parent.parent
if str(GUIDELINE_ADHERENCE_PATH) not in sys.path:
    sys.path.insert(0, str(GUIDELINE_ADHERENCE_PATH))

from guideline_adherence import BundleElement

from ..models import ElementCheckResult, ElementCheckStatus
from ..config import config
from .base import ElementChecker

logger = logging.getLogger(__name__)


class InfantAgeGroup(Enum):
    """Age stratification for febrile infant evaluation (AAP 2021)."""
    DAYS_0_7 = "0-7 days"      # Excluded from AAP guideline (higher risk)
    DAYS_8_21 = "8-21 days"    # Highest risk group in guideline
    DAYS_22_28 = "22-28 days"  # Intermediate risk
    DAYS_29_60 = "29-60 days"  # Lower risk, more options


def get_age_group(age_days: int) -> InfantAgeGroup:
    """Determine age group for guideline stratification."""
    if age_days < 8:
        return InfantAgeGroup.DAYS_0_7
    elif age_days <= 21:
        return InfantAgeGroup.DAYS_8_21
    elif age_days <= 28:
        return InfantAgeGroup.DAYS_22_28
    else:
        return InfantAgeGroup.DAYS_29_60


class FebrileInfantChecker(ElementChecker):
    """Check bundle elements for febrile infant guideline.

    This checker implements age-stratified and conditional logic per AAP 2021.
    """

    # Map element IDs to LOINC codes
    ELEMENT_LOINC_MAP = {
        "fi_ua": [config.LOINC_UA, config.LOINC_UA_WBC, config.LOINC_UA_LE],
        "fi_blood_culture": [config.LOINC_BLOOD_CULTURE],
        "fi_inflammatory_markers": [config.LOINC_ANC, config.LOINC_CRP],
        "fi_procalcitonin": [config.LOINC_PROCALCITONIN],
        "fi_csf_studies": [config.LOINC_CSF_WBC, config.LOINC_CSF_RBC],
        "fi_urine_culture": [config.LOINC_URINE_CULTURE],
    }

    def __init__(self, fhir_client):
        """Initialize with FHIR client."""
        super().__init__(fhir_client)
        # Cache for patient context
        self._patient_context = {}

    def check(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
        age_days: Optional[int] = None,
    ) -> ElementCheckResult:
        """Check if a febrile infant bundle element has been completed.

        Args:
            element: The bundle element to check.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.
            age_days: Patient age in days (required for age-stratified elements).

        Returns:
            ElementCheckResult with status.
        """
        element_id = element.element_id

        # Get patient context if not cached
        if patient_id not in self._patient_context:
            self._patient_context[patient_id] = self._build_patient_context(
                patient_id, trigger_time, age_days
            )

        context = self._patient_context[patient_id]
        age_group = context.get("age_group")

        # Check if element applies to this age group
        applicability = self._check_element_applicability(element_id, context)
        if applicability == "not_applicable":
            return self._create_result(
                element=element,
                status=ElementCheckStatus.NOT_APPLICABLE,
                trigger_time=trigger_time,
                notes=f"Not applicable for age group {age_group.value if age_group else 'unknown'}",
            )
        elif applicability == "conditional_not_met":
            return self._create_result(
                element=element,
                status=ElementCheckStatus.NOT_APPLICABLE,
                trigger_time=trigger_time,
                notes="Conditional requirement not met",
            )

        # Route to specific checker based on element type
        if element_id in ["fi_ua", "fi_blood_culture", "fi_inflammatory_markers",
                         "fi_procalcitonin", "fi_csf_studies", "fi_urine_culture"]:
            return self._check_lab_element(element, patient_id, trigger_time, context)

        elif element_id.startswith("fi_lp"):
            return self._check_lp_element(element, patient_id, trigger_time, context)

        elif element_id.startswith("fi_abx"):
            return self._check_antibiotic_element(element, patient_id, trigger_time, context)

        elif element_id == "fi_hsv_risk_assessment":
            return self._check_hsv_assessment(element, patient_id, trigger_time, context)

        elif element_id.startswith("fi_admit"):
            return self._check_admission_element(element, patient_id, trigger_time, context)

        elif element_id == "fi_safe_discharge_checklist":
            return self._check_discharge_checklist(element, patient_id, trigger_time, context)

        else:
            logger.warning(f"Unknown febrile infant element: {element_id}")
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes=f"Unknown element type: {element_id}",
            )

    def _build_patient_context(
        self,
        patient_id: str,
        trigger_time: datetime,
        age_days: Optional[int] = None
    ) -> dict:
        """Build patient context for conditional element evaluation.

        Args:
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.
            age_days: Patient age in days (if known).

        Returns:
            Dict with patient context for element evaluation.
        """
        context = {
            "age_days": age_days,
            "age_group": get_age_group(age_days) if age_days is not None else None,
            "inflammatory_markers_abnormal": False,
            "ua_abnormal": False,
            "lp_performed": False,
            "csf_pleocytosis": False,
            "disposition_home": False,
        }

        # Get patient info if age not provided
        if age_days is None:
            patient = self.fhir_client.get_patient(patient_id)
            if patient and patient.get("birth_date"):
                birth_date = patient["birth_date"]
                context["age_days"] = (trigger_time.date() - birth_date).days
                context["age_group"] = get_age_group(context["age_days"])

        # Check inflammatory markers
        context["inflammatory_markers_abnormal"] = self._are_inflammatory_markers_abnormal(
            patient_id, trigger_time
        )

        # Check UA
        context["ua_abnormal"] = self._is_ua_abnormal(patient_id, trigger_time)

        # Check LP status
        context["lp_performed"] = self._is_lp_performed(patient_id, trigger_time)

        return context

    def _check_element_applicability(self, element_id: str, context: dict) -> str:
        """Check if element applies given patient context.

        Returns:
            "applicable", "not_applicable", or "conditional_not_met"
        """
        age_group = context.get("age_group")
        im_abnormal = context.get("inflammatory_markers_abnormal", False)
        ua_abnormal = context.get("ua_abnormal", False)

        # Age-based applicability
        age_requirements = {
            # LP elements
            "fi_lp_8_21d": [InfantAgeGroup.DAYS_8_21],
            "fi_lp_22_28d_im_abnormal": [InfantAgeGroup.DAYS_22_28],

            # Treatment elements
            "fi_abx_8_21d": [InfantAgeGroup.DAYS_8_21],
            "fi_abx_22_28d_im_abnormal": [InfantAgeGroup.DAYS_22_28],

            # Admission elements
            "fi_admit_8_21d": [InfantAgeGroup.DAYS_8_21],
            "fi_admit_22_28d_im_abnormal": [InfantAgeGroup.DAYS_22_28],

            # HSV - 8-28 days
            "fi_hsv_risk_assessment": [InfantAgeGroup.DAYS_8_21, InfantAgeGroup.DAYS_22_28],

            # PCT recommended for 29-60 days
            "fi_procalcitonin": [InfantAgeGroup.DAYS_29_60],
        }

        if element_id in age_requirements:
            if age_group not in age_requirements[element_id]:
                return "not_applicable"

        # Conditional requirements
        conditional_requirements = {
            "fi_lp_22_28d_im_abnormal": lambda: im_abnormal,
            "fi_abx_22_28d_im_abnormal": lambda: im_abnormal,
            "fi_admit_22_28d_im_abnormal": lambda: im_abnormal,
            "fi_urine_culture": lambda: ua_abnormal,
            "fi_safe_discharge_checklist": lambda: context.get("disposition_home", False),
        }

        if element_id in conditional_requirements:
            if not conditional_requirements[element_id]():
                return "conditional_not_met"

        return "applicable"

    def _are_inflammatory_markers_abnormal(
        self,
        patient_id: str,
        trigger_time: datetime
    ) -> bool:
        """Check if any inflammatory markers are abnormal.

        Thresholds (AAP 2021):
        - PCT > 0.5 ng/mL
        - ANC > 4000/μL
        - CRP > 2.0 mg/dL
        """
        # Get PCT
        pct_labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=[config.LOINC_PROCALCITONIN],
            since_time=trigger_time,
        )
        for lab in pct_labs:
            value = lab.get("value")
            if value and float(value) > config.FI_PCT_ABNORMAL:
                return True

        # Get ANC
        anc_labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=[config.LOINC_ANC],
            since_time=trigger_time,
        )
        for lab in anc_labs:
            value = lab.get("value")
            if value and float(value) > config.FI_ANC_ABNORMAL:
                return True

        # Get CRP
        crp_labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=[config.LOINC_CRP],
            since_time=trigger_time,
        )
        for lab in crp_labs:
            value = lab.get("value")
            if value and float(value) > config.FI_CRP_ABNORMAL:
                return True

        return False

    def _is_ua_abnormal(self, patient_id: str, trigger_time: datetime) -> bool:
        """Check if urinalysis is abnormal.

        Abnormal UA defined as:
        - WBC >= 5/HPF OR
        - Positive leukocyte esterase
        """
        # Check UA WBC
        ua_wbc_labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=[config.LOINC_UA_WBC],
            since_time=trigger_time,
        )
        for lab in ua_wbc_labs:
            value = lab.get("value")
            if value:
                try:
                    if float(value) >= config.FI_UA_WBC_ABNORMAL:
                        return True
                except (ValueError, TypeError):
                    pass

        # Check LE
        ua_le_labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=[config.LOINC_UA_LE],
            since_time=trigger_time,
        )
        for lab in ua_le_labs:
            value = str(lab.get("value", "")).lower()
            if value in ["positive", "pos", "+", "++", "+++"]:
                return True

        return False

    def _is_lp_performed(self, patient_id: str, trigger_time: datetime) -> bool:
        """Check if LP was performed (CSF results available)."""
        csf_labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=[config.LOINC_CSF_WBC],
            since_time=trigger_time,
        )
        return len(csf_labs) > 0

    def _check_lab_element(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
        context: dict,
    ) -> ElementCheckResult:
        """Check lab-based febrile infant elements."""
        loinc_codes = self.ELEMENT_LOINC_MAP.get(element.element_id, [])

        if not loinc_codes:
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="No LOINC codes configured",
            )

        labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=loinc_codes,
            since_time=trigger_time,
        )

        if not labs:
            if self._is_within_window(trigger_time, element.time_window_hours):
                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.PENDING,
                    trigger_time=trigger_time,
                    notes="Awaiting lab results",
                )
            else:
                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.NOT_MET,
                    trigger_time=trigger_time,
                    notes="Time window expired without lab result",
                )

        # Check if result within window
        deadline = self._calculate_deadline(trigger_time, element.time_window_hours)
        for lab in sorted(labs, key=lambda x: x.get("effective_time", datetime.max)):
            effective_time = lab.get("effective_time")
            if effective_time and (deadline is None or effective_time <= deadline):
                value = lab.get("value")
                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.MET,
                    trigger_time=trigger_time,
                    completed_at=effective_time,
                    value=value,
                    notes=f"Result: {value}" if value else "Result obtained",
                )

        if self._is_within_window(trigger_time, element.time_window_hours):
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="Results found but not within required window",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.NOT_MET,
            trigger_time=trigger_time,
            notes="Time window expired - no result within required timeframe",
        )

    def _check_lp_element(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
        context: dict,
    ) -> ElementCheckResult:
        """Check LP-related elements."""
        # Check for CSF results as proxy for LP performed
        csf_labs = self.fhir_client.get_lab_results(
            patient_id=patient_id,
            loinc_codes=[config.LOINC_CSF_WBC, config.LOINC_CSF_RBC],
            since_time=trigger_time,
        )

        if csf_labs:
            deadline = self._calculate_deadline(trigger_time, element.time_window_hours)
            for lab in sorted(csf_labs, key=lambda x: x.get("effective_time", datetime.max)):
                effective_time = lab.get("effective_time")
                if effective_time and (deadline is None or effective_time <= deadline):
                    return self._create_result(
                        element=element,
                        status=ElementCheckStatus.MET,
                        trigger_time=trigger_time,
                        completed_at=effective_time,
                        notes="LP performed - CSF results available",
                    )

        if self._is_within_window(trigger_time, element.time_window_hours):
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="LP not yet performed",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.NOT_MET,
            trigger_time=trigger_time,
            notes="LP required but not performed within time window",
        )

    def _check_antibiotic_element(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
        context: dict,
    ) -> ElementCheckResult:
        """Check antibiotic administration elements."""
        med_admins = self.fhir_client.get_medication_administrations(
            patient_id=patient_id,
            since_time=trigger_time,
        )

        # Filter for IV antibiotics
        iv_antibiotics = [
            ma for ma in med_admins
            if ma.get("route", "").lower() in ["iv", "intravenous", "parenteral"]
            and self._is_antibiotic(ma.get("medication_name", ""))
        ]

        if not iv_antibiotics:
            if self._is_within_window(trigger_time, element.time_window_hours):
                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.PENDING,
                    trigger_time=trigger_time,
                    notes="IV antibiotics not yet administered",
                )
            else:
                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.NOT_MET,
                    trigger_time=trigger_time,
                    notes="IV antibiotics not administered within time window",
                )

        # Check timing
        deadline = self._calculate_deadline(trigger_time, element.time_window_hours)
        for admin in sorted(iv_antibiotics, key=lambda x: x.get("admin_time", datetime.max)):
            admin_time = admin.get("admin_time")
            if admin_time and (deadline is None or admin_time <= deadline):
                med_name = admin.get("medication_name", "antibiotic")
                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.MET,
                    trigger_time=trigger_time,
                    completed_at=admin_time,
                    value=med_name,
                    notes=f"IV {med_name} administered",
                )

        if self._is_within_window(trigger_time, element.time_window_hours):
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="IV antibiotics found but not within required window",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.NOT_MET,
            trigger_time=trigger_time,
            notes="IV antibiotics not administered within required window",
        )

    def _check_hsv_assessment(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
        context: dict,
    ) -> ElementCheckResult:
        """Check HSV risk assessment documentation."""
        # Check for acyclovir order/administration
        med_admins = self.fhir_client.get_medication_administrations(
            patient_id=patient_id,
            since_time=trigger_time,
        )

        acyclovir_given = any(
            "acyclovir" in ma.get("medication_name", "").lower()
            for ma in med_admins
        )

        if acyclovir_given:
            return self._create_result(
                element=element,
                status=ElementCheckStatus.MET,
                trigger_time=trigger_time,
                notes="Acyclovir administered - HSV considered",
            )

        # Check notes for HSV documentation
        notes = self.fhir_client.get_recent_notes(
            patient_id=patient_id,
            since_time=trigger_time,
        )

        hsv_keywords = ["hsv", "herpes", "acyclovir", "hsv risk", "vesicles"]
        for note in notes:
            note_text = note.get("text", "").lower()
            if any(kw in note_text for kw in hsv_keywords):
                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.MET,
                    trigger_time=trigger_time,
                    completed_at=note.get("date"),
                    notes="HSV risk documented in notes",
                )

        if self._is_within_window(trigger_time, element.time_window_hours):
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="HSV risk assessment not yet documented",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.NOT_MET,
            trigger_time=trigger_time,
            notes="HSV risk assessment not documented",
        )

    def _check_admission_element(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
        context: dict,
    ) -> ElementCheckResult:
        """Check hospital admission elements."""
        # Check encounter type
        patient = self.fhir_client.get_patient(patient_id)

        # For now, assume admitted if we have an active encounter
        # In real implementation, would check encounter type
        return self._create_result(
            element=element,
            status=ElementCheckStatus.PENDING,
            trigger_time=trigger_time,
            notes="Admission status check requires encounter data",
        )

    def _check_discharge_checklist(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
        context: dict,
    ) -> ElementCheckResult:
        """Check safe discharge checklist elements."""
        # Check notes for follow-up documentation
        notes = self.fhir_client.get_recent_notes(
            patient_id=patient_id,
            since_time=trigger_time,
        )

        discharge_keywords = ["follow-up", "followup", "return precautions",
                            "phone number", "transportation"]
        documented_items = 0

        for note in notes:
            note_text = note.get("text", "").lower()
            for kw in discharge_keywords:
                if kw in note_text:
                    documented_items += 1
                    break

        if documented_items >= 2:
            return self._create_result(
                element=element,
                status=ElementCheckStatus.MET,
                trigger_time=trigger_time,
                notes="Discharge checklist items documented",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.PENDING,
            trigger_time=trigger_time,
            notes="Safe discharge checklist incomplete",
        )

    def _is_antibiotic(self, medication_name: str) -> bool:
        """Check if medication is an antibiotic."""
        antibiotic_keywords = [
            "ampicillin", "gentamicin", "cefotaxime", "ceftriaxone",
            "vancomycin", "acyclovir", "penicillin", "cephalosporin",
            "amoxicillin", "cefazolin", "azithromycin", "metronidazole",
        ]
        med_lower = medication_name.lower()
        return any(abx in med_lower for abx in antibiotic_keywords)

    def clear_patient_cache(self, patient_id: Optional[str] = None):
        """Clear cached patient context.

        Args:
            patient_id: Specific patient to clear, or None to clear all.
        """
        if patient_id:
            self._patient_context.pop(patient_id, None)
        else:
            self._patient_context.clear()
