"""
FHIR client for surgical prophylaxis data access.

Queries Epic FHIR API for:
- Procedure (surgical cases, CPT codes, timing)
- MedicationRequest (prophylaxis orders)
- MedicationAdministration (actual administrations)
- Patient (demographics, weight)
- AllergyIntolerance (beta-lactam allergies)
"""

import os
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin

import requests

from .config import FHIR_BASE_URL, CPT_CATEGORY_HINTS
from .models import (
    MedicationAdministration,
    MedicationOrder,
    ProcedureCategory,
    SurgicalCase,
)


class FHIRClient:
    """Client for querying FHIR resources related to surgical prophylaxis."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 30):
        self.base_url = base_url or FHIR_BASE_URL
        self.timeout = timeout
        self.session = requests.Session()
        # Add auth headers if needed
        auth_token = os.getenv("FHIR_AUTH_TOKEN")
        if auth_token:
            self.session.headers["Authorization"] = f"Bearer {auth_token}"

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make GET request to FHIR endpoint."""
        url = urljoin(self.base_url.rstrip("/") + "/", endpoint.lstrip("/"))
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _get_all_pages(self, endpoint: str, params: Optional[dict] = None) -> list[dict]:
        """Get all pages of a FHIR search result."""
        results = []
        response = self._get(endpoint, params)

        while True:
            entries = response.get("entry", [])
            results.extend([e.get("resource", {}) for e in entries])

            # Check for next page
            next_link = next(
                (link for link in response.get("link", []) if link.get("relation") == "next"),
                None,
            )
            if not next_link:
                break

            # Fetch next page
            response = self.session.get(next_link["url"], timeout=self.timeout).json()

        return results

    def get_surgical_procedures(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        patient_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Get surgical procedures.

        Args:
            date_from: Start date for procedure search
            date_to: End date for procedure search
            patient_id: Optional specific patient

        Returns:
            List of FHIR Procedure resources
        """
        params = {
            "_count": 100,
        }

        if date_from:
            params["date"] = f"ge{date_from.isoformat()}"
        if date_to:
            # Add date less than or equal to
            if "date" in params:
                params["date"] = [params["date"], f"le{date_to.isoformat()}"]
            else:
                params["date"] = f"le{date_to.isoformat()}"
        if patient_id:
            params["subject"] = f"Patient/{patient_id}"

        # Filter for surgical procedures (status completed or in-progress)
        params["status"] = "completed,in-progress"

        return self._get_all_pages("Procedure", params)

    def get_medication_orders(
        self,
        patient_id: str,
        since_hours: int = 48,
        prophylaxis_only: bool = True,
    ) -> list[dict]:
        """
        Get medication orders (MedicationRequest) for a patient.

        Args:
            patient_id: Patient FHIR ID
            since_hours: Look back this many hours
            prophylaxis_only: Filter to likely prophylaxis antibiotics

        Returns:
            List of FHIR MedicationRequest resources
        """
        cutoff = datetime.now() - timedelta(hours=since_hours)
        params = {
            "subject": f"Patient/{patient_id}",
            "authoredon": f"ge{cutoff.isoformat()}",
            "status": "active,completed",
            "_count": 50,
        }

        orders = self._get_all_pages("MedicationRequest", params)

        if prophylaxis_only:
            # Filter to antibiotics commonly used for prophylaxis
            prophylaxis_meds = [
                "cefazolin", "vancomycin", "clindamycin", "metronidazole",
                "gentamicin", "cefoxitin", "ampicillin", "piperacillin",
            ]
            orders = [
                o for o in orders
                if any(
                    med in self._get_medication_name(o).lower()
                    for med in prophylaxis_meds
                )
            ]

        return orders

    def get_medication_administrations(
        self,
        patient_id: str,
        since_hours: int = 48,
        prophylaxis_only: bool = True,
    ) -> list[dict]:
        """
        Get medication administrations (MAR) for a patient.

        Args:
            patient_id: Patient FHIR ID
            since_hours: Look back this many hours
            prophylaxis_only: Filter to likely prophylaxis antibiotics

        Returns:
            List of FHIR MedicationAdministration resources
        """
        cutoff = datetime.now() - timedelta(hours=since_hours)
        params = {
            "subject": f"Patient/{patient_id}",
            "effective-time": f"ge{cutoff.isoformat()}",
            "status": "completed",
            "_count": 100,
        }

        admins = self._get_all_pages("MedicationAdministration", params)

        if prophylaxis_only:
            prophylaxis_meds = [
                "cefazolin", "vancomycin", "clindamycin", "metronidazole",
                "gentamicin", "cefoxitin", "ampicillin", "piperacillin",
            ]
            admins = [
                a for a in admins
                if any(
                    med in self._get_admin_medication_name(a).lower()
                    for med in prophylaxis_meds
                )
            ]

        return admins

    def get_patient(self, patient_id: str) -> Optional[dict]:
        """Get patient demographics."""
        try:
            return self._get(f"Patient/{patient_id}")
        except requests.HTTPError:
            return None

    def get_patient_weight(self, patient_id: str) -> Optional[float]:
        """
        Get patient's most recent weight in kg.

        Queries vital signs observations for body weight.
        """
        params = {
            "subject": f"Patient/{patient_id}",
            "code": "29463-7",  # LOINC for body weight
            "_sort": "-date",
            "_count": 1,
        }

        observations = self._get_all_pages("Observation", params)
        if not observations:
            return None

        obs = observations[0]
        value_quantity = obs.get("valueQuantity", {})
        value = value_quantity.get("value")
        unit = value_quantity.get("unit", "kg")

        if value is None:
            return None

        # Convert to kg if needed
        if unit.lower() in ["lb", "lbs", "[lb_av]"]:
            return value * 0.453592
        return float(value)

    def get_patient_allergies(self, patient_id: str) -> list[str]:
        """
        Get patient allergies, particularly beta-lactam allergies.

        Returns list of allergy names/categories.
        """
        params = {
            "patient": f"Patient/{patient_id}",
            "clinical-status": "active",
        }

        allergies = self._get_all_pages("AllergyIntolerance", params)

        result = []
        for allergy in allergies:
            # Get the allergy substance/code
            code = allergy.get("code", {})
            for coding in code.get("coding", []):
                if coding.get("display"):
                    result.append(coding["display"])
            if code.get("text"):
                result.append(code["text"])

        return result

    def has_beta_lactam_allergy(self, allergies: list[str]) -> bool:
        """Check if patient has beta-lactam allergy."""
        beta_lactam_keywords = [
            "penicillin", "amoxicillin", "ampicillin", "cephalosporin",
            "cefazolin", "ceftriaxone", "cefepime", "piperacillin",
            "beta-lactam", "β-lactam", "carbapenem", "meropenem",
        ]
        for allergy in allergies:
            allergy_lower = allergy.lower()
            if any(kw in allergy_lower for kw in beta_lactam_keywords):
                return True
        return False

    def build_surgical_case(
        self,
        procedure: dict,
        include_medications: bool = True,
    ) -> SurgicalCase:
        """
        Build a SurgicalCase from a FHIR Procedure resource.

        Args:
            procedure: FHIR Procedure resource
            include_medications: Whether to fetch medication data

        Returns:
            SurgicalCase with available data
        """
        # Extract patient ID
        patient_ref = procedure.get("subject", {}).get("reference", "")
        patient_id = patient_ref.replace("Patient/", "")

        # Extract CPT codes
        cpt_codes = []
        for coding in procedure.get("code", {}).get("coding", []):
            system = coding.get("system", "")
            if "cpt" in system.lower() or coding.get("code", "").isdigit():
                cpt_codes.append(coding.get("code"))

        # Determine procedure category from CPT
        category = ProcedureCategory.OTHER
        for cpt in cpt_codes:
            prefix = cpt[:3] if len(cpt) >= 3 else cpt
            if prefix in CPT_CATEGORY_HINTS:
                category = CPT_CATEGORY_HINTS[prefix]
                break

        # Extract timing
        performed = procedure.get("performedPeriod", {}) or procedure.get("performedDateTime")
        incision_time = None
        surgery_end = None

        if isinstance(performed, dict):
            if performed.get("start"):
                incision_time = datetime.fromisoformat(
                    performed["start"].replace("Z", "+00:00")
                )
            if performed.get("end"):
                surgery_end = datetime.fromisoformat(
                    performed["end"].replace("Z", "+00:00")
                )
        elif isinstance(performed, str):
            incision_time = datetime.fromisoformat(performed.replace("Z", "+00:00"))

        # Get patient data
        weight = None
        age = None
        allergies = []
        has_bl_allergy = False

        if patient_id:
            patient = self.get_patient(patient_id)
            if patient:
                # Calculate age
                birth_date = patient.get("birthDate")
                if birth_date:
                    birth = datetime.fromisoformat(birth_date)
                    age = (datetime.now() - birth).days / 365.25

            weight = self.get_patient_weight(patient_id)
            allergies = self.get_patient_allergies(patient_id)
            has_bl_allergy = self.has_beta_lactam_allergy(allergies)

        # Build case
        case = SurgicalCase(
            case_id=procedure.get("id", ""),
            patient_mrn=self._get_mrn(patient_id) if patient_id else "",
            encounter_id=self._extract_encounter_id(procedure),
            cpt_codes=cpt_codes,
            procedure_description=procedure.get("code", {}).get("text", ""),
            procedure_category=category,
            actual_incision_time=incision_time,
            surgery_end_time=surgery_end,
            patient_weight_kg=weight,
            patient_age_years=age,
            allergies=allergies,
            has_beta_lactam_allergy=has_bl_allergy,
        )

        # Add medications if requested
        if include_medications and patient_id:
            case.prophylaxis_orders = self._get_medication_orders_as_models(patient_id)
            case.prophylaxis_administrations = self._get_administrations_as_models(patient_id)

        return case

    def _get_medication_name(self, order: dict) -> str:
        """Extract medication name from MedicationRequest."""
        # Try medicationCodeableConcept first
        med_cc = order.get("medicationCodeableConcept", {})
        for coding in med_cc.get("coding", []):
            if coding.get("display"):
                return coding["display"]
        if med_cc.get("text"):
            return med_cc["text"]

        # Try medicationReference
        med_ref = order.get("medicationReference", {})
        if med_ref.get("display"):
            return med_ref["display"]

        return ""

    def _get_admin_medication_name(self, admin: dict) -> str:
        """Extract medication name from MedicationAdministration."""
        med_cc = admin.get("medicationCodeableConcept", {})
        for coding in med_cc.get("coding", []):
            if coding.get("display"):
                return coding["display"]
        if med_cc.get("text"):
            return med_cc["text"]

        med_ref = admin.get("medicationReference", {})
        if med_ref.get("display"):
            return med_ref["display"]

        return ""

    def _get_mrn(self, patient_id: str) -> str:
        """Get MRN from patient identifiers."""
        patient = self.get_patient(patient_id)
        if not patient:
            return patient_id

        for identifier in patient.get("identifier", []):
            if "mrn" in identifier.get("type", {}).get("coding", [{}])[0].get("code", "").lower():
                return identifier.get("value", patient_id)
            if "mr" in identifier.get("type", {}).get("text", "").lower():
                return identifier.get("value", patient_id)

        # Fallback to first identifier
        if patient.get("identifier"):
            return patient["identifier"][0].get("value", patient_id)

        return patient_id

    def _extract_encounter_id(self, procedure: dict) -> str:
        """Extract encounter ID from procedure."""
        encounter_ref = procedure.get("encounter", {}).get("reference", "")
        return encounter_ref.replace("Encounter/", "")

    def _get_medication_orders_as_models(self, patient_id: str) -> list[MedicationOrder]:
        """Get medication orders as model objects."""
        orders = self.get_medication_orders(patient_id)
        result = []

        for order in orders:
            # Extract dose
            dosage = order.get("dosageInstruction", [{}])[0]
            dose_quantity = dosage.get("doseAndRate", [{}])[0].get("doseQuantity", {})
            dose_mg = dose_quantity.get("value", 0)
            if dose_quantity.get("unit", "mg").lower() == "g":
                dose_mg *= 1000

            result.append(
                MedicationOrder(
                    order_id=order.get("id", ""),
                    medication_name=self._get_medication_name(order),
                    dose_mg=dose_mg,
                    route=dosage.get("route", {}).get("text", "IV"),
                    ordered_time=datetime.fromisoformat(
                        order.get("authoredOn", "").replace("Z", "+00:00")
                    ) if order.get("authoredOn") else datetime.now(),
                )
            )

        return result

    def _get_administrations_as_models(self, patient_id: str) -> list[MedicationAdministration]:
        """Get medication administrations as model objects."""
        admins = self.get_medication_administrations(patient_id)
        result = []

        for admin in admins:
            # Extract dose
            dosage = admin.get("dosage", {})
            dose = dosage.get("dose", {})
            dose_mg = dose.get("value", 0)
            if dose.get("unit", "mg").lower() == "g":
                dose_mg *= 1000

            # Extract time
            effective = admin.get("effectiveDateTime") or admin.get("effectivePeriod", {}).get("start")
            admin_time = datetime.now()
            if effective:
                admin_time = datetime.fromisoformat(effective.replace("Z", "+00:00"))

            result.append(
                MedicationAdministration(
                    admin_id=admin.get("id", ""),
                    medication_name=self._get_admin_medication_name(admin),
                    dose_mg=dose_mg,
                    route=dosage.get("route", {}).get("text", "IV"),
                    admin_time=admin_time,
                )
            )

        return result
