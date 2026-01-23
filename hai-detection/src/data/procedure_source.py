"""Procedure data source for SSI monitoring.

Provides surgical procedure data for SSI candidate detection.
Follows the same factory pattern as culture/device sources.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from ..models import Patient, SurgicalProcedure
from ..rules.nhsn_criteria import (
    NHSN_OPERATIVE_CATEGORIES,
    is_nhsn_operative_procedure,
    is_implant_procedure,
)

logger = logging.getLogger(__name__)


class BaseProcedureSource(ABC):
    """Abstract base class for surgical procedure data retrieval."""

    @abstractmethod
    def get_nhsn_procedures(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[Patient, SurgicalProcedure]]:
        """Get NHSN operative procedures within a date range.

        This returns procedures that are eligible for SSI surveillance,
        meaning they are NHSN operative procedure categories.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of (Patient, SurgicalProcedure) tuples
        """
        pass

    @abstractmethod
    def get_procedures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[SurgicalProcedure]:
        """Get all surgical procedures for a patient within a date range.

        Args:
            patient_id: FHIR patient ID or MRN
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of surgical procedures
        """
        pass

    @abstractmethod
    def get_procedure_by_id(self, procedure_id: str) -> SurgicalProcedure | None:
        """Get a specific procedure by ID.

        Args:
            procedure_id: Procedure identifier

        Returns:
            SurgicalProcedure if found, None otherwise
        """
        pass


class MockProcedureSource(BaseProcedureSource):
    """Mock procedure source for development and testing.

    Generates synthetic surgical procedure data for SSI surveillance testing.
    """

    def __init__(self):
        """Initialize with sample surgical procedures."""
        self._procedures: list[tuple[Patient, SurgicalProcedure]] = []
        self._generate_mock_data()

    def _generate_mock_data(self) -> None:
        """Generate mock surgical procedure data."""
        now = datetime.now()

        # Sample patients with recent surgeries
        mock_cases = [
            {
                "patient": Patient(
                    fhir_id="ssi-patient-001",
                    mrn="SSI001",
                    name="John Smith",
                    birth_date="1955-03-15",
                    location="3 North",
                ),
                "procedure": SurgicalProcedure(
                    id="proc-001",
                    procedure_code="44140",  # Colectomy CPT
                    procedure_name="Sigmoid colectomy",
                    procedure_date=now - timedelta(days=7),
                    patient_id="ssi-patient-001",
                    nhsn_category="COLO",
                    wound_class=2,  # Clean-contaminated
                    duration_minutes=180,
                    asa_score=2,
                    primary_surgeon="Dr. Sarah Johnson",
                    implant_used=False,
                    fhir_id="fhir-proc-001",
                    encounter_id="enc-001",
                    location_code="3N",
                ),
            },
            {
                "patient": Patient(
                    fhir_id="ssi-patient-002",
                    mrn="SSI002",
                    name="Mary Williams",
                    birth_date="1968-07-22",
                    location="Orthopedic Unit",
                ),
                "procedure": SurgicalProcedure(
                    id="proc-002",
                    procedure_code="27447",  # Total knee replacement CPT
                    procedure_name="Total knee arthroplasty, right",
                    procedure_date=now - timedelta(days=14),
                    patient_id="ssi-patient-002",
                    nhsn_category="KPRO",
                    wound_class=1,  # Clean
                    duration_minutes=120,
                    asa_score=3,
                    primary_surgeon="Dr. Michael Chen",
                    implant_used=True,
                    implant_type="Total knee prosthesis",
                    fhir_id="fhir-proc-002",
                    encounter_id="enc-002",
                    location_code="ORTH",
                ),
            },
            {
                "patient": Patient(
                    fhir_id="ssi-patient-003",
                    mrn="SSI003",
                    name="Robert Davis",
                    birth_date="1962-11-08",
                    location="CICU",
                ),
                "procedure": SurgicalProcedure(
                    id="proc-003",
                    procedure_code="33533",  # CABG CPT
                    procedure_name="CABG x3 with LIMA",
                    procedure_date=now - timedelta(days=5),
                    patient_id="ssi-patient-003",
                    nhsn_category="CABG",
                    wound_class=1,  # Clean
                    duration_minutes=300,
                    asa_score=4,
                    primary_surgeon="Dr. Elizabeth Park",
                    implant_used=True,
                    implant_type="Sternal wires",
                    fhir_id="fhir-proc-003",
                    encounter_id="enc-003",
                    location_code="CICU",
                ),
            },
            {
                "patient": Patient(
                    fhir_id="ssi-patient-004",
                    mrn="SSI004",
                    name="Patricia Taylor",
                    birth_date="1975-04-18",
                    location="2 West",
                ),
                "procedure": SurgicalProcedure(
                    id="proc-004",
                    procedure_code="47562",  # Laparoscopic cholecystectomy
                    procedure_name="Laparoscopic cholecystectomy",
                    procedure_date=now - timedelta(days=3),
                    patient_id="ssi-patient-004",
                    nhsn_category="CHOL",
                    wound_class=2,  # Clean-contaminated
                    duration_minutes=60,
                    asa_score=2,
                    primary_surgeon="Dr. James Wilson",
                    implant_used=False,
                    fhir_id="fhir-proc-004",
                    encounter_id="enc-004",
                    location_code="2W",
                ),
            },
            {
                "patient": Patient(
                    fhir_id="ssi-patient-005",
                    mrn="SSI005",
                    name="James Anderson",
                    birth_date="1945-09-30",
                    location="5 South",
                ),
                "procedure": SurgicalProcedure(
                    id="proc-005",
                    procedure_code="27130",  # Total hip replacement
                    procedure_name="Total hip arthroplasty, left",
                    procedure_date=now - timedelta(days=21),
                    patient_id="ssi-patient-005",
                    nhsn_category="HPRO",
                    wound_class=1,  # Clean
                    duration_minutes=150,
                    asa_score=3,
                    primary_surgeon="Dr. Michael Chen",
                    implant_used=True,
                    implant_type="Total hip prosthesis",
                    fhir_id="fhir-proc-005",
                    encounter_id="enc-005",
                    location_code="5S",
                ),
            },
            # Add a case with potential SSI signals
            {
                "patient": Patient(
                    fhir_id="ssi-patient-006",
                    mrn="SSI006",
                    name="Elizabeth Brown",
                    birth_date="1958-12-05",
                    location="4 North",
                ),
                "procedure": SurgicalProcedure(
                    id="proc-006",
                    procedure_code="44140",
                    procedure_name="Right hemicolectomy",
                    procedure_date=now - timedelta(days=10),
                    patient_id="ssi-patient-006",
                    nhsn_category="COLO",
                    wound_class=3,  # Contaminated (perforation)
                    duration_minutes=240,
                    asa_score=3,
                    primary_surgeon="Dr. Sarah Johnson",
                    implant_used=False,
                    fhir_id="fhir-proc-006",
                    encounter_id="enc-006",
                    location_code="4N",
                ),
            },
        ]

        for case in mock_cases:
            self._procedures.append((case["patient"], case["procedure"]))

    def get_nhsn_procedures(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[Patient, SurgicalProcedure]]:
        """Get NHSN operative procedures within date range."""
        results = []
        for patient, procedure in self._procedures:
            # Check if procedure date is in range
            if start_date <= procedure.procedure_date <= end_date:
                # Check if it's an NHSN operative category
                if procedure.nhsn_category and is_nhsn_operative_procedure(
                    procedure.nhsn_category
                ):
                    results.append((patient, procedure))

        logger.debug(f"MockProcedureSource: Found {len(results)} NHSN procedures")
        return results

    def get_procedures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[SurgicalProcedure]:
        """Get procedures for a specific patient."""
        results = []
        for patient, procedure in self._procedures:
            if (
                patient.fhir_id == patient_id or patient.mrn == patient_id
            ) and start_date <= procedure.procedure_date <= end_date:
                results.append(procedure)
        return results

    def get_procedure_by_id(self, procedure_id: str) -> SurgicalProcedure | None:
        """Get procedure by ID."""
        for _, procedure in self._procedures:
            if procedure.id == procedure_id or procedure.fhir_id == procedure_id:
                return procedure
        return None

    def add_mock_procedure(
        self, patient: Patient, procedure: SurgicalProcedure
    ) -> None:
        """Add a mock procedure for testing."""
        self._procedures.append((patient, procedure))


class FHIRProcedureSource(BaseProcedureSource):
    """FHIR-based procedure source.

    Retrieves surgical procedures from FHIR Procedure resources.
    """

    # CPT codes that map to NHSN operative categories
    CPT_TO_NHSN = {
        "44140": "COLO",  # Colectomy
        "44145": "COLO",  # Colectomy with colostomy
        "44150": "COLO",  # Colectomy, total
        "44204": "COLO",  # Laparoscopic colectomy
        "44950": "APPY",  # Appendectomy
        "44970": "APPY",  # Laparoscopic appendectomy
        "47562": "CHOL",  # Laparoscopic cholecystectomy
        "47563": "CHOL",  # Laparoscopic cholecystectomy with cholangiography
        "47600": "CHOL",  # Cholecystectomy
        "27447": "KPRO",  # Total knee arthroplasty
        "27130": "HPRO",  # Total hip arthroplasty
        "33533": "CABG",  # CABG
        "33534": "CABG",  # CABG x2
        "33535": "CABG",  # CABG x3
        "33536": "CABG",  # CABG x4+
        "00580": "LAM",   # Laminectomy
        "63030": "LAM",   # Laminotomy
        "22612": "FUS",   # Spinal fusion
        "22630": "FUS",   # Posterior fusion
    }

    def __init__(self, base_url: str | None = None):
        """Initialize with FHIR base URL.

        Args:
            base_url: FHIR server base URL. Uses config default if None.
        """
        import requests
        from ..config import Config
        self.base_url = base_url or Config.FHIR_BASE_URL
        self.session = requests.Session()

    def get_nhsn_procedures(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[Patient, SurgicalProcedure]]:
        """Get NHSN procedures from FHIR server.

        Searches for Procedure resources with surgical codes that map
        to NHSN operative categories.
        """
        import requests

        results = []
        patients_cache: dict[str, Patient] = {}

        params = {
            "category": "387713003",  # SNOMED: Surgical procedure
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
            "_include": "Procedure:patient",
            "_count": "100",
        }

        try:
            response = self.session.get(
                f"{self.base_url}/Procedure",
                params=params,
            )
            response.raise_for_status()
            bundle = response.json()

            # First pass: cache all patients from _include
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Patient":
                    patient = self._parse_patient(resource)
                    if patient:
                        patients_cache[patient.fhir_id] = patient

            # Second pass: parse procedures
            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Procedure":
                    procedure = self._parse_procedure(resource)
                    if procedure and procedure.nhsn_category:
                        # Get patient
                        patient_ref = resource.get("subject", {}).get("reference", "")
                        patient_id = patient_ref.split("/")[-1]

                        patient = patients_cache.get(patient_id)
                        if not patient:
                            # Fetch patient if not in bundle
                            patient = self._fetch_patient(patient_id)

                        if patient:
                            results.append((patient, procedure))

            logger.debug(f"FHIRProcedureSource: Found {len(results)} NHSN procedures")

        except requests.RequestException as e:
            logger.error(f"FHIR procedure query failed: {e}")

        return results

    def get_procedures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[SurgicalProcedure]:
        """Get procedures for patient from FHIR."""
        import requests

        results = []
        params = {
            "patient": patient_id,
            "date": [
                f"ge{start_date.strftime('%Y-%m-%d')}",
                f"le{end_date.strftime('%Y-%m-%d')}",
            ],
        }

        try:
            response = self.session.get(
                f"{self.base_url}/Procedure",
                params=params,
            )
            response.raise_for_status()
            bundle = response.json()

            for entry in bundle.get("entry", []):
                resource = entry.get("resource", {})
                if resource.get("resourceType") == "Procedure":
                    procedure = self._parse_procedure(resource)
                    if procedure:
                        results.append(procedure)

        except requests.RequestException as e:
            logger.error(f"FHIR procedure query failed: {e}")

        return results

    def get_procedure_by_id(self, procedure_id: str) -> SurgicalProcedure | None:
        """Get procedure by FHIR ID."""
        import requests

        try:
            response = self.session.get(f"{self.base_url}/Procedure/{procedure_id}")
            response.raise_for_status()
            resource = response.json()
            return self._parse_procedure(resource)
        except requests.RequestException as e:
            logger.error(f"Failed to fetch procedure {procedure_id}: {e}")
            return None

    def _parse_procedure(self, resource: dict) -> SurgicalProcedure | None:
        """Parse FHIR Procedure resource to SurgicalProcedure."""
        try:
            fhir_id = resource.get("id")

            # Get CPT code
            procedure_code = None
            procedure_name = None
            for coding in resource.get("code", {}).get("coding", []):
                if coding.get("system") in [
                    "http://www.ama-assn.org/go/cpt",
                    "CPT",
                ]:
                    procedure_code = coding.get("code")
                    procedure_name = coding.get("display")
                    break
            # Fallback to any code
            if not procedure_code:
                codings = resource.get("code", {}).get("coding", [])
                if codings:
                    procedure_code = codings[0].get("code")
                    procedure_name = codings[0].get("display")

            if not procedure_code:
                return None

            # Get procedure date
            performed = resource.get("performedDateTime") or resource.get("performedPeriod", {}).get("start")
            if not performed:
                return None
            procedure_date = datetime.fromisoformat(performed.replace("Z", "+00:00"))

            # Get patient ID
            patient_ref = resource.get("subject", {}).get("reference", "")
            patient_id = patient_ref.split("/")[-1]

            # Map CPT to NHSN category
            nhsn_category = self.CPT_TO_NHSN.get(procedure_code)

            # Get duration if available
            duration_minutes = None
            performed_period = resource.get("performedPeriod", {})
            if performed_period.get("start") and performed_period.get("end"):
                start = datetime.fromisoformat(performed_period["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(performed_period["end"].replace("Z", "+00:00"))
                duration_minutes = int((end - start).total_seconds() / 60)

            # Check for implant
            implant_used = False
            implant_type = None
            if nhsn_category in ["KPRO", "HPRO", "CABG", "FUS"]:
                implant_used = True  # These procedures typically involve implants
            # Check extension for explicit implant flag
            for ext in resource.get("extension", []):
                if "implant" in ext.get("url", "").lower():
                    implant_used = ext.get("valueBoolean", True)

            # Get wound class from extension if available
            wound_class = None
            for ext in resource.get("extension", []):
                if "wound-class" in ext.get("url", "").lower():
                    wound_class = ext.get("valueInteger")

            return SurgicalProcedure(
                id=fhir_id,
                procedure_code=procedure_code,
                procedure_name=procedure_name or procedure_code,
                procedure_date=procedure_date,
                patient_id=patient_id,
                nhsn_category=nhsn_category,
                wound_class=wound_class,
                duration_minutes=duration_minutes,
                implant_used=implant_used,
                implant_type=implant_type,
                fhir_id=fhir_id,
            )

        except Exception as e:
            logger.error(f"Failed to parse Procedure: {e}")
            return None

    def _parse_patient(self, resource: dict) -> Patient | None:
        """Parse FHIR Patient resource."""
        try:
            fhir_id = resource.get("id")

            # Get MRN
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

            return Patient(
                fhir_id=fhir_id,
                mrn=mrn,
                name=name,
                birth_date=resource.get("birthDate"),
            )

        except Exception as e:
            logger.error(f"Failed to parse Patient: {e}")
            return None

    def _fetch_patient(self, patient_id: str) -> Patient | None:
        """Fetch patient by ID."""
        import requests

        try:
            response = self.session.get(f"{self.base_url}/Patient/{patient_id}")
            response.raise_for_status()
            return self._parse_patient(response.json())
        except requests.RequestException as e:
            logger.error(f"Failed to fetch patient {patient_id}: {e}")
            return None


class ClarityProcedureSource(BaseProcedureSource):
    """Clarity-based procedure source.

    Retrieves surgical procedures from Epic Clarity OR tables.
    """

    def __init__(self, db_session=None):
        """Initialize with Clarity database session.

        Args:
            db_session: SQLAlchemy session for Clarity. Uses config default if None.
        """
        self._session = db_session

    def get_nhsn_procedures(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[Patient, SurgicalProcedure]]:
        """Get NHSN procedures from Clarity OR tables.

        Queries OR_LOG and related tables for surgical procedures.
        """
        # TODO: Implement Clarity query
        # Tables: OR_LOG, OR_LOG_ALL_PROC, OR_PROC, PATIENT
        logger.warning("ClarityProcedureSource.get_nhsn_procedures not implemented")
        return []

    def get_procedures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[SurgicalProcedure]:
        """Get procedures for patient from Clarity."""
        # TODO: Implement Clarity query
        logger.warning(
            "ClarityProcedureSource.get_procedures_for_patient not implemented"
        )
        return []

    def get_procedure_by_id(self, procedure_id: str) -> SurgicalProcedure | None:
        """Get procedure by OR log ID."""
        # TODO: Implement Clarity query
        logger.warning("ClarityProcedureSource.get_procedure_by_id not implemented")
        return None
