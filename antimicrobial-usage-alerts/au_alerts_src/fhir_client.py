"""FHIR client for Antimicrobial Usage Alerts.

Provides medication-focused queries for monitoring broad-spectrum
antibiotic usage duration and indication monitoring.
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

import requests

from .config import config
from .models import Patient, MedicationOrder

logger = logging.getLogger(__name__)


class FHIRClient(ABC):
    """Abstract FHIR client - implement for different backends."""

    @abstractmethod
    def get(self, resource_path: str, params: dict | None = None) -> dict:
        """GET a FHIR resource or search."""
        pass

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

    def get_patient(self, patient_id: str) -> Patient | None:
        """Get a patient by ID and convert to model."""
        try:
            resource = self.get(f"Patient/{patient_id}")
            return self._resource_to_patient(resource)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def get_active_medication_requests(
        self,
        rxnorm_codes: list[str] | None = None,
    ) -> list[dict]:
        """Get all active medication requests, optionally filtered by RxNorm codes.

        Args:
            rxnorm_codes: Optional list of RxNorm codes to filter by.
                         If None, returns all active medication requests.
        """
        params = {"status": "active", "_count": "500"}

        if rxnorm_codes:
            # FHIR uses code system|code format
            code_param = ",".join(
                f"http://www.nlm.nih.gov/research/umls/rxnorm|{code}"
                for code in rxnorm_codes
            )
            params["code"] = code_param

        response = self.get("MedicationRequest", params)
        return self._extract_entries(response)

    def get_monitored_medications(self) -> list[MedicationOrder]:
        """Get active medication requests for monitored broad-spectrum antibiotics."""
        rxnorm_codes = list(config.MONITORED_MEDICATIONS.keys())
        resources = self.get_active_medication_requests(rxnorm_codes)

        orders = []
        for resource in resources:
            order = self._resource_to_medication_order(resource)
            if order:
                orders.append(order)

        return orders

    def get_patient_medication_orders(self, patient_id: str) -> list[MedicationOrder]:
        """Get active monitored medications for a specific patient."""
        rxnorm_codes = list(config.MONITORED_MEDICATIONS.keys())

        params = {
            "patient": patient_id,
            "status": "active",
        }

        if rxnorm_codes:
            code_param = ",".join(
                f"http://www.nlm.nih.gov/research/umls/rxnorm|{code}"
                for code in rxnorm_codes
            )
            params["code"] = code_param

        response = self.get("MedicationRequest", params)
        resources = self._extract_entries(response)

        orders = []
        for resource in resources:
            order = self._resource_to_medication_order(resource)
            if order:
                orders.append(order)

        return orders

    def _resource_to_patient(self, resource: dict) -> Patient:
        """Convert FHIR Patient resource to Patient model."""
        # Extract name
        name = "Unknown"
        if names := resource.get("name", []):
            name_obj = names[0]
            given = " ".join(name_obj.get("given", []))
            family = name_obj.get("family", "")
            name = f"{given} {family}".strip() or "Unknown"

        # Extract MRN from identifiers
        mrn = ""
        for ident in resource.get("identifier", []):
            if ident.get("type", {}).get("coding", [{}])[0].get("code") == "MR":
                mrn = ident.get("value", "")
                break
        if not mrn:
            # Fall back to first identifier
            if resource.get("identifier"):
                mrn = resource["identifier"][0].get("value", "")

        # Extract location/department from extensions (if present)
        location = None
        department = None
        for ext in resource.get("extension", []):
            if "location" in ext.get("url", "").lower():
                location = ext.get("valueString")
            elif "department" in ext.get("url", "").lower():
                department = ext.get("valueString")

        return Patient(
            fhir_id=resource.get("id", ""),
            mrn=mrn,
            name=name,
            birth_date=resource.get("birthDate"),
            gender=resource.get("gender"),
            location=location,
            department=department,
        )

    def _resource_to_medication_order(self, resource: dict) -> MedicationOrder | None:
        """Convert FHIR MedicationRequest resource to MedicationOrder model."""
        # Extract medication coding
        med_coding = None
        rxnorm_code = None
        medication_name = None

        # Try medicationCodeableConcept first
        if med_concept := resource.get("medicationCodeableConcept"):
            for coding in med_concept.get("coding", []):
                if "rxnorm" in coding.get("system", "").lower():
                    rxnorm_code = coding.get("code")
                    medication_name = coding.get("display")
                    break
            # Fall back to text
            if not medication_name:
                medication_name = med_concept.get("text")

        # Check if this is a monitored medication
        if rxnorm_code and rxnorm_code not in config.MONITORED_MEDICATIONS:
            return None

        if not medication_name and rxnorm_code:
            medication_name = config.MONITORED_MEDICATIONS.get(rxnorm_code, "Unknown")

        if not medication_name:
            return None

        # Extract patient reference
        patient_ref = resource.get("subject", {}).get("reference", "")
        patient_id = patient_ref.replace("Patient/", "") if patient_ref else ""

        # Extract dosage info
        dose = None
        route = None
        if dosage_instructions := resource.get("dosageInstruction", []):
            dosage = dosage_instructions[0]
            if dose_quantity := dosage.get("doseAndRate", [{}])[0].get("doseQuantity"):
                dose = f"{dose_quantity.get('value', '')} {dose_quantity.get('unit', '')}".strip()
            if route_coding := dosage.get("route", {}).get("coding", [{}]):
                route = route_coding[0].get("display")

        # Extract start date from authoredOn or dispenseRequest.validityPeriod
        start_date = None
        if authored_on := resource.get("authoredOn"):
            try:
                # Handle different datetime formats
                if "T" in authored_on:
                    start_date = datetime.fromisoformat(authored_on.replace("Z", "+00:00"))
                else:
                    start_date = datetime.strptime(authored_on, "%Y-%m-%d")
            except ValueError:
                pass

        return MedicationOrder(
            fhir_id=resource.get("id", ""),
            patient_id=patient_id,
            medication_name=medication_name,
            rxnorm_code=rxnorm_code,
            dose=dose,
            route=route,
            start_date=start_date,
            status=resource.get("status", "active"),
        )

    def get_patient_conditions(self, patient_id: str) -> list[str]:
        """Get active ICD-10 codes for a patient.

        Args:
            patient_id: FHIR patient ID.

        Returns:
            List of ICD-10 codes.
        """
        params = {
            "patient": patient_id,
            "clinical-status": "active",
            "_count": "100",
        }

        try:
            response = self.get("Condition", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get conditions for patient {patient_id}: {e}")
            return []

        icd10_codes = []
        for resource in resources:
            for coding in resource.get("code", {}).get("coding", []):
                system = coding.get("system", "").lower()
                if "icd" in system or "i10" in system:
                    code = coding.get("code")
                    if code:
                        icd10_codes.append(code)

        return icd10_codes

    def get_recent_notes(
        self,
        patient_id: str,
        since_hours: int = 48,
        note_types: list[str] | None = None,
    ) -> list[dict]:
        """Get recent clinical notes for a patient.

        Args:
            patient_id: FHIR patient ID.
            since_hours: How far back to look for notes.
            note_types: Optional list of LOINC codes for note types to include.

        Returns:
            List of note dicts with 'type', 'date', 'author', and 'text' keys.
        """
        since_date = datetime.now() - timedelta(hours=since_hours)

        params = {
            "patient": patient_id,
            "date": f"ge{since_date.strftime('%Y-%m-%d')}",
            "_count": "50",
            "_sort": "-date",
        }

        # Filter by note type if specified
        # Common LOINC codes: 11506-3 (Progress note), 34117-2 (H&P), 28570-0 (Procedure note)
        if note_types:
            params["type"] = ",".join(note_types)

        try:
            response = self.get("DocumentReference", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get notes for patient {patient_id}: {e}")
            return []

        notes = []
        for resource in resources:
            note = self._extract_note_content(resource)
            if note:
                notes.append(note)

        return notes

    def _extract_note_content(self, resource: dict) -> dict | None:
        """Extract note content from a DocumentReference resource.

        Args:
            resource: FHIR DocumentReference resource.

        Returns:
            Dict with note details, or None if content can't be extracted.
        """
        # Get note type
        note_type = "Unknown"
        type_coding = resource.get("type", {}).get("coding", [])
        if type_coding:
            note_type = type_coding[0].get("display", type_coding[0].get("code", "Unknown"))

        # Get date
        note_date = resource.get("date") or resource.get("context", {}).get("period", {}).get("start")

        # Get author
        author = None
        authors = resource.get("author", [])
        if authors:
            author_ref = authors[0].get("display") or authors[0].get("reference", "")
            if author_ref:
                author = author_ref.replace("Practitioner/", "")

        # Get content
        text = None
        content_list = resource.get("content", [])
        for content in content_list:
            attachment = content.get("attachment", {})

            # Try to get inline data
            if data := attachment.get("data"):
                import base64
                try:
                    text = base64.b64decode(data).decode("utf-8")
                    break
                except Exception:
                    pass

            # Try to get from URL (would need to fetch)
            # For now, skip URL-based content
            if url := attachment.get("url"):
                logger.debug(f"Note has URL content: {url}")

        if not text:
            return None

        return {
            "type": note_type,
            "date": note_date,
            "author": author,
            "text": text,
        }

    def get_recent_medication_requests(
        self,
        since_hours: int = 24,
        rxnorm_codes: list[str] | None = None,
    ) -> list[MedicationOrder]:
        """Get medication requests from the past N hours.

        Args:
            since_hours: How far back to look for orders.
            rxnorm_codes: Optional list of RxNorm codes to filter by.

        Returns:
            List of MedicationOrder objects.
        """
        since_date = datetime.now() - timedelta(hours=since_hours)

        params = {
            "status": "active",
            "authoredon": f"ge{since_date.strftime('%Y-%m-%dT%H:%M:%S')}",
            "_count": "500",
        }

        if rxnorm_codes:
            code_param = ",".join(
                f"http://www.nlm.nih.gov/research/umls/rxnorm|{code}"
                for code in rxnorm_codes
            )
            params["code"] = code_param

        try:
            response = self.get("MedicationRequest", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get recent medication requests: {e}")
            return []

        orders = []
        for resource in resources:
            order = self._resource_to_medication_order_any(resource)
            if order:
                orders.append(order)

        return orders

    def _resource_to_medication_order_any(self, resource: dict) -> MedicationOrder | None:
        """Convert any MedicationRequest to MedicationOrder (not just monitored).

        Similar to _resource_to_medication_order but doesn't filter by
        MONITORED_MEDICATIONS. Used for indication monitoring which tracks
        all antibiotics.
        """
        rxnorm_code = None
        medication_name = None

        # Try medicationCodeableConcept first
        if med_concept := resource.get("medicationCodeableConcept"):
            for coding in med_concept.get("coding", []):
                if "rxnorm" in coding.get("system", "").lower():
                    rxnorm_code = coding.get("code")
                    medication_name = coding.get("display")
                    break
            # Fall back to text
            if not medication_name:
                medication_name = med_concept.get("text")

        if not medication_name:
            return None

        # Extract patient reference
        patient_ref = resource.get("subject", {}).get("reference", "")
        patient_id = patient_ref.replace("Patient/", "") if patient_ref else ""

        # Extract dosage info
        dose = None
        route = None
        if dosage_instructions := resource.get("dosageInstruction", []):
            dosage = dosage_instructions[0]
            if dose_quantity := dosage.get("doseAndRate", [{}])[0].get("doseQuantity"):
                dose = f"{dose_quantity.get('value', '')} {dose_quantity.get('unit', '')}".strip()
            if route_coding := dosage.get("route", {}).get("coding", [{}]):
                route = route_coding[0].get("display")

        # Extract start date
        start_date = None
        if authored_on := resource.get("authoredOn"):
            try:
                if "T" in authored_on:
                    start_date = datetime.fromisoformat(authored_on.replace("Z", "+00:00"))
                else:
                    start_date = datetime.strptime(authored_on, "%Y-%m-%d")
            except ValueError:
                pass

        return MedicationOrder(
            fhir_id=resource.get("id", ""),
            patient_id=patient_id,
            medication_name=medication_name,
            rxnorm_code=rxnorm_code,
            dose=dose,
            route=route,
            start_date=start_date,
            status=resource.get("status", "active"),
        )


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
            "exp": now + 300,
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


def get_fhir_client() -> FHIRClient:
    """Factory function - returns appropriate client based on config."""
    if config.is_epic_configured():
        print("Using Epic FHIR client")
        return EpicFHIRClient()
    else:
        print("Using local HAPI FHIR client")
        return HAPIFHIRClient()
