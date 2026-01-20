"""FHIR service for querying culture and medication data."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import requests


@dataclass
class Susceptibility:
    """Antibiotic susceptibility result."""
    antibiotic: str
    result: str  # S, I, R
    result_display: str  # Susceptible, Intermediate, Resistant
    mic: Optional[str] = None


@dataclass
class CultureResult:
    """Blood culture result with susceptibilities."""
    id: str
    patient_id: str
    patient_name: str
    patient_mrn: str
    organism: str
    organism_code: Optional[str]
    collected_at: Optional[datetime]
    resulted_at: Optional[datetime]
    susceptibilities: list[Susceptibility]


@dataclass
class Medication:
    """Active medication order."""
    id: str
    name: str
    code: Optional[str]
    status: str
    ordered_at: Optional[datetime]
    dose: Optional[str] = None
    route: Optional[str] = None


class FHIRService:
    """Service for FHIR queries from the dashboard."""

    # Common antibiotic keywords to identify antibiotics vs other medications
    ANTIBIOTIC_KEYWORDS = [
        "cillin", "mycin", "cycline", "floxacin", "azole", "oxacin",
        "sulfa", "meropenem", "imipenem", "cef", "pen", "vancomycin",
        "daptomycin", "linezolid", "metronidazole", "clindamycin",
        "azithromycin", "amoxicillin", "ampicillin", "ceftriaxone",
        "cefepime", "cefazolin", "piperacillin", "tazobactam",
        "gentamicin", "tobramycin", "amikacin", "levofloxacin",
        "ciprofloxacin", "moxifloxacin", "doxycycline", "minocycline",
        "trimethoprim", "sulfamethoxazole", "nitrofurantoin",
        "fosfomycin", "tigecycline", "colistin", "polymyxin",
        "rifampin", "micafungin", "caspofungin", "fluconazole",
        "voriconazole", "amphotericin", "nafcillin", "oxacillin",
        "dicloxacillin", "ceftazidime", "ceftaroline", "ertapenem",
        "doripenem", "aztreonam",
    ]

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        })

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """Make a GET request to the FHIR server."""
        try:
            response = self.session.get(
                f"{self.base_url}/{path}",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"FHIR request error: {e}")
            return None

    def _extract_entries(self, bundle: dict) -> list[dict]:
        """Extract resources from a FHIR Bundle."""
        if not bundle or bundle.get("resourceType") != "Bundle":
            return []
        return [
            entry.get("resource", {})
            for entry in bundle.get("entry", [])
            if "resource" in entry
        ]

    def get_culture_with_susceptibilities(self, culture_id: str) -> CultureResult | None:
        """Get a blood culture DiagnosticReport with its susceptibility results.

        Args:
            culture_id: The DiagnosticReport FHIR resource ID

        Returns:
            CultureResult with susceptibilities, or None if not found
        """
        # Get the DiagnosticReport
        report = self._get(f"DiagnosticReport/{culture_id}")
        if not report:
            return None

        # Extract patient reference
        patient_ref = report.get("subject", {}).get("reference", "")
        patient_id = patient_ref.replace("Patient/", "") if patient_ref else ""

        # Get patient details
        patient_name = "Unknown"
        patient_mrn = "Unknown"
        if patient_id:
            patient = self._get(f"Patient/{patient_id}")
            if patient:
                # Extract name
                names = patient.get("name", [])
                if names:
                    name = names[0]
                    given = " ".join(name.get("given", []))
                    family = name.get("family", "")
                    patient_name = f"{given} {family}".strip() or "Unknown"

                # Extract MRN
                for ident in patient.get("identifier", []):
                    type_coding = ident.get("type", {}).get("coding", [])
                    for coding in type_coding:
                        if coding.get("code") == "MR":
                            patient_mrn = ident.get("value", "Unknown")
                            break

        # Extract organism from conclusionCode
        organism = report.get("conclusion", "Unknown organism")
        organism_code = None
        conclusion_codes = report.get("conclusionCode", [])
        if conclusion_codes:
            coding = conclusion_codes[0].get("coding", [])
            if coding:
                organism = coding[0].get("display", organism)
                organism_code = coding[0].get("code")

        # Parse dates
        collected_at = None
        resulted_at = None
        if report.get("effectiveDateTime"):
            try:
                collected_at = datetime.fromisoformat(
                    report["effectiveDateTime"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        if report.get("issued"):
            try:
                resulted_at = datetime.fromisoformat(
                    report["issued"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Get susceptibility Observations
        # These are linked via note field containing "Culture: {culture_id}"
        susceptibilities = self._get_susceptibilities_for_culture(culture_id)

        return CultureResult(
            id=culture_id,
            patient_id=patient_id,
            patient_name=patient_name,
            patient_mrn=patient_mrn,
            organism=organism,
            organism_code=organism_code,
            collected_at=collected_at,
            resulted_at=resulted_at,
            susceptibilities=susceptibilities,
        )

    def _get_susceptibilities_for_culture(self, culture_id: str) -> list[Susceptibility]:
        """Get susceptibility Observations for a culture.

        In our demo data, these are linked via note field.
        In Epic, they would be linked via DiagnosticReport.result references.
        """
        susceptibilities = []

        # Search for Observations that reference this culture in notes
        # This is a workaround since HAPI FHIR doesn't support derivedFrom to DiagnosticReport
        # We search for lab Observations and filter by note content
        bundle = self._get("Observation", {
            "category": "laboratory",
            "_count": "100",
        })

        observations = self._extract_entries(bundle)

        for obs in observations:
            # Check if this observation references our culture in the note
            notes = obs.get("note", [])
            culture_match = False
            for note in notes:
                if note.get("text", "").startswith(f"Culture: {culture_id}"):
                    culture_match = True
                    break

            if not culture_match:
                continue

            # Extract antibiotic name from code
            code_text = obs.get("code", {}).get("text", "")
            antibiotic = code_text.replace(" Susceptibility", "")
            if not antibiotic:
                coding = obs.get("code", {}).get("coding", [])
                if coding:
                    antibiotic = coding[0].get("display", "Unknown")
                    antibiotic = antibiotic.replace(" [Susceptibility]", "")

            # Extract S/I/R result
            result = "?"
            result_display = "Unknown"
            interpretations = obs.get("interpretation", [])
            if interpretations:
                coding = interpretations[0].get("coding", [])
                if coding:
                    result = coding[0].get("code", "?")
                    result_display = coding[0].get("display", "Unknown")

            # Extract MIC value from component
            mic = None
            for component in obs.get("component", []):
                comp_code = component.get("code", {}).get("text", "")
                if comp_code == "MIC":
                    mic = component.get("valueString")
                    break

            susceptibilities.append(Susceptibility(
                antibiotic=antibiotic,
                result=result,
                result_display=result_display,
                mic=mic,
            ))

        # Sort by antibiotic name
        susceptibilities.sort(key=lambda s: s.antibiotic.lower())
        return susceptibilities

    def get_patient_medications(
        self,
        patient_id: str,
        antibiotics_only: bool = True,
        include_statuses: list[str] | None = None,
    ) -> list[Medication]:
        """Get medications for a patient.

        Args:
            patient_id: FHIR Patient resource ID
            antibiotics_only: If True, filter to likely antibiotics
            include_statuses: List of statuses to include (default: active, on-hold)

        Returns:
            List of Medication objects
        """
        if include_statuses is None:
            include_statuses = ["active", "on-hold"]

        medications = []

        for status in include_statuses:
            bundle = self._get("MedicationRequest", {
                "patient": patient_id,
                "status": status,
                "_count": "100",
            })

            for resource in self._extract_entries(bundle):
                # Extract medication name
                med_name = "Unknown"
                med_code = None
                med_concept = resource.get("medicationCodeableConcept", {})
                if med_concept:
                    med_name = med_concept.get("text", "")
                    coding = med_concept.get("coding", [])
                    if coding:
                        if not med_name:
                            med_name = coding[0].get("display", "Unknown")
                        med_code = coding[0].get("code")

                # Filter to antibiotics if requested
                if antibiotics_only:
                    name_lower = med_name.lower()
                    is_antibiotic = any(
                        kw in name_lower for kw in self.ANTIBIOTIC_KEYWORDS
                    )
                    if not is_antibiotic:
                        continue

                # Parse ordered date
                ordered_at = None
                if resource.get("authoredOn"):
                    try:
                        ordered_at = datetime.fromisoformat(
                            resource["authoredOn"].replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        pass

                # Extract dosage info if available
                dose = None
                route = None
                dosage_instructions = resource.get("dosageInstruction", [])
                if dosage_instructions:
                    di = dosage_instructions[0]
                    dose_qty = di.get("doseAndRate", [{}])[0].get("doseQuantity", {})
                    if dose_qty:
                        dose = f"{dose_qty.get('value', '')} {dose_qty.get('unit', '')}".strip()
                    route_coding = di.get("route", {}).get("coding", [])
                    if route_coding:
                        route = route_coding[0].get("display")

                medications.append(Medication(
                    id=resource.get("id", ""),
                    name=med_name,
                    code=med_code,
                    status=resource.get("status", "unknown"),
                    ordered_at=ordered_at,
                    dose=dose,
                    route=route,
                ))

        # Sort by name
        medications.sort(key=lambda m: m.name.lower())
        return medications
