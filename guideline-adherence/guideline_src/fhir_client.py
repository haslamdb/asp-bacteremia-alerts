"""Extended FHIR client for guideline adherence monitoring.

Adds vital signs, medication administration, and enhanced lab queries
to the base FHIR client pattern.
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

import requests

from .config import config

logger = logging.getLogger(__name__)


class GuidelineFHIRClient(ABC):
    """Abstract FHIR client for guideline adherence monitoring."""

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

    @staticmethod
    def _parse_datetime(dt_str: str | None) -> datetime | None:
        """Parse FHIR datetime string to Python datetime."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(dt_str, "%Y-%m-%d")
            except ValueError:
                return None

    # -------------------------------------------------------------------------
    # Patient queries
    # -------------------------------------------------------------------------

    def get_patient(self, patient_id: str) -> dict | None:
        """Get patient by ID.

        Returns:
            Dict with patient info or None.
        """
        try:
            resource = self.get(f"Patient/{patient_id}")
            return self._resource_to_patient(resource)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise

    def _resource_to_patient(self, resource: dict) -> dict:
        """Convert FHIR Patient resource to dict."""
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
        if not mrn and resource.get("identifier"):
            mrn = resource["identifier"][0].get("value", "")

        return {
            "fhir_id": resource.get("id", ""),
            "mrn": mrn,
            "name": name,
            "birth_date": resource.get("birthDate"),
            "gender": resource.get("gender"),
        }

    # -------------------------------------------------------------------------
    # Condition queries (for identifying applicable bundles)
    # -------------------------------------------------------------------------

    def get_patient_conditions(self, patient_id: str) -> list[str]:
        """Get active ICD-10 codes for a patient.

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

    def get_sepsis_patients(self) -> list[dict]:
        """Find patients with active sepsis diagnoses.

        Returns:
            List of dicts with patient_id, encounter_id, condition_code, onset_time.
        """
        # Build ICD-10 code filter
        icd10_codes = []
        for prefix in config.SEPSIS_ICD10_PREFIXES:
            icd10_codes.append(f"http://hl7.org/fhir/sid/icd-10-cm|{prefix}")

        params = {
            "code": ",".join(icd10_codes),
            "clinical-status": "active",
            "_count": "200",
        }

        try:
            response = self.get("Condition", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get sepsis conditions: {e}")
            return []

        patients = []
        for resource in resources:
            patient_ref = resource.get("subject", {}).get("reference", "")
            patient_id = patient_ref.replace("Patient/", "") if patient_ref else ""

            encounter_ref = resource.get("encounter", {}).get("reference", "")
            encounter_id = encounter_ref.replace("Encounter/", "") if encounter_ref else ""

            # Get onset time
            onset = resource.get("onsetDateTime") or resource.get("recordedDate")
            onset_time = self._parse_datetime(onset)

            # Get ICD-10 code
            code = ""
            for coding in resource.get("code", {}).get("coding", []):
                if "icd" in coding.get("system", "").lower():
                    code = coding.get("code", "")
                    break

            if patient_id:
                patients.append({
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "condition_code": code,
                    "onset_time": onset_time,
                })

        return patients

    def get_patients_by_condition(
        self,
        icd10_prefixes: list[str],
        max_age_days: int | None = None,
        min_age_days: int | None = None,
    ) -> list[dict]:
        """Find patients with conditions matching ICD-10 prefixes.

        Args:
            icd10_prefixes: List of ICD-10 code prefixes to search for.
            max_age_days: Optional maximum patient age in days.
            min_age_days: Optional minimum patient age in days.

        Returns:
            List of dicts with patient_id, encounter_id, condition_code, onset_time, age_days.
        """
        # Build ICD-10 code filter
        icd10_codes = []
        for prefix in icd10_prefixes:
            icd10_codes.append(f"http://hl7.org/fhir/sid/icd-10-cm|{prefix}")

        params = {
            "code": ",".join(icd10_codes),
            "clinical-status": "active",
            "_count": "200",
        }

        try:
            response = self.get("Condition", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get conditions for ICD-10 {icd10_prefixes}: {e}")
            return []

        patients = []
        for resource in resources:
            patient_ref = resource.get("subject", {}).get("reference", "")
            patient_id = patient_ref.replace("Patient/", "") if patient_ref else ""

            if not patient_id:
                continue

            encounter_ref = resource.get("encounter", {}).get("reference", "")
            encounter_id = encounter_ref.replace("Encounter/", "") if encounter_ref else ""

            # Get onset time
            onset = resource.get("onsetDateTime") or resource.get("recordedDate")
            onset_time = self._parse_datetime(onset)

            # Get ICD-10 code
            code = ""
            for coding in resource.get("code", {}).get("coding", []):
                if "icd" in coding.get("system", "").lower():
                    code = coding.get("code", "")
                    break

            # Get patient age
            age_days = None
            try:
                patient = self.get_patient(patient_id)
                if patient and patient.get("birth_date"):
                    birth_str = patient["birth_date"]
                    if isinstance(birth_str, str):
                        birth_date = datetime.strptime(birth_str, "%Y-%m-%d").date()
                    else:
                        birth_date = birth_str
                    reference_date = (onset_time.date() if onset_time else datetime.now().date())
                    age_days = (reference_date - birth_date).days
            except Exception as e:
                logger.debug(f"Could not calculate age for patient {patient_id}: {e}")

            # Filter by age if specified
            if max_age_days is not None and age_days is not None:
                if age_days > max_age_days:
                    continue
            if min_age_days is not None and age_days is not None:
                if age_days < min_age_days:
                    continue

            patients.append({
                "patient_id": patient_id,
                "encounter_id": encounter_id,
                "condition_code": code,
                "onset_time": onset_time,
                "age_days": age_days,
            })

        return patients

    # -------------------------------------------------------------------------
    # Lab queries
    # -------------------------------------------------------------------------

    def get_lab_results(
        self,
        patient_id: str,
        loinc_codes: list[str],
        since_time: datetime | None = None,
        since_hours: int | None = None,
    ) -> list[dict]:
        """Get lab results for specific LOINC codes.

        Args:
            patient_id: FHIR patient ID.
            loinc_codes: List of LOINC codes to search for.
            since_time: Optional start time for search.
            since_hours: Optional hours back to search (alternative to since_time).

        Returns:
            List of dicts with loinc_code, value, unit, effective_time.
        """
        if since_hours and not since_time:
            since_time = datetime.now() - timedelta(hours=since_hours)

        params = {
            "patient": patient_id,
            "code": ",".join(f"http://loinc.org|{code}" for code in loinc_codes),
            "_count": "100",
            "_sort": "-date",
        }

        if since_time:
            params["date"] = f"ge{since_time.strftime('%Y-%m-%dT%H:%M:%S')}"

        try:
            response = self.get("Observation", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get lab results: {e}")
            return []

        results = []
        for resource in resources:
            # Get LOINC code
            loinc_code = ""
            for coding in resource.get("code", {}).get("coding", []):
                if "loinc" in coding.get("system", "").lower():
                    loinc_code = coding.get("code", "")
                    break

            # Get value
            value = None
            unit = None
            if value_qty := resource.get("valueQuantity"):
                value = value_qty.get("value")
                unit = value_qty.get("unit")
            elif value_str := resource.get("valueString"):
                value = value_str

            # Get effective time
            effective = resource.get("effectiveDateTime") or resource.get("issued")
            effective_time = self._parse_datetime(effective)

            results.append({
                "loinc_code": loinc_code,
                "value": value,
                "unit": unit,
                "effective_time": effective_time,
            })

        return results

    # -------------------------------------------------------------------------
    # Vital signs queries
    # -------------------------------------------------------------------------

    def get_vital_signs(
        self,
        patient_id: str,
        since_time: datetime | None = None,
        since_hours: int = 24,
    ) -> list[dict]:
        """Get vital signs (temperature, HR, RR, BP, SpO2).

        Args:
            patient_id: FHIR patient ID.
            since_time: Optional start time.
            since_hours: Hours back to search if since_time not provided.

        Returns:
            List of dicts with code, display, value, unit, effective_time.
        """
        if not since_time:
            since_time = datetime.now() - timedelta(hours=since_hours)

        params = {
            "patient": patient_id,
            "category": "vital-signs",
            "date": f"ge{since_time.strftime('%Y-%m-%dT%H:%M:%S')}",
            "_count": "200",
            "_sort": "-date",
        }

        try:
            response = self.get("Observation", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get vital signs: {e}")
            return []

        vitals = []
        for resource in resources:
            # Get code
            code = ""
            display = ""
            for coding in resource.get("code", {}).get("coding", []):
                code = coding.get("code", "")
                display = coding.get("display", "")
                break

            # Get value
            value = None
            unit = None
            if value_qty := resource.get("valueQuantity"):
                value = value_qty.get("value")
                unit = value_qty.get("unit")

            # Get effective time
            effective = resource.get("effectiveDateTime")
            effective_time = self._parse_datetime(effective)

            vitals.append({
                "code": code,
                "display": display,
                "value": value,
                "unit": unit,
                "effective_time": effective_time,
            })

        return vitals

    # -------------------------------------------------------------------------
    # Medication administration queries
    # -------------------------------------------------------------------------

    def get_medication_administrations(
        self,
        patient_id: str,
        since_time: datetime | None = None,
        since_hours: int = 24,
    ) -> list[dict]:
        """Get medication administrations (actual given times).

        Args:
            patient_id: FHIR patient ID.
            since_time: Optional start time.
            since_hours: Hours back to search.

        Returns:
            List of dicts with medication_name, dose, admin_time, status.
        """
        if not since_time:
            since_time = datetime.now() - timedelta(hours=since_hours)

        params = {
            "patient": patient_id,
            "effective-time": f"ge{since_time.strftime('%Y-%m-%dT%H:%M:%S')}",
            "_count": "200",
            "_sort": "-effective-time",
        }

        try:
            response = self.get("MedicationAdministration", params)
            resources = self._extract_entries(response)
        except Exception as e:
            logger.warning(f"Failed to get medication administrations: {e}")
            return []

        admins = []
        for resource in resources:
            # Get medication name
            med_name = ""
            if med_concept := resource.get("medicationCodeableConcept"):
                med_name = med_concept.get("text", "")
                if not med_name:
                    for coding in med_concept.get("coding", []):
                        med_name = coding.get("display", "")
                        if med_name:
                            break

            # Get dose
            dose = ""
            if dosage := resource.get("dosage"):
                if dose_qty := dosage.get("dose"):
                    dose = f"{dose_qty.get('value', '')} {dose_qty.get('unit', '')}".strip()

            # Get administration time
            admin_time = None
            if effective := resource.get("effectiveDateTime"):
                admin_time = self._parse_datetime(effective)
            elif effective_period := resource.get("effectivePeriod"):
                admin_time = self._parse_datetime(effective_period.get("start"))

            # Get route
            route = ""
            if dosage := resource.get("dosage"):
                if route_concept := dosage.get("route"):
                    route = route_concept.get("text", "")
                    if not route:
                        for coding in route_concept.get("coding", []):
                            route = coding.get("display", "")
                            if route:
                                break

            admins.append({
                "medication_name": med_name,
                "dose": dose,
                "admin_time": admin_time,
                "status": resource.get("status", ""),
                "route": route,
            })

        return admins

    # -------------------------------------------------------------------------
    # Clinical notes queries
    # -------------------------------------------------------------------------

    def get_recent_notes(
        self,
        patient_id: str,
        since_hours: int = 48,
        note_types: list[str] | None = None,
        since_time: datetime | None = None,
    ) -> list[dict]:
        """Get recent clinical notes.

        Args:
            patient_id: FHIR patient ID.
            since_hours: Hours back to search (if since_time not provided).
            note_types: Optional LOINC codes for note types.
            since_time: Optional specific start time.

        Returns:
            List of dicts with type, date, author, text.
        """
        if since_time:
            since_date = since_time
        else:
            since_date = datetime.now() - timedelta(hours=since_hours)

        params = {
            "patient": patient_id,
            "date": f"ge{since_date.strftime('%Y-%m-%d')}",
            "_count": "50",
            "_sort": "-date",
        }

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
        """Extract content from DocumentReference."""
        # Get type
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
            if data := attachment.get("data"):
                import base64
                try:
                    text = base64.b64decode(data).decode("utf-8")
                    break
                except Exception:
                    pass

        if not text:
            return None

        return {
            "type": note_type,
            "date": note_date,
            "author": author,
            "text": text,
        }


class HAPIGuidelineFHIRClient(GuidelineFHIRClient):
    """Client for local HAPI FHIR server."""

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


class EpicGuidelineFHIRClient(GuidelineFHIRClient):
    """Client for Epic FHIR API with OAuth 2.0."""

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

        self.private_key: str | None = None
        if self.private_key_path:
            with open(self.private_key_path) as f:
                self.private_key = f.read()

    def _get_token_url(self) -> str:
        """Derive token URL from FHIR base URL."""
        base = self.base_url.rsplit("/FHIR", 1)[0]
        return f"{base}/oauth2/token"

    def _get_access_token(self) -> str:
        """OAuth 2.0 JWT bearer flow."""
        import jwt

        if self.access_token and self.token_expires_at:
            if self.token_expires_at > datetime.now():
                return self.access_token

        if not self.private_key:
            raise ValueError("Private key not loaded")

        token_url = self._get_token_url()
        now = int(time.time())

        claims = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": token_url,
            "jti": f"{now}-{self.client_id}",
            "exp": now + 300,
        }

        assertion = jwt.encode(claims, self.private_key, algorithm="RS384")

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


def get_fhir_client() -> GuidelineFHIRClient:
    """Factory function - returns appropriate client based on config."""
    if config.is_epic_configured():
        logger.info("Using Epic FHIR client")
        return EpicGuidelineFHIRClient()
    else:
        logger.info("Using local HAPI FHIR client")
        return HAPIGuidelineFHIRClient()
