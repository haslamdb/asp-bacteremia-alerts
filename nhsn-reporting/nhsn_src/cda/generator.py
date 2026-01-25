"""CDA document generator for NHSN HAI (BSI/CLABSI) reporting.

Generates HL7 CDA R2 compliant documents for submission to NHSN.
Based on: HL7 Implementation Guide for CDA Release 2: NHSN Healthcare
Associated Infection (HAI) Reports.

Reference: https://www.hl7.org/implement/standards/product_brief.cfm?product_id=20
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any
from xml.etree import ElementTree as ET
from xml.dom import minidom

# CDA namespaces
CDA_NS = "urn:hl7-org:v3"
SDTC_NS = "urn:hl7-org:sdtc"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# NHSN OIDs
NHSN_ROOT_OID = "2.16.840.1.113883.3.117"
LOINC_OID = "2.16.840.1.113883.6.1"
SNOMED_OID = "2.16.840.1.113883.6.96"
CDC_NHSN_OID = "2.16.840.1.113883.3.117.1.1.5.2.1.1"

# HAI Report type codes (LOINC)
HAI_REPORT_CODES = {
    "bsi": "51897-7",  # Healthcare Associated Infection report
    "clabsi": "51897-7",
}

# BSI Event type codes
BSI_EVENT_CODES = {
    "clabsi": "1645-5",  # Central line-associated BSI
    "lcbi": "1643-0",    # Laboratory-confirmed BSI
}


@dataclass
class BSICDADocument:
    """Data structure for a BSI CDA document."""

    # Document metadata
    document_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    creation_time: datetime = field(default_factory=datetime.now)

    # Facility info
    facility_id: str = ""
    facility_name: str = ""
    facility_oid: str = ""

    # Patient info
    patient_id: str = ""
    patient_mrn: str = ""
    patient_name: str = ""
    patient_dob: date | None = None
    patient_gender: str = ""  # M or F

    # Event info
    event_id: str = ""
    event_date: date | None = None
    event_type: str = "clabsi"  # clabsi, lcbi, etc.
    location_code: str = ""  # CDC location code

    # BSI-specific data
    organism: str = ""
    organism_code: str = ""  # SNOMED code
    device_type: str = "central_line"
    device_days: int | None = None

    # Classification
    is_clabsi: bool = True
    is_mbi_lcbi: bool = False
    secondary_bsi: bool = False

    # Author info
    author_name: str = ""
    author_id: str = ""


class CDAGenerator:
    """Generates CDA R2 documents for NHSN HAI submission."""

    def __init__(
        self,
        facility_id: str,
        facility_name: str,
        facility_oid: str | None = None,
    ):
        """Initialize the CDA generator.

        Args:
            facility_id: NHSN facility ID
            facility_name: Facility name
            facility_oid: Facility OID (optional, will generate if not provided)
        """
        self.facility_id = facility_id
        self.facility_name = facility_name
        self.facility_oid = facility_oid or f"{NHSN_ROOT_OID}.{facility_id}"

    def generate_bsi_document(self, doc: BSICDADocument) -> str:
        """Generate a BSI CDA document.

        Args:
            doc: BSI document data

        Returns:
            CDA XML string
        """
        # Set facility info if not provided
        if not doc.facility_id:
            doc.facility_id = self.facility_id
        if not doc.facility_name:
            doc.facility_name = self.facility_name
        if not doc.facility_oid:
            doc.facility_oid = self.facility_oid

        root = self._create_cda_root()

        # Add header components
        self._add_type_id(root)
        self._add_template_ids(root, "bsi")
        self._add_document_id(root, doc.document_id)
        self._add_code(root, HAI_REPORT_CODES["bsi"], "Healthcare Associated Infection Report")
        self._add_title(root, "BSI Event Report")
        self._add_effective_time(root, doc.creation_time)
        self._add_confidentiality_code(root)
        self._add_language_code(root)

        # Record target (patient)
        self._add_record_target(root, doc)

        # Author
        self._add_author(root, doc)

        # Custodian (facility)
        self._add_custodian(root, doc)

        # Component (body with BSI data)
        self._add_bsi_body(root, doc)

        return self._to_xml_string(root)

    def generate_batch(self, documents: list[BSICDADocument]) -> list[str]:
        """Generate multiple CDA documents.

        Args:
            documents: List of BSI document data

        Returns:
            List of CDA XML strings
        """
        return [self.generate_bsi_document(doc) for doc in documents]

    def _create_cda_root(self) -> ET.Element:
        """Create the CDA root element with namespaces."""
        # Register namespaces
        ET.register_namespace("", CDA_NS)
        ET.register_namespace("sdtc", SDTC_NS)
        ET.register_namespace("xsi", XSI_NS)

        root = ET.Element(
            f"{{{CDA_NS}}}ClinicalDocument",
            {
                f"{{{XSI_NS}}}schemaLocation": f"{CDA_NS} CDA.xsd",
            }
        )
        return root

    def _add_type_id(self, root: ET.Element) -> None:
        """Add CDA type identifier."""
        ET.SubElement(
            root, f"{{{CDA_NS}}}typeId",
            root="2.16.840.1.113883.1.3",
            extension="POCD_HD000040"
        )

    def _add_template_ids(self, root: ET.Element, report_type: str) -> None:
        """Add template IDs for HAI reporting."""
        # General HAI Report template
        ET.SubElement(
            root, f"{{{CDA_NS}}}templateId",
            root="2.16.840.1.113883.10.20.5.4.25"
        )
        # BSI Numerator template
        if report_type in ("bsi", "clabsi"):
            ET.SubElement(
                root, f"{{{CDA_NS}}}templateId",
                root="2.16.840.1.113883.10.20.5.36"
            )

    def _add_document_id(self, root: ET.Element, doc_id: str) -> None:
        """Add document ID."""
        ET.SubElement(
            root, f"{{{CDA_NS}}}id",
            root=self.facility_oid,
            extension=doc_id
        )

    def _add_code(self, root: ET.Element, code: str, display_name: str) -> None:
        """Add document type code."""
        ET.SubElement(
            root, f"{{{CDA_NS}}}code",
            code=code,
            codeSystem=LOINC_OID,
            codeSystemName="LOINC",
            displayName=display_name
        )

    def _add_title(self, root: ET.Element, title: str) -> None:
        """Add document title."""
        title_elem = ET.SubElement(root, f"{{{CDA_NS}}}title")
        title_elem.text = title

    def _add_effective_time(self, root: ET.Element, dt: datetime) -> None:
        """Add effective time."""
        ET.SubElement(
            root, f"{{{CDA_NS}}}effectiveTime",
            value=dt.strftime("%Y%m%d%H%M%S")
        )

    def _add_confidentiality_code(self, root: ET.Element) -> None:
        """Add confidentiality code (Normal)."""
        ET.SubElement(
            root, f"{{{CDA_NS}}}confidentialityCode",
            code="N",
            codeSystem="2.16.840.1.113883.5.25"
        )

    def _add_language_code(self, root: ET.Element) -> None:
        """Add language code."""
        ET.SubElement(root, f"{{{CDA_NS}}}languageCode", code="en-US")

    def _add_record_target(self, root: ET.Element, doc: BSICDADocument) -> None:
        """Add patient (record target) information."""
        record_target = ET.SubElement(root, f"{{{CDA_NS}}}recordTarget")
        patient_role = ET.SubElement(record_target, f"{{{CDA_NS}}}patientRole")

        # Patient ID (MRN)
        ET.SubElement(
            patient_role, f"{{{CDA_NS}}}id",
            root=doc.facility_oid,
            extension=doc.patient_mrn
        )

        # Patient demographics
        patient = ET.SubElement(patient_role, f"{{{CDA_NS}}}patient")

        # Name
        if doc.patient_name:
            name = ET.SubElement(patient, f"{{{CDA_NS}}}name")
            parts = doc.patient_name.split()
            if len(parts) >= 2:
                given = ET.SubElement(name, f"{{{CDA_NS}}}given")
                given.text = parts[0]
                family = ET.SubElement(name, f"{{{CDA_NS}}}family")
                family.text = parts[-1]
            else:
                given = ET.SubElement(name, f"{{{CDA_NS}}}given")
                given.text = doc.patient_name

        # Gender
        if doc.patient_gender:
            ET.SubElement(
                patient, f"{{{CDA_NS}}}administrativeGenderCode",
                code=doc.patient_gender,
                codeSystem="2.16.840.1.113883.5.1"
            )

        # Birth time
        if doc.patient_dob:
            ET.SubElement(
                patient, f"{{{CDA_NS}}}birthTime",
                value=doc.patient_dob.strftime("%Y%m%d")
            )

    def _add_author(self, root: ET.Element, doc: BSICDADocument) -> None:
        """Add author information."""
        author = ET.SubElement(root, f"{{{CDA_NS}}}author")

        # Author time
        ET.SubElement(
            author, f"{{{CDA_NS}}}time",
            value=doc.creation_time.strftime("%Y%m%d%H%M%S")
        )

        assigned_author = ET.SubElement(author, f"{{{CDA_NS}}}assignedAuthor")

        # Author ID
        ET.SubElement(
            assigned_author, f"{{{CDA_NS}}}id",
            root=doc.facility_oid,
            extension=doc.author_id or "system"
        )

        # Author name
        if doc.author_name:
            assigned_person = ET.SubElement(
                assigned_author, f"{{{CDA_NS}}}assignedPerson"
            )
            name = ET.SubElement(assigned_person, f"{{{CDA_NS}}}name")
            name_text = ET.SubElement(name, f"{{{CDA_NS}}}given")
            name_text.text = doc.author_name

        # Represented organization
        org = ET.SubElement(
            assigned_author, f"{{{CDA_NS}}}representedOrganization"
        )
        ET.SubElement(org, f"{{{CDA_NS}}}id", root=doc.facility_oid)
        org_name = ET.SubElement(org, f"{{{CDA_NS}}}name")
        org_name.text = doc.facility_name

    def _add_custodian(self, root: ET.Element, doc: BSICDADocument) -> None:
        """Add custodian (facility) information."""
        custodian = ET.SubElement(root, f"{{{CDA_NS}}}custodian")
        assigned_custodian = ET.SubElement(
            custodian, f"{{{CDA_NS}}}assignedCustodian"
        )
        org = ET.SubElement(
            assigned_custodian, f"{{{CDA_NS}}}representedCustodianOrganization"
        )

        ET.SubElement(org, f"{{{CDA_NS}}}id", root=doc.facility_oid)
        name = ET.SubElement(org, f"{{{CDA_NS}}}name")
        name.text = doc.facility_name

    def _add_bsi_body(self, root: ET.Element, doc: BSICDADocument) -> None:
        """Add BSI event data in structured body."""
        component = ET.SubElement(root, f"{{{CDA_NS}}}component")
        structured_body = ET.SubElement(component, f"{{{CDA_NS}}}structuredBody")

        # Infection details section
        section_component = ET.SubElement(structured_body, f"{{{CDA_NS}}}component")
        section = ET.SubElement(section_component, f"{{{CDA_NS}}}section")

        # Section template
        ET.SubElement(
            section, f"{{{CDA_NS}}}templateId",
            root="2.16.840.1.113883.10.20.5.4.26"
        )

        # Section code
        ET.SubElement(
            section, f"{{{CDA_NS}}}code",
            code="51899-3",
            codeSystem=LOINC_OID,
            codeSystemName="LOINC",
            displayName="Details"
        )

        # Section title
        title = ET.SubElement(section, f"{{{CDA_NS}}}title")
        title.text = "Infection Details"

        # Section text (human readable)
        text = ET.SubElement(section, f"{{{CDA_NS}}}text")
        self._add_bsi_narrative(text, doc)

        # Section entries (structured data)
        self._add_bsi_entries(section, doc)

    def _add_bsi_narrative(self, text: ET.Element, doc: BSICDADocument) -> None:
        """Add human-readable narrative for BSI event."""
        table = ET.SubElement(text, "table")

        # Event date row
        tr = ET.SubElement(table, "tr")
        td1 = ET.SubElement(tr, "td")
        td1.text = "Event Date"
        td2 = ET.SubElement(tr, "td")
        td2.text = doc.event_date.strftime("%Y-%m-%d") if doc.event_date else "Unknown"

        # Event type row
        tr = ET.SubElement(table, "tr")
        td1 = ET.SubElement(tr, "td")
        td1.text = "Event Type"
        td2 = ET.SubElement(tr, "td")
        td2.text = "CLABSI" if doc.is_clabsi else "BSI"

        # Organism row
        tr = ET.SubElement(table, "tr")
        td1 = ET.SubElement(tr, "td")
        td1.text = "Organism"
        td2 = ET.SubElement(tr, "td")
        td2.text = doc.organism or "Unknown"

        # Location row
        tr = ET.SubElement(table, "tr")
        td1 = ET.SubElement(tr, "td")
        td1.text = "Location"
        td2 = ET.SubElement(tr, "td")
        td2.text = doc.location_code or "Unknown"

        # Device days row
        if doc.device_days is not None:
            tr = ET.SubElement(table, "tr")
            td1 = ET.SubElement(tr, "td")
            td1.text = "Device Days"
            td2 = ET.SubElement(tr, "td")
            td2.text = str(doc.device_days)

    def _add_bsi_entries(self, section: ET.Element, doc: BSICDADocument) -> None:
        """Add structured BSI entries."""
        # Event date entry
        entry = ET.SubElement(section, f"{{{CDA_NS}}}entry")
        observation = ET.SubElement(
            entry, f"{{{CDA_NS}}}observation",
            classCode="OBS", moodCode="EVN"
        )

        # Infection type
        ET.SubElement(
            observation, f"{{{CDA_NS}}}templateId",
            root="2.16.840.1.113883.10.20.5.6.139"
        )

        event_code = BSI_EVENT_CODES.get(doc.event_type, BSI_EVENT_CODES["clabsi"])
        ET.SubElement(
            observation, f"{{{CDA_NS}}}code",
            code=event_code,
            codeSystem=CDC_NHSN_OID,
            displayName="BSI Event Type"
        )

        ET.SubElement(observation, f"{{{CDA_NS}}}statusCode", code="completed")

        # Event date
        if doc.event_date:
            ET.SubElement(
                observation, f"{{{CDA_NS}}}effectiveTime",
                value=doc.event_date.strftime("%Y%m%d")
            )

        # Organism entry
        if doc.organism:
            org_entry = ET.SubElement(section, f"{{{CDA_NS}}}entry")
            org_obs = ET.SubElement(
                org_entry, f"{{{CDA_NS}}}observation",
                classCode="OBS", moodCode="EVN"
            )

            ET.SubElement(
                org_obs, f"{{{CDA_NS}}}code",
                code="41852-5",
                codeSystem=LOINC_OID,
                displayName="Microorganism identified"
            )

            value = ET.SubElement(
                org_obs, f"{{{CDA_NS}}}value",
                {f"{{{XSI_NS}}}type": "CD"}
            )
            value.set("displayName", doc.organism)
            if doc.organism_code:
                value.set("code", doc.organism_code)
                value.set("codeSystem", SNOMED_OID)

        # Location entry
        if doc.location_code:
            loc_entry = ET.SubElement(section, f"{{{CDA_NS}}}entry")
            loc_obs = ET.SubElement(
                loc_entry, f"{{{CDA_NS}}}observation",
                classCode="OBS", moodCode="EVN"
            )

            ET.SubElement(
                loc_obs, f"{{{CDA_NS}}}code",
                code="2250-8",
                codeSystem=LOINC_OID,
                displayName="Location"
            )

            value = ET.SubElement(
                loc_obs, f"{{{CDA_NS}}}value",
                {f"{{{XSI_NS}}}type": "CD"}
            )
            value.set("code", doc.location_code)
            value.set("codeSystem", CDC_NHSN_OID)

    def _to_xml_string(self, root: ET.Element) -> str:
        """Convert element tree to formatted XML string."""
        # Convert to string
        rough_string = ET.tostring(root, encoding="unicode")

        # Pretty print
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ", encoding=None)


def create_bsi_document_from_candidate(
    candidate: Any,
    facility_id: str,
    facility_name: str,
    author_name: str = "System",
) -> BSICDADocument:
    """Create a BSI CDA document from an HAI candidate.

    Args:
        candidate: HAICandidate object
        facility_id: NHSN facility ID
        facility_name: Facility name
        author_name: Name of the author/preparer

    Returns:
        BSICDADocument ready for CDA generation
    """
    return BSICDADocument(
        document_id=str(uuid.uuid4()),
        creation_time=datetime.now(),
        facility_id=facility_id,
        facility_name=facility_name,
        patient_id=candidate.patient.fhir_id,
        patient_mrn=candidate.patient.mrn,
        patient_name=candidate.patient.name,
        patient_dob=getattr(candidate.patient, 'dob', None),
        patient_gender=getattr(candidate.patient, 'gender', ''),
        event_id=candidate.id,
        event_date=candidate.culture.collection_date.date() if candidate.culture.collection_date else None,
        event_type=candidate.hai_type.value,
        location_code=getattr(candidate, 'location_code', ''),
        organism=candidate.culture.organism or '',
        device_days=candidate.device_days_at_culture,
        is_clabsi=candidate.hai_type.value == "clabsi",
        author_name=author_name,
    )
