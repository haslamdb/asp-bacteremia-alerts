"""FHIR-based data source implementations."""

import logging
from datetime import datetime, timedelta, date

import requests

from ..config import Config
from ..models import (
    ClinicalNote, DeviceInfo, CultureResult, Patient,
    VentilationEpisode, DailyVentParameters,
)
from .base import BaseNoteSource, BaseDeviceSource, BaseCultureSource, BaseVentilatorSource

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


class FHIRVentilatorSource(BaseVentilatorSource):
    """FHIR-based mechanical ventilation data retrieval for VAE surveillance.

    Uses FHIR Procedure, DeviceUseStatement, and Observation resources to:
    - Identify patients on mechanical ventilation
    - Track ventilation episodes (intubation to extubation)
    - Retrieve daily FiO2 and PEEP parameters
    """

    # SNOMED codes for mechanical ventilation procedures
    MECHANICAL_VENTILATION_CODES = {
        "40617009",   # Artificial respiration (procedure)
        "243141005",  # Mechanically assisted spontaneous ventilation
        "243147009",  # Controlled mechanical ventilation
        "243148004",  # Synchronized intermittent mandatory ventilation
        "243150007",  # Assisted controlled mandatory ventilation
        "243151006",  # Controlled mandatory ventilation
        "428311008",  # Non-invasive ventilation
        "371907003",  # Oxygen administration by nasal cannula (for FiO2 context)
    }

    # SNOMED codes for endotracheal/tracheostomy devices
    VENTILATOR_DEVICE_CODES = {
        "129121000",  # Endotracheal tube
        "270902009",  # Tracheostomy tube
        "426854004",  # Ventilator device
        "706172005",  # Breathing circuit
    }

    # LOINC codes for ventilator parameters
    FIO2_LOINC_CODES = [
        "3150-0",     # Inhaled oxygen concentration
        "19994-3",    # Oxygen/Total gas setting Ventilator
    ]

    PEEP_LOINC_CODES = [
        "76530-5",    # PEEP Respiratory system by Ventilator
        "20077-4",    # Positive end expiratory pressure setting Ventilator
    ]

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or Config.get_fhir_base_url()
        self.session = requests.Session()

    def get_ventilated_patients(
        self,
        start_date: datetime,
        end_date: datetime,
        min_vent_days: int = 2,
    ) -> list[tuple[Patient, VentilationEpisode]]:
        """Get patients on mechanical ventilation within a date range.

        Queries FHIR Procedure resources for mechanical ventilation procedures
        and filters to patients with at least min_vent_days on the ventilator.
        """
        results = []

        # Query Procedure resources for mechanical ventilation
        params = {
            "code": ",".join(self.MECHANICAL_VENTILATION_CODES),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
            "_include": "Procedure:subject",
            "_count": "100",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/Procedure",
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

            # Parse Procedure resources to find ventilation episodes
            episodes_by_patient = {}
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Procedure":
                    episode = self._parse_ventilation_procedure(resource)
                    if episode:
                        patient_id = episode.patient_id
                        if patient_id not in episodes_by_patient:
                            episodes_by_patient[patient_id] = []
                        episodes_by_patient[patient_id].append(episode)

            # Filter to episodes with minimum vent days and build results
            for patient_id, episodes in episodes_by_patient.items():
                patient = patients.get(patient_id)
                if not patient:
                    patient = self._fetch_patient(patient_id)

                if patient:
                    for episode in episodes:
                        vent_days = episode.get_ventilator_days()
                        if vent_days >= min_vent_days:
                            results.append((patient, episode))

            logger.info(f"Found {len(results)} ventilated patients meeting criteria")

        except requests.RequestException as e:
            logger.error(f"FHIR ventilation query failed: {e}")

        return results

    def get_daily_vent_parameters(
        self,
        episode_id: str,
        start_date: date,
        end_date: date,
    ) -> list[DailyVentParameters]:
        """Get daily ventilator parameters for a ventilation episode.

        Queries FHIR Observation resources for FiO2 and PEEP values,
        calculates the minimum for each calendar day.
        """
        results = []

        # We need the patient_id from the episode to query observations
        # For now, episode_id contains patient info in format "patient_id:intubation_date"
        parts = episode_id.split(":")
        if len(parts) < 1:
            return results

        patient_id = parts[0]

        # Query FiO2 observations
        fio2_by_date = self._get_daily_min_observations(
            patient_id,
            self.FIO2_LOINC_CODES,
            start_date,
            end_date,
        )

        # Query PEEP observations
        peep_by_date = self._get_daily_min_observations(
            patient_id,
            self.PEEP_LOINC_CODES,
            start_date,
            end_date,
        )

        # Merge FiO2 and PEEP data by date
        all_dates = set(fio2_by_date.keys()) | set(peep_by_date.keys())

        for day_date in sorted(all_dates):
            fio2_data = fio2_by_date.get(day_date, {})
            peep_data = peep_by_date.get(day_date, {})

            # Calculate ventilator day (1-based from start of episode)
            intubation_date = datetime.fromisoformat(parts[1]).date() if len(parts) > 1 else start_date
            vent_day = (day_date - intubation_date).days + 1

            param = DailyVentParameters(
                episode_id=episode_id,
                date=day_date,
                ventilator_day=vent_day,
                min_fio2=fio2_data.get("value"),
                min_peep=peep_data.get("value"),
                fio2_observation_id=fio2_data.get("id"),
                peep_observation_id=peep_data.get("id"),
            )
            results.append(param)

        return results

    def get_ventilation_episodes_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[VentilationEpisode]:
        """Get ventilation episodes for a specific patient."""
        results = []

        params = {
            "patient": patient_id,
            "code": ",".join(self.MECHANICAL_VENTILATION_CODES),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
        }

        try:
            response = self.session.get(
                f"{self.base_url}/Procedure",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Procedure":
                    episode = self._parse_ventilation_procedure(resource)
                    if episode:
                        results.append(episode)

        except requests.RequestException as e:
            logger.error(f"FHIR ventilation episodes query failed: {e}")

        return results

    def _parse_ventilation_procedure(self, resource: dict) -> VentilationEpisode | None:
        """Parse a FHIR Procedure resource to VentilationEpisode."""
        try:
            fhir_id = resource.get("id")

            # Get patient reference
            subject_ref = resource.get("subject", {}).get("reference", "")
            patient_id = subject_ref.split("/")[-1] if subject_ref else ""

            if not patient_id:
                return None

            # Get timing from performedPeriod
            performed = resource.get("performedPeriod", {})
            start_str = performed.get("start")
            end_str = performed.get("end")

            if not start_str:
                # Try performedDateTime for point-in-time procedures
                performed_dt = resource.get("performedDateTime")
                if performed_dt:
                    start_str = performed_dt
                else:
                    return None

            intubation_date = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            extubation_date = None
            if end_str:
                extubation_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

            # Get encounter reference
            encounter_ref = resource.get("encounter", {}).get("reference", "")
            encounter_id = encounter_ref.split("/")[-1] if encounter_ref else None

            # Get location from encounter if available
            location_code = None
            if encounter_id:
                location_code = self._get_encounter_location(encounter_id)

            # Generate episode ID
            episode_id = f"{patient_id}:{intubation_date.isoformat()}"

            # Get patient MRN (will need to be fetched separately if needed)
            patient_mrn = ""

            return VentilationEpisode(
                id=episode_id,
                patient_id=patient_id,
                patient_mrn=patient_mrn,
                intubation_date=intubation_date,
                extubation_date=extubation_date,
                encounter_id=encounter_id,
                location_code=location_code,
                fhir_device_id=fhir_id,
            )

        except Exception as e:
            logger.error(f"Failed to parse ventilation procedure: {e}")
            return None

    def _get_daily_min_observations(
        self,
        patient_id: str,
        loinc_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[date, dict]:
        """Get minimum observation values for each day.

        Returns dict mapping date to {"value": float, "id": str}
        """
        daily_mins = {}

        params = {
            "patient": patient_id,
            "code": ",".join(loinc_codes),
            "date": [
                f"ge{start_date.isoformat()}",
                f"le{end_date.isoformat()}",
            ],
            "_sort": "date",
            "_count": "500",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/Observation",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "Observation":
                    continue

                # Get date
                effective = resource.get("effectiveDateTime")
                if not effective:
                    continue
                obs_datetime = datetime.fromisoformat(effective.replace("Z", "+00:00"))
                obs_date = obs_datetime.date()

                # Get value
                value_quantity = resource.get("valueQuantity", {})
                value = value_quantity.get("value")
                if value is None:
                    continue

                # Track minimum for each day
                obs_id = resource.get("id")
                if obs_date not in daily_mins or value < daily_mins[obs_date]["value"]:
                    daily_mins[obs_date] = {"value": value, "id": obs_id}

        except requests.RequestException as e:
            logger.error(f"FHIR observation query failed: {e}")

        return daily_mins

    def _get_encounter_location(self, encounter_id: str) -> str | None:
        """Get location code from an encounter."""
        try:
            response = self.session.get(
                f"{self.base_url}/Encounter/{encounter_id}",
                timeout=10,
            )
            response.raise_for_status()
            encounter = response.json()

            # Get location from encounter.location[]
            for loc in encounter.get("location", []):
                loc_ref = loc.get("location", {}).get("reference", "")
                if loc_ref:
                    # Could fetch Location resource for NHSN code
                    return loc_ref.split("/")[-1]

        except requests.RequestException as e:
            logger.debug(f"Could not fetch encounter location: {e}")

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
            response = self.session.get(
                f"{self.base_url}/Patient/{patient_id}",
                timeout=10,
            )
            response.raise_for_status()
            return self._parse_patient(response.json())
        except requests.RequestException as e:
            logger.error(f"Failed to fetch patient {patient_id}: {e}")
            return None


# ============================================================
# CAUTI-specific FHIR Data Sources
# ============================================================

class FHIRUrinaryCatheterSource(FHIRDeviceSource):
    """FHIR DeviceUseStatement-based urinary catheter retrieval for CAUTI surveillance.

    Extends FHIRDeviceSource to specifically query for indwelling urinary catheters
    using SNOMED CT codes for urinary catheter devices.
    """

    # SNOMED CT codes for urinary catheters
    URINARY_CATHETER_CODES = {
        "20568009",    # Urinary catheter (general)
        "68135008",    # Foley catheter
        "286558007",   # Indwelling urinary catheter
        "448130004",   # Suprapubic catheter
        "61088005",    # Urethral catheter
    }

    # SNOMED CT codes for urinary catheter body sites
    URINARY_CATHETER_SITES = {
        "87953007",    # Urinary bladder
        "13648007",    # Urinary bladder structure
        "64033007",    # Urethra
        "181422007",   # Suprapubic region
    }

    def get_urinary_catheters(
        self,
        patient_id: str,
        as_of_date: datetime,
    ) -> list[DeviceInfo]:
        """Get indwelling urinary catheters present at a given date.

        Args:
            patient_id: FHIR patient ID
            as_of_date: Date to check for catheter presence

        Returns:
            List of urinary catheter DeviceInfo objects
        """
        devices = []

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

                device = self._parse_urinary_catheter(resource)

                if device and self._is_urinary_catheter(device, resource):
                    # Check if catheter was present at as_of_date
                    if self._was_present_at_date(device, as_of_date):
                        devices.append(device)

        except requests.RequestException as e:
            logger.error(f"FHIR urinary catheter query failed: {e}")

        return devices

    def get_all_urinary_catheter_episodes(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[DeviceInfo]:
        """Get all urinary catheter episodes for a patient within a date range.

        Args:
            patient_id: FHIR patient ID
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of urinary catheter DeviceInfo objects
        """
        devices = []

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

                if resource.get("status") == "entered-in-error":
                    continue

                device = self._parse_urinary_catheter(resource)

                if device and self._is_urinary_catheter(device, resource):
                    # Check if catheter overlaps with date range
                    if self._overlaps_date_range(device, start_date, end_date):
                        devices.append(device)

        except requests.RequestException as e:
            logger.error(f"FHIR urinary catheter episodes query failed: {e}")

        return devices

    def _parse_urinary_catheter(self, resource: dict) -> DeviceInfo | None:
        """Parse FHIR DeviceUseStatement to DeviceInfo for urinary catheters."""
        try:
            # Get device type from device reference or code
            device_type = "urinary_catheter"
            device_ref = resource.get("device", {})

            # Try to get specific type from CodeableConcept
            if isinstance(device_ref, dict) and device_ref.get("concept"):
                for coding in device_ref.get("concept", {}).get("coding", []):
                    code = coding.get("code")
                    display = coding.get("display", "")

                    if code == "68135008" or "foley" in display.lower():
                        device_type = "foley_catheter"
                    elif code == "448130004" or "suprapubic" in display.lower():
                        device_type = "suprapubic_catheter"
                    elif code in self.URINARY_CATHETER_CODES:
                        device_type = "urinary_catheter"

            # Get site from bodySite
            site = None
            body_site = resource.get("bodySite", {})
            for coding in body_site.get("coding", []):
                code = coding.get("code")
                display = coding.get("display")

                if code in self.URINARY_CATHETER_SITES:
                    site = display or "urinary"
                    # Infer device type from site if not already set
                    if "suprapubic" in (display or "").lower():
                        device_type = "suprapubic_catheter"

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
            logger.error(f"Failed to parse urinary catheter DeviceUseStatement: {e}")
            return None

    def _is_urinary_catheter(self, device: DeviceInfo, resource: dict) -> bool:
        """Check if device is a urinary catheter.

        Uses both device type and body site information to determine.
        """
        # Check device type
        catheter_types = {
            "urinary_catheter",
            "foley_catheter",
            "suprapubic_catheter",
            "indwelling_urinary_catheter",
        }
        if device.device_type.lower() in catheter_types:
            return True

        # Check device code
        device_ref = resource.get("device", {})
        if isinstance(device_ref, dict) and device_ref.get("concept"):
            for coding in device_ref.get("concept", {}).get("coding", []):
                if coding.get("code") in self.URINARY_CATHETER_CODES:
                    return True

        # Check body site
        body_site = resource.get("bodySite", {})
        for coding in body_site.get("coding", []):
            if coding.get("code") in self.URINARY_CATHETER_SITES:
                return True

        return False

    def _overlaps_date_range(
        self,
        device: DeviceInfo,
        start_date: datetime,
        end_date: datetime,
    ) -> bool:
        """Check if device use overlaps with a date range."""
        if device.insertion_date is None:
            return False

        # Device inserted after range end - no overlap
        if device.insertion_date > end_date:
            return False

        # Device removed before range start - no overlap
        if device.removal_date and device.removal_date < start_date:
            return False

        return True


class FHIRUrineCultureSource(FHIRCultureSource):
    """FHIR DiagnosticReport-based urine culture retrieval for CAUTI surveillance.

    Extends FHIRCultureSource to specifically query for urine cultures
    and parse CFU/mL values needed for CAUTI criteria.
    """

    # LOINC codes for urine cultures
    URINE_CULTURE_CODES = {
        "630-4",      # Bacteria identified in urine by Culture
        "6463-4",     # Bacteria identified in urine by Aerobe culture
        "88461-2",    # Urine culture colony count
        "49581-2",    # Bacteria identified in urine by Culture (Quantitative)
        "5799-2",     # Bacteria identified in urine by Microorganisms (culture)
    }

    def get_positive_urine_cultures(
        self,
        start_date: datetime,
        end_date: datetime,
        min_cfu_ml: int = 100000,
    ) -> list[tuple[Patient, CultureResult]]:
        """Get positive urine cultures meeting CFU threshold.

        Args:
            start_date: Start of date range
            end_date: End of date range
            min_cfu_ml: Minimum CFU/mL threshold (default 10^5 for CAUTI)

        Returns:
            List of (Patient, CultureResult) tuples for qualifying cultures
        """
        results = []

        params = {
            "code": ",".join(self.URINE_CULTURE_CODES),
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

            # Parse urine culture DiagnosticReports
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "DiagnosticReport":
                    culture = self._parse_urine_culture(resource)

                    if culture and culture.is_positive:
                        # Check CFU threshold if available
                        cfu_ml = self._extract_cfu_ml(resource)
                        if cfu_ml is None or cfu_ml >= min_cfu_ml:
                            patient_ref = resource.get("subject", {}).get("reference", "")
                            patient_id = patient_ref.split("/")[-1]
                            patient = patients.get(patient_id)

                            if patient:
                                # Store CFU in culture result for later use
                                culture._cfu_ml = cfu_ml
                                results.append((patient, culture))
                            else:
                                patient = self._fetch_patient(patient_id)
                                if patient:
                                    culture._cfu_ml = cfu_ml
                                    results.append((patient, culture))

            logger.info(f"Found {len(results)} positive urine cultures meeting CAUTI criteria")

        except requests.RequestException as e:
            logger.error(f"FHIR urine culture query failed: {e}")

        return results

    def get_urine_cultures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CultureResult]:
        """Get urine cultures for a specific patient within date range."""
        results = []

        params = {
            "patient": patient_id,
            "code": ",".join(self.URINE_CULTURE_CODES),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
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
                    culture = self._parse_urine_culture(resource)
                    if culture:
                        culture._cfu_ml = self._extract_cfu_ml(resource)
                        results.append(culture)

        except requests.RequestException as e:
            logger.error(f"FHIR urine culture patient query failed: {e}")

        return results

    def _parse_urine_culture(self, resource: dict) -> CultureResult | None:
        """Parse a FHIR DiagnosticReport for urine culture."""
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

            # Determine if positive and get organism(s)
            is_positive = False
            organism = None
            organism_count = 0

            conclusion = resource.get("conclusion", "")
            if conclusion:
                conclusion_lower = conclusion.lower()
                is_positive = (
                    "positive" in conclusion_lower or
                    "growth" in conclusion_lower or
                    "colony" in conclusion_lower
                )
                # Check for mixed flora
                if "mixed" in conclusion_lower or "multiple" in conclusion_lower:
                    organism_count = 3  # Assume >2 for mixed flora

            # Try to extract organism(s) from conclusion codes
            organisms = []
            for cc in resource.get("conclusionCode", []):
                for coding in cc.get("coding", []):
                    if coding.get("display"):
                        organisms.append(coding.get("display"))
                        is_positive = True

            if organisms:
                organism = organisms[0]  # Primary organism
                organism_count = len(organisms)

            return CultureResult(
                fhir_id=fhir_id,
                collection_date=collection_date,
                organism=organism,
                result_date=result_date,
                specimen_source="urine",
                is_positive=is_positive,
            )

        except Exception as e:
            logger.error(f"Failed to parse urine culture DiagnosticReport: {e}")
            return None

    def _extract_cfu_ml(self, resource: dict) -> int | None:
        """Extract CFU/mL value from DiagnosticReport or linked Observations.

        Looks for colony count in:
        1. Conclusion text (e.g., "10^5 CFU/mL")
        2. Linked Observation resources
        3. Extended fields
        """
        try:
            # Try to extract from conclusion text
            conclusion = resource.get("conclusion", "")
            if conclusion:
                # Match patterns like "10^5", ">100000", "1E5"
                import re

                # Pattern for scientific notation
                sci_match = re.search(r"10\^(\d+)", conclusion)
                if sci_match:
                    exponent = int(sci_match.group(1))
                    return 10 ** exponent

                # Pattern for 1E notation
                e_match = re.search(r"(\d+)E(\d+)", conclusion, re.IGNORECASE)
                if e_match:
                    base = int(e_match.group(1))
                    exponent = int(e_match.group(2))
                    return base * (10 ** exponent)

                # Pattern for numeric with > or >= prefix
                num_match = re.search(r"[>≥]?\s*(\d{5,})", conclusion)
                if num_match:
                    return int(num_match.group(1))

            # Check linked Observation resources (would need separate query)
            # For now, return None if not in conclusion
            return None

        except Exception as e:
            logger.debug(f"Could not extract CFU/mL: {e}")
            return None

    def get_organism_count(self, resource: dict) -> int:
        """Get the number of organisms identified in a culture.

        Returns:
            Number of organisms (>2 typically indicates mixed flora)
        """
        count = 0

        # Count organisms in conclusionCode
        for cc in resource.get("conclusionCode", []):
            for coding in cc.get("coding", []):
                if coding.get("display"):
                    count += 1

        # Check conclusion for mixed flora indication
        conclusion = resource.get("conclusion", "").lower()
        if "mixed flora" in conclusion or "mixed growth" in conclusion:
            return 3  # More than 2 organisms

        return max(count, 1) if count > 0 else 0


# ============================================================
# CDI-specific FHIR Data Sources
# ============================================================

class FHIRCDITestSource:
    """FHIR Observation-based C. difficile test result retrieval for CDI surveillance.

    Queries FHIR for C. difficile toxin tests, PCR/NAAT tests, and culture results.

    NHSN CDI LabID Event Criteria:
    - Positive C. difficile toxin A and/or B test result, OR
    - Detection of toxin-producing C. difficile organism by culture/PCR
    - Specimen must be unformed stool (including ostomy)
    - Antigen-only results (GDH) do NOT qualify

    LOINC Codes Used:
    - 34713-8: C. difficile toxin A
    - 34714-6: C. difficile toxin B
    - 34712-0: C. difficile toxin A+B
    - 82197-9: C. difficile toxin B gene (PCR)
    - 80685-5: C. difficile toxin genes (NAAT)
    """

    # LOINC codes for qualifying CDI tests (toxin or molecular)
    CDI_TOXIN_LOINC_CODES = {
        "34713-8": "toxin_a",      # C. difficile toxin A
        "34714-6": "toxin_b",      # C. difficile toxin B
        "34712-0": "toxin_ab",     # C. difficile toxin A+B
        "562-9": "toxin_ab",       # C. difficile toxin A+B (alt code)
        "6359-4": "toxin_ab",      # C. difficile toxin
    }

    CDI_MOLECULAR_LOINC_CODES = {
        "82197-9": "pcr",          # C. difficile toxin B gene (PCR)
        "80685-5": "naat",         # C. difficile toxin genes (NAAT)
        "63588-5": "naat",         # C. difficile toxin B gene (NAA)
        "54067-4": "naat",         # C. difficile toxin A gene (NAA)
        "625-4": "culture_toxigenic",  # C. difficile culture
    }

    # LOINC codes for antigen tests (do NOT qualify alone)
    CDI_ANTIGEN_LOINC_CODES = {
        "76580-0": "gdh",          # C. difficile Ag (GDH)
        "31369-5": "antigen",      # C. difficile Ag
    }

    def __init__(self, base_url: str | None = None):
        from ..config import Config
        self.base_url = base_url or Config.get_fhir_base_url()
        self.session = requests.Session()

    def get_positive_cdi_tests(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple["Patient", "CDITestResult"]]:
        """Get positive C. diff toxin/PCR tests within a date range.

        Queries FHIR Observation resources for positive C. diff tests
        that qualify for CDI LabID events (toxin or molecular tests).

        Args:
            start_date: Start of date range to search
            end_date: End of date range to search

        Returns:
            List of (Patient, CDITestResult) tuples for positive qualifying tests
        """
        from ..models import CDITestResult

        results = []

        # Combine toxin and molecular LOINC codes
        all_qualifying_codes = set(self.CDI_TOXIN_LOINC_CODES.keys()) | set(self.CDI_MOLECULAR_LOINC_CODES.keys())

        params = {
            "code": ",".join(all_qualifying_codes),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
            "_include": "Observation:subject",
            "_count": "100",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/Observation",
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

            # Parse Observation resources for positive CDI tests
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Observation":
                    cdi_test = self._parse_cdi_observation(resource)

                    if cdi_test and cdi_test.result == "positive":
                        patient_ref = resource.get("subject", {}).get("reference", "")
                        patient_id = patient_ref.split("/")[-1]
                        patient = patients.get(patient_id)

                        if patient:
                            results.append((patient, cdi_test))
                        else:
                            patient = self._fetch_patient(patient_id)
                            if patient:
                                results.append((patient, cdi_test))

            logger.info(f"Found {len(results)} positive CDI tests from FHIR")

        except requests.RequestException as e:
            logger.error(f"FHIR CDI test query failed: {e}")

        return results

    def get_patient_cdi_history(
        self,
        patient_id: str,
        before_date: datetime,
        lookback_days: int = 90,
    ) -> list["CDITestResult"]:
        """Get prior CDI test results for recurrence detection.

        Queries patient's prior CDI tests to determine if current
        test is incident, recurrent, or duplicate.

        Args:
            patient_id: FHIR patient ID
            before_date: Current test date (look back from here)
            lookback_days: Days to look back (default 90 for recurrence window)

        Returns:
            List of prior CDI test results ordered by date descending
        """
        from ..models import CDITestResult

        results = []

        start_date = before_date - timedelta(days=lookback_days)

        # Query all qualifying CDI tests
        all_codes = set(self.CDI_TOXIN_LOINC_CODES.keys()) | set(self.CDI_MOLECULAR_LOINC_CODES.keys())

        params = {
            "patient": patient_id,
            "code": ",".join(all_codes),
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"lt{before_date.strftime('%Y-%m-%d')}",
            ],
            "_sort": "-date",
            "_count": "50",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/Observation",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Observation":
                    cdi_test = self._parse_cdi_observation(resource)
                    if cdi_test and cdi_test.result == "positive":
                        results.append(cdi_test)

        except requests.RequestException as e:
            logger.error(f"FHIR CDI history query failed: {e}")

        return results

    def get_patient_admission_date(
        self,
        patient_id: str,
        as_of_date: datetime,
    ) -> datetime | None:
        """Get patient's current encounter admission date.

        Used to calculate specimen day for HO vs CO classification.

        Args:
            patient_id: FHIR patient ID
            as_of_date: Date of the CDI test

        Returns:
            Admission date of the current encounter, or None if not found
        """
        try:
            # Query active/in-progress encounter
            params = {
                "patient": patient_id,
                "status": "in-progress,finished",
                "date": f"le{as_of_date.strftime('%Y-%m-%d')}",
                "_sort": "-date",
                "_count": "1",
            }

            response = self.session.get(
                f"{self.base_url}/Encounter",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Encounter":
                    period = resource.get("period", {})
                    start_str = period.get("start")
                    if start_str:
                        return datetime.fromisoformat(start_str.replace("Z", "+00:00"))

        except requests.RequestException as e:
            logger.error(f"FHIR encounter query failed: {e}")

        return None

    def get_patient_prior_discharge(
        self,
        patient_id: str,
        before_date: datetime,
        lookback_days: int = 28,
    ) -> tuple[datetime | None, str | None]:
        """Get most recent prior inpatient discharge for CO-HCFA detection.

        CO-HCFA requires discharge from any inpatient facility within 4 weeks.

        Args:
            patient_id: FHIR patient ID
            before_date: Current admission date
            lookback_days: Days to look back (default 28 = 4 weeks)

        Returns:
            Tuple of (discharge_date, facility_name) or (None, None)
        """
        try:
            start_date = before_date - timedelta(days=lookback_days)

            params = {
                "patient": patient_id,
                "status": "finished",
                "class": "IMP,ACUTE,NONAC",  # Inpatient classes
                "date": [
                    f"ge{start_date.strftime('%Y-%m-%d')}",
                    f"lt{before_date.strftime('%Y-%m-%d')}",
                ],
                "_sort": "-date",
                "_count": "1",
            }

            response = self.session.get(
                f"{self.base_url}/Encounter",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Encounter":
                    period = resource.get("period", {})
                    end_str = period.get("end")
                    if end_str:
                        discharge_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))

                        # Get facility name if available
                        facility = None
                        service_provider = resource.get("serviceProvider", {})
                        if service_provider.get("display"):
                            facility = service_provider.get("display")

                        return (discharge_date, facility)

        except requests.RequestException as e:
            logger.error(f"FHIR prior discharge query failed: {e}")

        return (None, None)

    def get_patient_encounter_info(
        self,
        patient_id: str,
        as_of_date: datetime,
    ) -> dict:
        """Get full encounter information for CDI surveillance.

        Returns:
            Dict with admission_date, discharge_date (if discharged),
            encounter_id, location, etc.
        """
        info = {
            "encounter_id": None,
            "admission_date": None,
            "discharge_date": None,
            "location_code": None,
            "class": None,
        }

        try:
            params = {
                "patient": patient_id,
                "status": "in-progress,finished",
                "date": f"le{as_of_date.strftime('%Y-%m-%d')}",
                "_sort": "-date",
                "_count": "1",
            }

            response = self.session.get(
                f"{self.base_url}/Encounter",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Encounter":
                    info["encounter_id"] = resource.get("id")

                    period = resource.get("period", {})
                    if period.get("start"):
                        info["admission_date"] = datetime.fromisoformat(
                            period["start"].replace("Z", "+00:00")
                        )
                    if period.get("end"):
                        info["discharge_date"] = datetime.fromisoformat(
                            period["end"].replace("Z", "+00:00")
                        )

                    # Get class (inpatient, outpatient, etc.)
                    enc_class = resource.get("class", {})
                    if isinstance(enc_class, dict):
                        info["class"] = enc_class.get("code")

                    # Get location
                    locations = resource.get("location", [])
                    if locations:
                        loc = locations[-1]  # Most recent location
                        loc_ref = loc.get("location", {}).get("reference", "")
                        if loc_ref:
                            info["location_code"] = loc_ref.split("/")[-1]

        except requests.RequestException as e:
            logger.error(f"FHIR encounter info query failed: {e}")

        return info

    def _parse_cdi_observation(self, resource: dict) -> "CDITestResult | None":
        """Parse a FHIR Observation resource to CDITestResult."""
        from ..models import CDITestResult

        try:
            fhir_id = resource.get("id")

            # Get patient ID
            subject_ref = resource.get("subject", {}).get("reference", "")
            patient_id = subject_ref.split("/")[-1] if subject_ref else ""

            # Get test date
            effective = resource.get("effectiveDateTime")
            if not effective:
                return None
            test_date = datetime.fromisoformat(effective.replace("Z", "+00:00"))

            # Get LOINC code and determine test type
            loinc_code = None
            test_type = "unknown"

            for coding in resource.get("code", {}).get("coding", []):
                code = coding.get("code")
                if code in self.CDI_TOXIN_LOINC_CODES:
                    loinc_code = code
                    test_type = self.CDI_TOXIN_LOINC_CODES[code]
                    break
                elif code in self.CDI_MOLECULAR_LOINC_CODES:
                    loinc_code = code
                    test_type = self.CDI_MOLECULAR_LOINC_CODES[code]
                    break
                elif code in self.CDI_ANTIGEN_LOINC_CODES:
                    loinc_code = code
                    test_type = self.CDI_ANTIGEN_LOINC_CODES[code]
                    break

            # Determine result (positive/negative)
            result = "unknown"

            # Check valueCodeableConcept
            value_cc = resource.get("valueCodeableConcept", {})
            for coding in value_cc.get("coding", []):
                display = (coding.get("display") or "").lower()
                code = coding.get("code", "")

                if "positive" in display or "detected" in display or code == "10828004":
                    result = "positive"
                    break
                elif "negative" in display or "not detected" in display or code == "260385009":
                    result = "negative"
                    break

            # Check interpretation
            for interp in resource.get("interpretation", []):
                for coding in interp.get("coding", []):
                    code = coding.get("code", "")
                    if code in ("POS", "A", "H", "HH"):
                        result = "positive"
                    elif code in ("NEG", "N"):
                        result = "negative"

            # Get specimen type
            specimen_type = None
            is_formed_stool = False

            specimen_ref = resource.get("specimen", {}).get("reference", "")
            if specimen_ref:
                specimen_info = self._fetch_specimen_info(specimen_ref)
                if specimen_info:
                    specimen_type = specimen_info.get("type")
                    is_formed_stool = specimen_info.get("is_formed", False)

            # Get encounter ID
            encounter_ref = resource.get("encounter", {}).get("reference", "")
            encounter_id = encounter_ref.split("/")[-1] if encounter_ref else None

            return CDITestResult(
                fhir_id=fhir_id,
                patient_id=patient_id,
                test_date=test_date,
                test_type=test_type,
                result=result,
                loinc_code=loinc_code,
                specimen_type=specimen_type,
                is_formed_stool=is_formed_stool,
                encounter_id=encounter_id,
            )

        except Exception as e:
            logger.error(f"Failed to parse CDI Observation: {e}")
            return None

    def _fetch_specimen_info(self, specimen_ref: str) -> dict | None:
        """Fetch specimen information to check stool consistency."""
        try:
            # Handle relative or absolute reference
            if specimen_ref.startswith("Specimen/"):
                specimen_id = specimen_ref.split("/")[-1]
                url = f"{self.base_url}/Specimen/{specimen_id}"
            elif specimen_ref.startswith(self.base_url):
                url = specimen_ref
            else:
                url = f"{self.base_url}/{specimen_ref}"

            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            resource = response.json()

            specimen_type = None
            is_formed = False

            # Get type from type.coding
            for coding in resource.get("type", {}).get("coding", []):
                display = (coding.get("display") or "").lower()
                if "stool" in display or "feces" in display:
                    specimen_type = "stool"
                    # Check for formed stool
                    if "formed" in display:
                        is_formed = True
                elif "ostomy" in display:
                    specimen_type = "ostomy"

            # Check condition for stool consistency
            for condition in resource.get("condition", []):
                for coding in condition.get("coding", []):
                    display = (coding.get("display") or "").lower()
                    if "formed" in display or "solid" in display:
                        is_formed = True
                    elif "liquid" in display or "watery" in display or "loose" in display:
                        is_formed = False

            return {
                "type": specimen_type,
                "is_formed": is_formed,
            }

        except Exception as e:
            logger.debug(f"Could not fetch specimen info: {e}")
            return None

    def _parse_patient(self, resource: dict) -> "Patient | None":
        """Parse FHIR Patient resource."""
        from ..models import Patient

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

    def _fetch_patient(self, patient_id: str) -> "Patient | None":
        """Fetch a patient by ID."""
        try:
            response = self.session.get(
                f"{self.base_url}/Patient/{patient_id}",
                timeout=10,
            )
            response.raise_for_status()
            return self._parse_patient(response.json())
        except requests.RequestException as e:
            logger.error(f"Failed to fetch patient {patient_id}: {e}")
            return None

    def get_stool_frequency(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """Get stool frequency/output observations from flowsheets.

        Queries FHIR Observation resources for stool count data.
        This supplements LLM-based extraction with structured flowsheet data.

        LOINC codes for stool output:
        - 8251-1: Number of stools in 24 hours
        - 9295-2: Stool consistency
        - 80349-7: Stool output measurement

        Args:
            patient_id: FHIR Patient ID
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of dicts with date, frequency, consistency info
        """
        # LOINC codes for stool-related observations
        stool_loinc_codes = [
            "8251-1",   # Number of stools in 24 hours
            "9295-2",   # Stool consistency
            "80349-7",  # Stool output measurement
        ]

        results = []

        try:
            # Build params - use list of tuples for multiple date params
            params = [
                ("patient", patient_id),
                ("code", ",".join([f"http://loinc.org|{code}" for code in stool_loinc_codes])),
                ("date", f"ge{start_date.strftime('%Y-%m-%d')}"),
                ("date", f"le{end_date.strftime('%Y-%m-%d')}"),
                ("_sort", "-date"),
            ]

            response = self.session.get(
                f"{self.base_url}/Observation",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") != "Observation":
                    continue

                observation = self._parse_stool_observation(resource)
                if observation:
                    results.append(observation)

        except requests.RequestException as e:
            logger.debug(f"Failed to query stool observations: {e}")

        return results

    def _parse_stool_observation(self, resource: dict) -> dict | None:
        """Parse a stool-related FHIR Observation.

        Args:
            resource: FHIR Observation resource

        Returns:
            Dict with observation data, or None if invalid
        """
        try:
            # Get date
            effective = resource.get("effectiveDateTime")
            if not effective:
                return None
            obs_date = datetime.fromisoformat(effective.replace("Z", "+00:00"))

            # Get LOINC code
            loinc_code = None
            for coding in resource.get("code", {}).get("coding", []):
                if coding.get("system") == "http://loinc.org":
                    loinc_code = coding.get("code")
                    break

            # Parse value based on type
            result = {
                "date": obs_date,
                "loinc_code": loinc_code,
            }

            # Numeric value (stool count)
            if "valueQuantity" in resource:
                result["value"] = resource["valueQuantity"].get("value")
                result["unit"] = resource["valueQuantity"].get("unit")
                result["type"] = "count"

            # Coded value (consistency)
            elif "valueCodeableConcept" in resource:
                for coding in resource["valueCodeableConcept"].get("coding", []):
                    result["value"] = coding.get("display")
                    result["type"] = "consistency"
                    break

            # String value
            elif "valueString" in resource:
                result["value"] = resource["valueString"]
                result["type"] = "text"

            return result

        except Exception as e:
            logger.debug(f"Failed to parse stool observation: {e}")
            return None
