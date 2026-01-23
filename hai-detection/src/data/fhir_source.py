"""FHIR-based data source implementations."""

import logging
from datetime import datetime, timedelta

import requests

from ..config import Config
from ..models import ClinicalNote, DeviceInfo, CultureResult, Patient
from .base import BaseNoteSource, BaseDeviceSource, BaseCultureSource

logger = logging.getLogger(__name__)


class FHIRNoteSource(BaseNoteSource):
    """FHIR DocumentReference-based note retrieval."""

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or Config.get_fhir_base_url()
        self.session = requests.Session()

    def get_notes_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        note_types: list[str] | None = None,
    ) -> list[ClinicalNote]:
        """Retrieve clinical notes from FHIR DocumentReference."""
        notes = []

        params = {
            "patient": patient_id,
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
            "status": "current",
            "_count": Config.MAX_NOTES_PER_PATIENT,
        }

        # Add type filter if specified
        if note_types:
            # Map common types to FHIR document type codes
            type_codes = self._map_note_types_to_codes(note_types)
            if type_codes:
                params["type"] = ",".join(type_codes)

        try:
            response = self.session.get(
                f"{self.base_url}/DocumentReference",
                params=params,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                note = self._parse_document_reference(resource)
                if note:
                    notes.append(note)

        except requests.RequestException as e:
            logger.error(f"FHIR request failed: {e}")

        return notes

    def get_note_by_id(self, note_id: str) -> ClinicalNote | None:
        """Retrieve a specific DocumentReference by ID."""
        try:
            response = self.session.get(f"{self.base_url}/DocumentReference/{note_id}")
            response.raise_for_status()
            resource = response.json()
            return self._parse_document_reference(resource)
        except requests.RequestException as e:
            logger.error(f"Failed to fetch note {note_id}: {e}")
            return None

    def _parse_document_reference(self, resource: dict) -> ClinicalNote | None:
        """Parse FHIR DocumentReference to ClinicalNote."""
        try:
            note_id = resource.get("id")
            patient_ref = resource.get("subject", {}).get("reference", "")
            patient_id = patient_ref.split("/")[-1] if patient_ref else ""

            # Get note type from type coding
            note_type = "unknown"
            for coding in resource.get("type", {}).get("coding", []):
                if coding.get("display"):
                    note_type = self._normalize_note_type(coding.get("display"))
                    break

            # Get author
            author = None
            for auth in resource.get("author", []):
                if auth.get("display"):
                    author = auth.get("display")
                    break

            # Get date
            date_str = resource.get("date") or resource.get("context", {}).get("period", {}).get("start")
            note_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")) if date_str else datetime.now()

            # Get content - may be inline or a URL
            content = ""
            for content_item in resource.get("content", []):
                attachment = content_item.get("attachment", {})
                if attachment.get("data"):
                    # Base64 encoded content
                    import base64
                    content = base64.b64decode(attachment["data"]).decode("utf-8")
                elif attachment.get("url"):
                    # Fetch from URL
                    content = self._fetch_binary_content(attachment["url"])

            if not content:
                return None

            return ClinicalNote(
                id=note_id,
                patient_id=patient_id,
                note_type=note_type,
                author=author,
                date=note_date,
                content=content,
                source="fhir",
            )

        except Exception as e:
            logger.error(f"Failed to parse DocumentReference: {e}")
            return None

    def _fetch_binary_content(self, url: str) -> str:
        """Fetch binary content from a FHIR Binary resource URL."""
        try:
            # Handle relative URLs
            if url.startswith("/"):
                url = f"{self.base_url}{url}"
            elif not url.startswith("http"):
                url = f"{self.base_url}/{url}"

            response = self.session.get(url)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch binary content: {e}")
            return ""

    def _map_note_types_to_codes(self, note_types: list[str]) -> list[str]:
        """Map common note type names to LOINC codes."""
        type_map = {
            "progress_note": "11506-3",
            "id_consult": "11488-4",
            "discharge_summary": "18842-5",
            "h_and_p": "34117-2",
            "operative": "11504-8",
        }
        return [type_map[t] for t in note_types if t in type_map]

    def _normalize_note_type(self, display: str) -> str:
        """Normalize FHIR note type display to internal type."""
        display_lower = display.lower()
        if "progress" in display_lower:
            return "progress_note"
        if "consult" in display_lower and "id" in display_lower:
            return "id_consult"
        if "infectious" in display_lower:
            return "id_consult"
        if "discharge" in display_lower:
            return "discharge_summary"
        if "history" in display_lower and "physical" in display_lower:
            return "h_and_p"
        if "operative" in display_lower:
            return "operative"
        return "other"


class FHIRDeviceSource(BaseDeviceSource):
    """FHIR DeviceUseStatement-based device retrieval."""

    # Central line device type codes (SNOMED CT)
    CENTRAL_LINE_CODES = {
        "52124006",   # Central venous catheter
        "303728004",  # Peripherally inserted central catheter
        "706689003",  # Tunneled central venous catheter
        "706687001",  # Non-tunneled central venous catheter
    }

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or Config.get_fhir_base_url()
        self.session = requests.Session()

    def get_central_lines(
        self,
        patient_id: str,
        as_of_date: datetime,
    ) -> list[DeviceInfo]:
        """Get central lines present at a given date."""
        devices = []

        # Query DeviceUseStatement for the patient
        # Note: Don't filter by status as HAPI FHIR doesn't support multiple values well
        params = {
            "patient": patient_id,
        }

        try:
            response = self.session.get(
                f"{self.base_url}/DeviceUseStatement",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                # Skip entered-in-error status
                if resource.get("status") == "entered-in-error":
                    continue

                device = self._parse_device_use_statement(resource)

                if device and self._is_central_line(device):
                    # Check if line was present at as_of_date
                    if self._was_present_at_date(device, as_of_date):
                        devices.append(device)

        except requests.RequestException as e:
            logger.error(f"FHIR device query failed: {e}")

        return devices

    def get_active_devices(
        self,
        patient_id: str,
        device_types: list[str] | None = None,
    ) -> list[DeviceInfo]:
        """Get currently active devices."""
        devices = []

        params = {
            "patient": patient_id,
            "status": "active",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/DeviceUseStatement",
                params=params,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                device = self._parse_device_use_statement(resource)
                if device:
                    if device_types is None or device.device_type in device_types:
                        devices.append(device)

        except requests.RequestException as e:
            logger.error(f"FHIR device query failed: {e}")

        return devices

    def _parse_device_use_statement(self, resource: dict) -> DeviceInfo | None:
        """Parse FHIR DeviceUseStatement to DeviceInfo."""
        try:
            # Get device type from device reference or code
            device_type = "unknown"
            device_ref = resource.get("device", {})

            # Try to get from CodeableConcept in device field
            if isinstance(device_ref, dict) and device_ref.get("concept"):
                for coding in device_ref.get("concept", {}).get("coding", []):
                    device_type = self._normalize_device_type(
                        coding.get("code"), coding.get("display")
                    )
                    break

            # Get site from bodySite and infer device type if needed
            site = None
            body_site = resource.get("bodySite", {})
            for coding in body_site.get("coding", []):
                if coding.get("display"):
                    site = coding.get("display")
                # Infer device type from body site if not already set
                if device_type == "unknown" and coding.get("code"):
                    device_type = self._infer_device_type_from_site(coding.get("code"))

            # Get timing
            timing = resource.get("timingPeriod", {}) or resource.get("timing", {}).get("repeat", {}).get("boundsPeriod", {})
            insertion_date = None
            removal_date = None

            if timing.get("start"):
                insertion_date = datetime.fromisoformat(
                    timing["start"].replace("Z", "+00:00")
                )
            if timing.get("end"):
                removal_date = datetime.fromisoformat(
                    timing["end"].replace("Z", "+00:00")
                )

            return DeviceInfo(
                device_type=device_type,
                insertion_date=insertion_date,
                removal_date=removal_date,
                site=site,
                fhir_id=resource.get("id"),
            )

        except Exception as e:
            logger.error(f"Failed to parse DeviceUseStatement: {e}")
            return None

    def _infer_device_type_from_site(self, site_code: str) -> str:
        """Infer device type from body site code.

        Central line sites include subclavian, jugular, femoral veins and
        basilic vein (for PICC).
        """
        # SNOMED codes for central line insertion sites
        central_line_sites = {
            "20699002",   # Right subclavian vein
            "48345005",   # Left subclavian vein
            "83419000",   # Right internal jugular vein
            "12123001",   # Left internal jugular vein
            "7657000",    # Right femoral vein
            "83978002",   # Left femoral vein
        }
        picc_sites = {
            "50094009",   # Right basilic vein
            "789001",     # Left basilic vein
        }

        if site_code in picc_sites:
            return "picc"
        if site_code in central_line_sites:
            return "central_venous_catheter"
        return "unknown"

    def _is_central_line(self, device: DeviceInfo) -> bool:
        """Check if device is a central line."""
        central_line_types = {
            "central_venous_catheter",
            "picc",
            "tunneled_catheter",
            "non_tunneled_catheter",
            "central_line",
        }
        return device.device_type.lower() in central_line_types

    def _was_present_at_date(self, device: DeviceInfo, as_of_date: datetime) -> bool:
        """Check if device was present at a given date."""
        if device.insertion_date is None:
            return False

        # Was inserted before the date
        if device.insertion_date > as_of_date:
            return False

        # Either still in place or removed after the date
        if device.removal_date is None:
            return True

        # Allow for 1 day grace period after removal (NHSN criteria)
        grace_period = timedelta(days=Config.POST_REMOVAL_WINDOW_DAYS)
        return device.removal_date + grace_period >= as_of_date

    def _normalize_device_type(self, code: str | None, display: str | None) -> str:
        """Normalize device type to internal representation."""
        if code in self.CENTRAL_LINE_CODES:
            return "central_venous_catheter"

        if display:
            display_lower = display.lower()
            if "picc" in display_lower or "peripherally inserted" in display_lower:
                return "picc"
            if "tunneled" in display_lower:
                return "tunneled_catheter"
            if "central" in display_lower:
                return "central_venous_catheter"

        return "unknown"


class FHIRCultureSource(BaseCultureSource):
    """FHIR DiagnosticReport/Observation-based culture retrieval."""

    # LOINC codes for blood cultures
    BLOOD_CULTURE_CODES = {
        "600-7",    # Blood culture
        "17934-1",  # Blood culture aerobic
        "17935-8",  # Blood culture anaerobic
    }

    # LOINC codes for other culture types (to check for alternate sources)
    OTHER_CULTURE_CODES = {
        "630-4": "urine",       # Urine culture
        "6463-4": "urine",      # Bacteria identified in urine
        "43409-2": "respiratory",  # Respiratory culture
        "6460-0": "respiratory",   # Sputum culture
        "43411-8": "wound",     # Wound culture
        "6462-6": "wound",      # Bacteria in wound
        "43411-4": "abscess",   # Abscess culture
        "88184-0": "drain",     # Drain fluid culture
        "29574-4": "stool",     # Stool culture
    }

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or Config.get_fhir_base_url()
        self.session = requests.Session()

    def get_positive_blood_cultures(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[Patient, CultureResult]]:
        """Get positive blood cultures within a date range."""
        results = []

        # Query DiagnosticReport for blood cultures
        # Note: HAPI FHIR doesn't support conclusion search, so we filter locally
        params = {
            "code": ",".join(self.BLOOD_CULTURE_CODES),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
            "_include": "DiagnosticReport:subject",
            "_count": "100",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/DiagnosticReport",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            bundle = response.json()

            # Build patient lookup from included resources
            patients = {}
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Patient":
                    patient = self._parse_patient(resource)
                    if patient:
                        patients[patient.fhir_id] = patient

            # Parse DiagnosticReports and filter for positive results
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "DiagnosticReport":
                    culture = self._parse_diagnostic_report(resource)
                    if culture and culture.is_positive:
                        patient_ref = resource.get("subject", {}).get("reference", "")
                        patient_id = patient_ref.split("/")[-1]
                        patient = patients.get(patient_id)

                        if patient:
                            results.append((patient, culture))
                        else:
                            # Fetch patient if not included
                            patient = self._fetch_patient(patient_id)
                            if patient:
                                results.append((patient, culture))

            logger.info(f"Found {len(results)} positive blood cultures from {len(bundle.get('entry', []))} total reports")

        except requests.RequestException as e:
            logger.error(f"FHIR culture query failed: {e}")

        return results

    def get_cultures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CultureResult]:
        """Get all cultures (blood, wound, urine, etc.) for a specific patient."""
        results = []

        # Combine blood and other culture codes to get all cultures
        all_culture_codes = set(self.BLOOD_CULTURE_CODES) | set(self.OTHER_CULTURE_CODES.keys())

        params = {
            "patient": patient_id,
            "code": ",".join(all_culture_codes),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
        }

        try:
            response = self.session.get(
                f"{self.base_url}/DiagnosticReport",
                params=params,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "DiagnosticReport":
                    culture = self._parse_diagnostic_report(resource)
                    if culture:
                        results.append(culture)

        except requests.RequestException as e:
            logger.error(f"FHIR culture query failed: {e}")

        return results

    def _parse_diagnostic_report(self, resource: dict) -> CultureResult | None:
        """Parse FHIR DiagnosticReport to CultureResult."""
        try:
            fhir_id = resource.get("id")

            # Get collection date
            effective = resource.get("effectiveDateTime") or resource.get("effectivePeriod", {}).get("start")
            if not effective:
                return None
            collection_date = datetime.fromisoformat(effective.replace("Z", "+00:00"))

            # Get result date
            issued = resource.get("issued")
            result_date = datetime.fromisoformat(issued.replace("Z", "+00:00")) if issued else None

            # Determine specimen source from LOINC code
            specimen_source = "blood"  # Default
            for coding in resource.get("code", {}).get("coding", []):
                loinc_code = coding.get("code")
                if loinc_code in self.BLOOD_CULTURE_CODES:
                    specimen_source = "blood"
                    break
                elif loinc_code in self.OTHER_CULTURE_CODES:
                    specimen_source = self.OTHER_CULTURE_CODES[loinc_code]
                    break
                # Also check display text for wound-related terms
                display = coding.get("display", "").lower()
                if "wound" in display:
                    specimen_source = "wound"
                elif "urine" in display:
                    specimen_source = "urine"
                elif "respiratory" in display or "sputum" in display:
                    specimen_source = "respiratory"
                elif "abscess" in display:
                    specimen_source = "abscess"
                elif "drain" in display:
                    specimen_source = "drain"
                elif "tissue" in display:
                    specimen_source = "tissue"

            # Determine if positive and get organism
            is_positive = False
            organism = None

            conclusion = resource.get("conclusion", "")
            if conclusion:
                is_positive = "positive" in conclusion.lower() or "growth" in conclusion.lower()

            # Try to extract organism from conclusion codes
            for cc in resource.get("conclusionCode", []):
                for coding in cc.get("coding", []):
                    if coding.get("display"):
                        organism = coding.get("display")
                        is_positive = True
                        break

            return CultureResult(
                fhir_id=fhir_id,
                collection_date=collection_date,
                organism=organism,
                result_date=result_date,
                specimen_source=specimen_source,
                is_positive=is_positive,
            )

        except Exception as e:
            logger.error(f"Failed to parse DiagnosticReport: {e}")
            return None

    def _parse_patient(self, resource: dict) -> Patient | None:
        """Parse FHIR Patient resource."""
        try:
            fhir_id = resource.get("id")

            # Get MRN from identifiers
            mrn = ""
            for identifier in resource.get("identifier", []):
                type_coding = identifier.get("type", {}).get("coding", [])
                for coding in type_coding:
                    if coding.get("code") == "MR":
                        mrn = identifier.get("value", "")
                        break
                if mrn:
                    break

            # Get name
            name = ""
            for name_obj in resource.get("name", []):
                if name_obj.get("use") == "official" or not name:
                    given = " ".join(name_obj.get("given", []))
                    family = name_obj.get("family", "")
                    name = f"{given} {family}".strip()

            # Get birth date
            birth_date = resource.get("birthDate")

            return Patient(
                fhir_id=fhir_id,
                mrn=mrn,
                name=name,
                birth_date=birth_date,
            )

        except Exception as e:
            logger.error(f"Failed to parse Patient: {e}")
            return None

    def _fetch_patient(self, patient_id: str) -> Patient | None:
        """Fetch a patient by ID."""
        try:
            response = self.session.get(f"{self.base_url}/Patient/{patient_id}")
            response.raise_for_status()
            return self._parse_patient(response.json())
        except requests.RequestException as e:
            logger.error(f"Failed to fetch patient {patient_id}: {e}")
            return None

    def get_other_cultures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CultureResult]:
        """Get non-blood cultures for a patient (urine, respiratory, wound, etc.).

        Used to identify potential alternative sources for BSI when the same
        organism is found at another site.
        """
        results = []

        params = {
            "patient": patient_id,
            "code": ",".join(self.OTHER_CULTURE_CODES.keys()),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
            "_count": "50",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/DiagnosticReport",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "DiagnosticReport":
                    culture = self._parse_other_culture(resource)
                    if culture and culture.is_positive:
                        results.append(culture)

        except requests.RequestException as e:
            logger.error(f"FHIR other culture query failed: {e}")

        return results

    def _parse_other_culture(self, resource: dict) -> CultureResult | None:
        """Parse a non-blood culture DiagnosticReport."""
        try:
            fhir_id = resource.get("id")

            # Get collection date
            effective = resource.get("effectiveDateTime") or resource.get("effectivePeriod", {}).get("start")
            if not effective:
                return None
            collection_date = datetime.fromisoformat(effective.replace("Z", "+00:00"))

            # Determine specimen source from code
            specimen_source = "other"
            for coding in resource.get("code", {}).get("coding", []):
                code = coding.get("code")
                if code in self.OTHER_CULTURE_CODES:
                    specimen_source = self.OTHER_CULTURE_CODES[code]
                    break

            # Get result date
            issued = resource.get("issued")
            result_date = datetime.fromisoformat(issued.replace("Z", "+00:00")) if issued else None

            # Determine if positive and get organism
            is_positive = False
            organism = None

            conclusion = resource.get("conclusion", "")
            if conclusion:
                is_positive = "positive" in conclusion.lower() or "growth" in conclusion.lower()

            # Try to extract organism from conclusion codes
            for cc in resource.get("conclusionCode", []):
                for coding in cc.get("coding", []):
                    if coding.get("display"):
                        organism = coding.get("display")
                        is_positive = True
                        break

            return CultureResult(
                fhir_id=fhir_id,
                collection_date=collection_date,
                organism=organism,
                result_date=result_date,
                specimen_source=specimen_source,
                is_positive=is_positive,
            )

        except Exception as e:
            logger.error(f"Failed to parse other culture: {e}")
            return None

    def find_matching_organisms(
        self,
        patient_id: str,
        blood_culture_organism: str,
        blood_culture_date: datetime,
        window_days: int = 7,
    ) -> list[CultureResult]:
        """Find cultures from other sites with the same organism.

        This helps identify if the BSI is secondary to another infection source.
        For example, if both blood and urine grow E. coli, the BSI may be
        secondary to a UTI rather than a CLABSI.

        Args:
            patient_id: FHIR patient ID
            blood_culture_organism: Organism from the blood culture
            blood_culture_date: Date of the blood culture
            window_days: Days before/after blood culture to search

        Returns:
            List of cultures from other sites with matching organisms
        """
        if not blood_culture_organism:
            return []

        start_date = blood_culture_date - timedelta(days=window_days)
        end_date = blood_culture_date + timedelta(days=window_days)

        other_cultures = self.get_other_cultures_for_patient(patient_id, start_date, end_date)

        # Normalize organism name for comparison
        bsi_organism_lower = blood_culture_organism.lower()

        matching = []
        for culture in other_cultures:
            if culture.organism:
                # Check for organism match (case-insensitive, partial match)
                culture_organism_lower = culture.organism.lower()
                if (bsi_organism_lower in culture_organism_lower or
                    culture_organism_lower in bsi_organism_lower):
                    matching.append(culture)

        return matching
