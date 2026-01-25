"""FHIR client for Drug-Bug Mismatch Detection.

Provides methods to query cultures with susceptibilities and current medications.
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

import requests

from .config import config
from .models import (
    Antibiotic,
    CultureWithSusceptibilities,
    Patient,
    Susceptibility,
)


class FHIRClient(ABC):
    """Abstract FHIR client - implement for different backends."""

    @abstractmethod
    def get(self, resource_path: str, params: dict | None = None) -> dict:
        """GET a FHIR resource or search."""
        pass

    @abstractmethod
    def post(self, resource_path: str, resource: dict) -> dict:
        """POST a FHIR resource."""
        pass

    def get_patient(self, patient_id: str) -> Optional[dict]:
        """Get a single patient by ID."""
        try:
            return self.get(f"Patient/{patient_id}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_active_medication_requests(self, patient_id: str) -> list[dict]:
        """Get active medication requests for a patient."""
        response = self.get("MedicationRequest", {
            "patient": patient_id,
            "status": "active",
        })
        return self._extract_entries(response)

    def get_recent_microbiology_reports(
        self,
        hours_back: int = 24,
        status: str = "final",
    ) -> list[dict]:
        """Get recent microbiology culture reports."""
        date_from = datetime.now() - timedelta(hours=hours_back)
        # Use 'MB' code for microbiology (v2-0074 diagnostic service section)
        params = {
            "category": "MB",
            "status": status,
            "date": f"ge{date_from.strftime('%Y-%m-%dT%H:%M:%S')}",
            "_count": "500",
        }
        response = self.get("DiagnosticReport", params)
        return self._extract_entries(response)

    def get_observations_for_report(self, report_id: str) -> list[dict]:
        """Get Observation resources linked to a DiagnosticReport."""
        # Observations can be linked via result array or derived-from
        response = self.get("Observation", {
            "derived-from": f"DiagnosticReport/{report_id}",
            "_count": "100",
        })
        observations = self._extract_entries(response)

        # Also try based-on reference
        if not observations:
            response = self.get("Observation", {
                "based-on": f"DiagnosticReport/{report_id}",
                "_count": "100",
            })
            observations = self._extract_entries(response)

        return observations

    def get_observation(self, observation_id: str) -> Optional[dict]:
        """Get a single Observation by ID."""
        try:
            return self.get(f"Observation/{observation_id}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    @staticmethod
    def _extract_entries(bundle: dict) -> list[dict]:
        """Extract resource entries from a FHIR Bundle."""
        if bundle.get("resourceType") != "Bundle":
            return []
        return [
            entry.get("resource", {})
            for entry in bundle.get("entry", [])
            if "resource" in entry
        ]


class HAPIFHIRClient(FHIRClient):
    """Client for local HAPI FHIR server (no auth required)."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or config.FHIR_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        })

    def get(self, resource_path: str, params: dict | None = None) -> dict:
        """GET request to FHIR server."""
        response = self.session.get(
            f"{self.base_url}/{resource_path}",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def post(self, resource_path: str, resource: dict) -> dict:
        """POST request to FHIR server."""
        response = self.session.post(
            f"{self.base_url}/{resource_path}",
            json=resource,
        )
        response.raise_for_status()
        return response.json()


class EpicFHIRClient(FHIRClient):
    """Client for Epic FHIR API (OAuth 2.0 backend auth)."""

    def __init__(
        self,
        base_url: str | None = None,
        client_id: str | None = None,
        private_key_path: str | None = None,
    ):
        self.base_url = base_url or config.EPIC_FHIR_BASE_URL
        self.client_id = client_id or config.EPIC_CLIENT_ID
        self.private_key_path = private_key_path or config.EPIC_PRIVATE_KEY_PATH

        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/fhir+json",
            "Content-Type": "application/fhir+json",
        })

        # Load private key
        self.private_key: str | None = None
        if self.private_key_path:
            with open(self.private_key_path) as f:
                self.private_key = f.read()

    def _get_token_url(self) -> str:
        """Derive token URL from FHIR base URL."""
        base = self.base_url.rsplit("/FHIR", 1)[0]
        return f"{base}/oauth2/token"

    def _get_access_token(self) -> str:
        """OAuth 2.0 JWT bearer flow for backend apps."""
        import jwt

        # Return cached token if still valid
        if self.access_token and self.token_expires_at:
            if self.token_expires_at > datetime.now():
                return self.access_token

        if not self.private_key:
            raise ValueError("Private key not loaded - cannot authenticate to Epic")

        token_url = self._get_token_url()
        now = int(time.time())

        # Build JWT assertion
        claims = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": token_url,
            "jti": f"{now}-{self.client_id}",
            "exp": now + 300,  # 5 minute expiry
        }

        assertion = jwt.encode(claims, self.private_key, algorithm="RS384")

        # Request access token
        response = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion,
            },
        )
        response.raise_for_status()

        token_data = response.json()
        self.access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)

        return self.access_token

    def get(self, resource_path: str, params: dict | None = None) -> dict:
        """GET request with OAuth authentication."""
        token = self._get_access_token()

        response = self.session.get(
            f"{self.base_url}/{resource_path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()

    def post(self, resource_path: str, resource: dict) -> dict:
        """POST request with OAuth authentication."""
        token = self._get_access_token()

        response = self.session.post(
            f"{self.base_url}/{resource_path}",
            json=resource,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


def get_fhir_client() -> FHIRClient:
    """Factory function - returns appropriate client based on config."""
    if config.is_epic_configured():
        print("Using Epic FHIR client")
        return EpicFHIRClient()
    else:
        print("Using local HAPI FHIR client")
        return HAPIFHIRClient()


class DrugBugFHIRClient:
    """High-level client for drug-bug mismatch queries."""

    def __init__(self, fhir_client: FHIRClient | None = None):
        self.fhir = fhir_client or get_fhir_client()

    def parse_patient(self, patient_resource: dict) -> Patient:
        """Parse FHIR Patient resource into model."""
        # Extract MRN
        mrn = "Unknown"
        for identifier in patient_resource.get("identifier", []):
            if "mrn" in identifier.get("system", "").lower():
                mrn = identifier.get("value", mrn)
                break
            mrn = identifier.get("value", mrn)

        # Extract name
        name = "Unknown"
        for name_entry in patient_resource.get("name", []):
            given = " ".join(name_entry.get("given", []))
            family = name_entry.get("family", "")
            name = f"{given} {family}".strip() or name
            break

        return Patient(
            fhir_id=patient_resource.get("id", ""),
            mrn=mrn,
            name=name,
            birth_date=patient_resource.get("birthDate"),
            gender=patient_resource.get("gender"),
        )

    def parse_medication_request(self, med_request: dict) -> Antibiotic:
        """Parse FHIR MedicationRequest into Antibiotic model."""
        medication_name = "Unknown"
        rxnorm_code = None

        # Extract medication info
        med_concept = med_request.get("medicationCodeableConcept", {})
        medication_name = med_concept.get("text", medication_name)

        for coding in med_concept.get("coding", []):
            if "rxnorm" in coding.get("system", "").lower():
                rxnorm_code = coding.get("code")
                if not medication_name or medication_name == "Unknown":
                    medication_name = coding.get("display", medication_name)

        # Extract route
        route = None
        for dosage in med_request.get("dosageInstruction", []):
            route_info = dosage.get("route", {})
            for coding in route_info.get("coding", []):
                route = coding.get("display")
                break

        return Antibiotic(
            fhir_id=med_request.get("id", ""),
            medication_name=medication_name,
            rxnorm_code=rxnorm_code,
            route=route,
            status=med_request.get("status", "active"),
        )

    def parse_susceptibility_observation(self, observation: dict) -> Optional[Susceptibility]:
        """Parse FHIR Observation into Susceptibility model."""
        # Get antibiotic name from code
        antibiotic = None
        code_concept = observation.get("code", {})
        antibiotic = code_concept.get("text")
        if not antibiotic:
            for coding in code_concept.get("coding", []):
                antibiotic = coding.get("display")
                if antibiotic:
                    break

        if not antibiotic:
            return None

        # Get interpretation (S/I/R)
        interpretation = None
        for interp in observation.get("interpretation", []):
            for coding in interp.get("coding", []):
                # Look for S, I, R codes
                code = coding.get("code", "")
                if code in ("S", "I", "R"):
                    interpretation = code
                    break
                # Also check display
                display = coding.get("display", "").upper()
                if display in ("SUSCEPTIBLE", "INTERMEDIATE", "RESISTANT"):
                    interpretation = display[0]  # S, I, or R
                    break

        # Also check valueCodeableConcept for interpretation
        if not interpretation:
            value_cc = observation.get("valueCodeableConcept", {})
            for coding in value_cc.get("coding", []):
                code = coding.get("code", "")
                if code in ("S", "I", "R"):
                    interpretation = code
                    break

        if not interpretation:
            return None

        # Get MIC value
        mic = None
        mic_units = None
        mic_text = None
        value_quantity = observation.get("valueQuantity", {})
        if value_quantity:
            mic = value_quantity.get("value")
            mic_units = value_quantity.get("unit")
            mic_text = f"{mic} {mic_units}" if mic is not None else None

        # Check for comparator (e.g., ">256", "<=0.5")
        comparator = value_quantity.get("comparator", "")
        if comparator and mic is not None:
            mic_text = f"{comparator}{mic} {mic_units or ''}"

        # Get organism from specimen or report reference
        organism = "Unknown"
        # Organism might be in a component or referenced specimen
        for component in observation.get("component", []):
            component_code = component.get("code", {}).get("text", "")
            if "organism" in component_code.lower():
                organism = component.get("valueCodeableConcept", {}).get("text", organism)

        return Susceptibility(
            organism=organism,
            antibiotic=antibiotic,
            interpretation=interpretation,
            mic=mic,
            mic_units=mic_units,
            mic_text=mic_text,
        )

    def get_cultures_with_susceptibilities(
        self,
        hours_back: int = 24,
    ) -> list[CultureWithSusceptibilities]:
        """Get recent cultures with their susceptibility results."""
        cultures = []

        # Get recent microbiology reports
        reports = self.fhir.get_recent_microbiology_reports(hours_back=hours_back)

        for report in reports:
            culture = self._parse_culture_report(report)
            if culture and culture.organism:
                cultures.append(culture)

        return cultures

    def _parse_culture_report(self, report: dict) -> Optional[CultureWithSusceptibilities]:
        """Parse a DiagnosticReport with its susceptibilities."""
        # Extract organism from conclusion or conclusionCode
        organism = None
        conclusion = report.get("conclusion", "")
        if conclusion:
            # Parse organism from conclusion (may contain gram stain and organism)
            parts = conclusion.split(".")
            for part in parts:
                if "gram" not in part.lower():
                    organism = part.strip()
                    break
            if not organism:
                organism = conclusion

        for code_entry in report.get("conclusionCode", []):
            text = code_entry.get("text", "")
            if text and "pending" not in text.lower():
                organism = text
            for coding in code_entry.get("coding", []):
                display = coding.get("display")
                if display and "pending" not in display.lower():
                    organism = display

        if not organism:
            return None

        # Extract patient reference
        patient_ref = report.get("subject", {}).get("reference", "")
        patient_id = patient_ref.replace("Patient/", "") if patient_ref else ""

        if not patient_id:
            return None

        # Parse dates
        collection_date = None
        resulted_date = None
        if report.get("effectiveDateTime"):
            try:
                collection_date = datetime.fromisoformat(
                    report["effectiveDateTime"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        if report.get("issued"):
            try:
                resulted_date = datetime.fromisoformat(
                    report["issued"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Get specimen type from multiple sources
        specimen_type = None

        # Try specimen array first
        specimen_refs = report.get("specimen", [])
        for spec_ref in specimen_refs:
            if "display" in spec_ref:
                specimen_type = spec_ref.get("display")
                break

        # Fallback: extract from code.text (e.g., "Blood Culture" -> "Blood")
        if not specimen_type:
            code_text = report.get("code", {}).get("text", "")
            if code_text:
                # Extract specimen type from culture name
                code_lower = code_text.lower()
                if "blood" in code_lower:
                    specimen_type = "Blood"
                elif "urine" in code_lower:
                    specimen_type = "Urine"
                elif "respiratory" in code_lower or "sputum" in code_lower:
                    specimen_type = "Respiratory"
                elif "wound" in code_lower:
                    specimen_type = "Wound"
                elif "csf" in code_lower or "cerebrospinal" in code_lower:
                    specimen_type = "CSF"
                elif "stool" in code_lower:
                    specimen_type = "Stool"

        # Fallback: check code.coding display
        if not specimen_type:
            for coding in report.get("code", {}).get("coding", []):
                display = coding.get("display", "").lower()
                if "blood" in display:
                    specimen_type = "Blood"
                    break
                elif "urine" in display:
                    specimen_type = "Urine"
                    break

        # Get susceptibility observations
        susceptibilities = []

        # Check result array for observation references
        for result in report.get("result", []):
            obs_ref = result.get("reference", "")
            if obs_ref:
                obs_id = obs_ref.replace("Observation/", "")
                obs = self.fhir.get_observation(obs_id)
                if obs:
                    susc = self.parse_susceptibility_observation(obs)
                    if susc:
                        susc.organism = organism  # Set organism from report
                        susceptibilities.append(susc)

        # Also query for linked observations
        report_id = report.get("id")
        if report_id:
            linked_obs = self.fhir.get_observations_for_report(report_id)
            for obs in linked_obs:
                susc = self.parse_susceptibility_observation(obs)
                if susc:
                    susc.organism = organism
                    # Avoid duplicates
                    if not any(s.antibiotic == susc.antibiotic for s in susceptibilities):
                        susceptibilities.append(susc)

        return CultureWithSusceptibilities(
            fhir_id=report.get("id", ""),
            patient_id=patient_id,
            organism=organism,
            collection_date=collection_date,
            resulted_date=resulted_date,
            specimen_type=specimen_type,
            susceptibilities=susceptibilities,
        )

    def get_patient(self, patient_id: str) -> Optional[Patient]:
        """Get patient information."""
        patient_resource = self.fhir.get_patient(patient_id)
        if patient_resource:
            return self.parse_patient(patient_resource)
        return None

    def get_current_antibiotics(self, patient_id: str) -> list[Antibiotic]:
        """Get current antibiotic orders for a patient."""
        med_requests = self.fhir.get_active_medication_requests(patient_id)
        antibiotics = []
        for mr in med_requests:
            abx = self.parse_medication_request(mr)
            # Only include if we have an RxNorm code (to match susceptibilities)
            if abx.rxnorm_code:
                antibiotics.append(abx)
        return antibiotics
