#!/usr/bin/env python3
"""Generate NHSN CLABSI test data and load to HAPI FHIR.

This script creates synthetic patients with CLABSI scenarios:
- Patients with central lines (DeviceUseStatement)
- Positive blood cultures (DiagnosticReport + Observation)
- Various timing scenarios for NHSN criteria testing

Usage:
    python generate_nhsn_test_data.py
    python generate_nhsn_test_data.py --fhir-url http://localhost:8081/fhir
    python generate_nhsn_test_data.py --dry-run
"""

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from typing import Any

import requests

# FHIR server configuration
DEFAULT_FHIR_URL = "http://localhost:8081/fhir"

# CCHMC-specific locations for pediatric context
LOCATIONS = [
    {"code": "T5A", "display": "PICU"},
    {"code": "T5B", "display": "CICU"},
    {"code": "T4", "display": "NICU"},
    {"code": "G5S", "display": "Oncology"},
    {"code": "G6N", "display": "BMT"},
    {"code": "A6N", "display": "Hospital Medicine"},
]

# Central line types with SNOMED codes
CENTRAL_LINE_TYPES = [
    {"code": "52124006", "display": "Central venous catheter", "short": "CVC"},
    {"code": "303728004", "display": "Peripherally inserted central catheter", "short": "PICC"},
    {"code": "706689003", "display": "Tunneled central venous catheter", "short": "Tunneled CVC"},
]

# Body sites for central lines
LINE_SITES = [
    {"code": "20699002", "display": "Right subclavian vein"},
    {"code": "48345005", "display": "Left subclavian vein"},
    {"code": "83419000", "display": "Right internal jugular vein"},
    {"code": "12123001", "display": "Left internal jugular vein"},
    {"code": "7657000", "display": "Right femoral vein"},
    {"code": "83978002", "display": "Left femoral vein"},
    {"code": "50094009", "display": "Right basilic vein"},  # PICC
]

# Organisms for blood cultures
# Pathogenic organisms (clear CLABSI candidates)
PATHOGENIC_ORGANISMS = [
    {"code": "3092008", "display": "Staphylococcus aureus"},
    {"code": "112283007", "display": "Escherichia coli"},
    {"code": "56415008", "display": "Klebsiella pneumoniae"},
    {"code": "52499004", "display": "Pseudomonas aeruginosa"},
    {"code": "4298009", "display": "Candida albicans"},
    {"code": "76327009", "display": "Enterococcus faecalis"},
]

# Contaminant organisms (require 2 positive cultures)
CONTAMINANT_ORGANISMS = [
    {"code": "116197008", "display": "Coagulase-negative staphylococci"},
    {"code": "83512006", "display": "Staphylococcus epidermidis"},
    {"code": "5765005", "display": "Corynebacterium species"},
    {"code": "35408001", "display": "Micrococcus species"},
]

# Alternative infection sources (for non-CLABSI scenarios)
ALTERNATIVE_SOURCES = [
    "Pneumonia",
    "Urinary tract infection",
    "Intra-abdominal infection",
    "Skin/soft tissue infection",
]

# Clinical note authors
NOTE_AUTHORS = [
    "David Haslam, MD",
    "Jennifer Smith, MD",
    "Michael Chen, MD",
    "Sarah Johnson, NP",
    "Robert Williams, MD",
    "Emily Davis, PA-C",
    "James Wilson, MD",
    "Amanda Martinez, MD",
]


def random_author() -> str:
    """Return a random note author."""
    return random.choice(NOTE_AUTHORS)


# Pediatric first names
FIRST_NAMES = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
    "Isabella", "William", "Mia", "James", "Charlotte", "Benjamin", "Amelia",
    "Lucas", "Harper", "Henry", "Evelyn", "Alexander",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
]


def generate_patient_id() -> str:
    return f"nhsn-test-{uuid.uuid4().hex[:8]}"


def generate_mrn() -> str:
    return f"NHSN{random.randint(100000, 999999)}"


def random_pediatric_age() -> tuple[str, int]:
    """Generate random pediatric age, return (birthDate, age_years)."""
    age_days = random.choices(
        [
            random.randint(1, 28),      # Neonate
            random.randint(29, 365),    # Infant
            random.randint(366, 1825),  # Toddler (1-5)
            random.randint(1826, 4380), # Child (5-12)
            random.randint(4381, 6570), # Adolescent (12-18)
        ],
        weights=[15, 20, 25, 25, 15],
    )[0]

    birth_date = datetime.now() - timedelta(days=age_days)
    age_years = age_days // 365
    return birth_date.strftime("%Y-%m-%d"), age_years


def create_patient(patient_id: str, mrn: str) -> dict:
    """Create a FHIR Patient resource."""
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    birth_date, _ = random_pediatric_age()
    gender = random.choice(["male", "female"])

    return {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [
            {
                "type": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                        "code": "MR",
                        "display": "Medical Record Number"
                    }]
                },
                "value": mrn
            }
        ],
        "name": [
            {
                "use": "official",
                "family": last_name,
                "given": [first_name]
            }
        ],
        "gender": gender,
        "birthDate": birth_date,
    }


def create_encounter(patient_id: str, encounter_id: str, location: dict,
                    start_date: datetime) -> dict:
    """Create a FHIR Encounter resource."""
    return {
        "resourceType": "Encounter",
        "id": encounter_id,
        "status": "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "IMP",
            "display": "inpatient encounter"
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": start_date.isoformat()},
        "location": [
            {
                "location": {
                    "display": f"{location['code']} - {location['display']}"
                },
                "status": "active"
            }
        ]
    }


def create_device(device_id: str, line_type: dict) -> dict:
    """Create a FHIR Device resource for a central line."""
    return {
        "resourceType": "Device",
        "id": device_id,
        "type": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": line_type["code"],
                "display": line_type["display"]
            }]
        },
        "status": "active"
    }


def create_device_use_statement(
    patient_id: str,
    device_id: str,
    line_type: dict,
    site: dict,
    insertion_date: datetime,
    removal_date: datetime | None = None,
) -> dict:
    """Create a FHIR DeviceUseStatement for a central line."""
    resource = {
        "resourceType": "DeviceUseStatement",
        "id": f"dus-{uuid.uuid4().hex[:8]}",
        "status": "completed" if removal_date else "active",
        "subject": {"reference": f"Patient/{patient_id}"},
        "device": {
            "reference": {"reference": f"Device/{device_id}"},
            "concept": {
                "coding": [{
                    "system": "http://snomed.info/sct",
                    "code": line_type["code"],
                    "display": line_type["display"]
                }]
            }
        },
        "timingPeriod": {
            "start": insertion_date.isoformat()
        },
        "bodySite": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": site["code"],
                "display": site["display"]
            }]
        }
    }

    if removal_date:
        resource["timingPeriod"]["end"] = removal_date.isoformat()

    return resource


def create_blood_culture_report(
    patient_id: str,
    report_id: str,
    collection_date: datetime,
    organism: dict | None,
    is_positive: bool = True,
) -> dict:
    """Create a FHIR DiagnosticReport for blood culture."""
    conclusion = "Positive" if is_positive else "No growth"
    if is_positive and organism:
        conclusion = f"Positive for {organism['display']}"

    resource = {
        "resourceType": "DiagnosticReport",
        "id": report_id,
        "status": "final",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code": "MB",
                "display": "Microbiology"
            }]
        }],
        "code": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "600-7",
                "display": "Blood culture"
            }]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collection_date.isoformat(),
        "issued": (collection_date + timedelta(hours=48)).isoformat(),
        "conclusion": conclusion,
    }

    if is_positive and organism:
        resource["conclusionCode"] = [{
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": organism["code"],
                "display": organism["display"]
            }]
        }]

    return resource


def create_clinical_note(
    patient_id: str,
    note_id: str,
    note_date: datetime,
    note_type: str,
    content: str,
    author: str | None = None,
) -> dict:
    """Create a FHIR DocumentReference for a clinical note."""
    import base64

    type_codes = {
        "progress_note": {"code": "11506-3", "display": "Progress note"},
        "id_consult": {"code": "11488-4", "display": "Consultation note"},
    }

    type_info = type_codes.get(note_type, type_codes["progress_note"])

    doc_ref = {
        "resourceType": "DocumentReference",
        "id": note_id,
        "status": "current",
        "type": {
            "coding": [{
                "system": "http://loinc.org",
                "code": type_info["code"],
                "display": type_info["display"]
            }]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": note_date.isoformat(),
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "data": base64.b64encode(content.encode()).decode()
            }
        }]
    }

    # Add author if provided
    if author:
        doc_ref["author"] = [{"display": author}]

    return doc_ref


# ============================================================================
# CLABSI Test Scenarios
# ============================================================================

def scenario_clear_clabsi(base_time: datetime) -> dict:
    """Clear CLABSI: pathogenic organism, line >2 days, no alternative source."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=7)
    line_insertion = base_time - timedelta(days=5)
    culture_date = base_time - timedelta(hours=random.randint(12, 48))

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = random.choice(PATHOGENIC_ORGANISMS)

    note_content = f"""
ASSESSMENT/PLAN:
Patient with {organism['display']} bacteremia. Central line in place for {(culture_date - line_insertion).days} days.
No clear alternative source identified. Recommend line removal and continued IV antibiotics.

ID CONSULT:
Blood cultures positive for {organism['display']}.
Review of recent imaging shows no evidence of pneumonia or intra-abdominal source.
Urinalysis negative. No skin/soft tissue infection noted.
Most likely catheter-related bloodstream infection given line dwell time and organism.
"""

    return {
        "scenario": "clear_clabsi",
        "description": f"Clear CLABSI: {organism['display']}, line {(culture_date - line_insertion).days} days",
        "expected_result": "should_be_clabsi",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
            create_clinical_note(patient_id, f"note-{uuid.uuid4().hex[:8]}",
                               culture_date + timedelta(hours=6), "id_consult", note_content,
                               author=random_author()),
        ]
    }


def scenario_alternative_source(base_time: datetime) -> dict:
    """BSI with clear alternative source (pneumonia) - NOT CLABSI."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=10)
    line_insertion = base_time - timedelta(days=8)
    culture_date = base_time - timedelta(hours=random.randint(12, 48))

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = random.choice([o for o in PATHOGENIC_ORGANISMS if "Pseudomonas" in o["display"] or "Klebsiella" in o["display"]])

    note_content = f"""
ASSESSMENT/PLAN:
Patient with {organism['display']} bacteremia in setting of ventilator-associated pneumonia.
Chest X-ray shows new right lower lobe consolidation.
Respiratory cultures also growing {organism['display']}.
Blood cultures likely secondary to pulmonary source.

PHYSICAL EXAM:
Decreased breath sounds RLL, coarse crackles bilaterally.
Central line site clean, no erythema or drainage.
"""

    return {
        "scenario": "alternative_source_pneumonia",
        "description": f"BSI secondary to pneumonia: {organism['display']}",
        "expected_result": "not_clabsi",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
            create_clinical_note(patient_id, f"note-{uuid.uuid4().hex[:8]}",
                               culture_date + timedelta(hours=6), "progress_note", note_content,
                               author=random_author()),
        ]
    }


def scenario_contaminant_single(base_time: datetime) -> dict:
    """Single positive culture for contaminant organism - excluded."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=5)
    line_insertion = base_time - timedelta(days=4)
    culture_date = base_time - timedelta(hours=random.randint(12, 48))

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = random.choice(CONTAMINANT_ORGANISMS)

    return {
        "scenario": "contaminant_single",
        "description": f"Single contaminant: {organism['display']}",
        "expected_result": "excluded_contaminant",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
        ]
    }


def scenario_contaminant_confirmed(base_time: datetime) -> dict:
    """Two positive cultures for contaminant organism - valid CLABSI."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id1 = f"bc-{uuid.uuid4().hex[:8]}"
    report_id2 = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=6)
    line_insertion = base_time - timedelta(days=5)
    culture_date1 = base_time - timedelta(hours=36)
    culture_date2 = culture_date1 + timedelta(hours=18)  # Second culture next day

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = random.choice(CONTAMINANT_ORGANISMS)

    note_content = f"""
ASSESSMENT/PLAN:
Patient with two positive blood cultures for {organism['display']} drawn on separate days.
Central line in place for {(culture_date1 - line_insertion).days} days.
No alternative source identified. Meets CLABSI criteria per NHSN.
"""

    return {
        "scenario": "contaminant_confirmed",
        "description": f"Confirmed contaminant (2 cultures): {organism['display']}",
        "expected_result": "should_be_clabsi",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture_report(patient_id, report_id1, culture_date1, organism),
            create_blood_culture_report(patient_id, report_id2, culture_date2, organism),
            create_clinical_note(patient_id, f"note-{uuid.uuid4().hex[:8]}",
                               culture_date2 + timedelta(hours=6), "progress_note", note_content,
                               author=random_author()),
        ]
    }


def scenario_insufficient_line_days(base_time: datetime) -> dict:
    """Line in place <2 days - does not meet CLABSI criteria."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=2)
    line_insertion = base_time - timedelta(days=1)  # Only 1 day before culture
    culture_date = base_time - timedelta(hours=random.randint(4, 12))

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = random.choice(PATHOGENIC_ORGANISMS)

    return {
        "scenario": "insufficient_line_days",
        "description": f"Line <2 days: {organism['display']}",
        "expected_result": "excluded_timing",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
        ]
    }


def scenario_line_removed(base_time: datetime) -> dict:
    """Line removed before culture - but within 1 day grace period."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=8)
    line_insertion = base_time - timedelta(days=7)
    line_removal = base_time - timedelta(hours=36)
    culture_date = base_time - timedelta(hours=12)  # Within 1 day of removal

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = random.choice(PATHOGENIC_ORGANISMS)

    note_content = f"""
ASSESSMENT/PLAN:
{organism['display']} bacteremia 24 hours after central line removal.
Line was in place for {(line_removal - line_insertion).days} days prior to removal.
Per NHSN criteria, BSI within 1 day of line removal can be attributed to line.
"""

    return {
        "scenario": "line_removed_within_grace",
        "description": f"Line removed, culture within 1 day: {organism['display']}",
        "expected_result": "should_be_clabsi",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site,
                                       line_insertion, line_removal),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
            create_clinical_note(patient_id, f"note-{uuid.uuid4().hex[:8]}",
                               culture_date + timedelta(hours=6), "progress_note", note_content,
                               author=random_author()),
        ]
    }


def scenario_no_central_line(base_time: datetime) -> dict:
    """BSI without central line - not a CLABSI candidate."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=3)
    culture_date = base_time - timedelta(hours=random.randint(12, 48))

    location = random.choice(LOCATIONS)
    organism = random.choice(PATHOGENIC_ORGANISMS)

    return {
        "scenario": "no_central_line",
        "description": f"No central line: {organism['display']}",
        "expected_result": "not_clabsi_candidate",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
        ]
    }


def scenario_mbi_lcbi(base_time: datetime) -> dict:
    """Mucosal barrier injury LCBI - oncology patient with gut organism."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=14)
    line_insertion = base_time - timedelta(days=12)
    culture_date = base_time - timedelta(hours=random.randint(12, 48))

    # Oncology/BMT location for MBI context
    location = random.choice([l for l in LOCATIONS if l["code"] in ["G5S", "G6N"]])
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    # Gut flora organism
    organism = {"code": "112283007", "display": "Escherichia coli"}

    note_content = f"""
ASSESSMENT/PLAN:
Patient is day +10 post allogeneic BMT with severe neutropenia (ANC 0) and Grade 2 mucositis.
{organism['display']} bacteremia - likely MBI-LCBI given neutropenia and mucositis.
Central line in place but organism consistent with gut translocation.

HOSPITAL COURSE:
Patient received conditioning chemotherapy with significant mucositis.
Currently with severe neutropenia expected to persist for several more days.
"""

    return {
        "scenario": "mbi_lcbi",
        "description": f"MBI-LCBI candidate: {organism['display']} in BMT patient",
        "expected_result": "mbi_lcbi_not_clabsi",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
            create_clinical_note(patient_id, f"note-{uuid.uuid4().hex[:8]}",
                               culture_date + timedelta(hours=6), "progress_note", note_content,
                               author=random_author()),
        ]
    }


def scenario_ambiguous(base_time: datetime) -> dict:
    """Ambiguous case requiring IP review."""
    patient_id = generate_patient_id()
    mrn = generate_mrn()
    encounter_id = f"enc-{uuid.uuid4().hex[:8]}"
    device_id = f"dev-{uuid.uuid4().hex[:8]}"
    report_id = f"bc-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=10)
    line_insertion = base_time - timedelta(days=8)
    culture_date = base_time - timedelta(hours=random.randint(12, 48))

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = random.choice(PATHOGENIC_ORGANISMS)

    note_content = f"""
ASSESSMENT/PLAN:
Patient with {organism['display']} bacteremia. Multiple potential sources:
- Central line in place for {(culture_date - line_insertion).days} days
- Recent abdominal surgery with possible intra-abdominal source
- Mild respiratory symptoms, chest X-ray with possible infiltrate

Difficult to determine primary source. Will continue antibiotics and monitor.
Line site appears clean but cannot rule out catheter-related infection.
"""

    return {
        "scenario": "ambiguous_case",
        "description": f"Ambiguous: {organism['display']} with multiple possible sources",
        "expected_result": "needs_ip_review",
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, encounter_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture_report(patient_id, report_id, culture_date, organism),
            create_clinical_note(patient_id, f"note-{uuid.uuid4().hex[:8]}",
                               culture_date + timedelta(hours=6), "progress_note", note_content,
                               author=random_author()),
        ]
    }


# All scenario generators
SCENARIO_GENERATORS = [
    scenario_clear_clabsi,
    scenario_clear_clabsi,  # Weight: more clear cases
    scenario_alternative_source,
    scenario_contaminant_single,
    scenario_contaminant_confirmed,
    scenario_insufficient_line_days,
    scenario_line_removed,
    scenario_no_central_line,
    scenario_mbi_lcbi,
    scenario_ambiguous,
]


def load_resource(fhir_url: str, resource: dict, dry_run: bool = False) -> bool:
    """Load a single resource to FHIR server."""
    resource_type = resource["resourceType"]
    resource_id = resource.get("id", str(uuid.uuid4()))

    url = f"{fhir_url}/{resource_type}/{resource_id}"

    if dry_run:
        print(f"  [DRY RUN] Would PUT {resource_type}/{resource_id}")
        return True

    try:
        response = requests.put(
            url,
            json=resource,
            headers={"Content-Type": "application/fhir+json"},
            timeout=10,
        )
        if response.status_code in (200, 201):
            return True
        else:
            print(f"  ERROR: {resource_type}/{resource_id} - {response.status_code}: {response.text[:100]}")
            return False
    except requests.RequestException as e:
        print(f"  ERROR: {resource_type}/{resource_id} - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate NHSN CLABSI test data for HAPI FHIR"
    )
    parser.add_argument(
        "--fhir-url",
        default=DEFAULT_FHIR_URL,
        help=f"FHIR server URL (default: {DEFAULT_FHIR_URL})",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of scenarios to generate (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually load data, just print what would be done",
    )
    parser.add_argument(
        "--all-scenarios",
        action="store_true",
        help="Generate one of each scenario type instead of random selection",
    )

    args = parser.parse_args()

    # Check FHIR server connectivity
    if not args.dry_run:
        try:
            response = requests.get(f"{args.fhir_url}/metadata", timeout=5)
            response.raise_for_status()
            print(f"Connected to FHIR server at {args.fhir_url}")
        except requests.RequestException as e:
            print(f"ERROR: Cannot connect to FHIR server: {e}")
            sys.exit(1)

    # Generate scenarios
    base_time = datetime.now()
    scenarios = []

    if args.all_scenarios:
        # One of each unique scenario
        unique_generators = list(set(SCENARIO_GENERATORS))
        for gen in unique_generators:
            scenarios.append(gen(base_time))
    else:
        # Random selection
        for _ in range(args.count):
            generator = random.choice(SCENARIO_GENERATORS)
            scenarios.append(generator(base_time))

    print(f"\nGenerating {len(scenarios)} NHSN test scenarios...")
    print("=" * 60)

    total_resources = 0
    loaded_resources = 0

    for i, scenario in enumerate(scenarios, 1):
        print(f"\n[{i}/{len(scenarios)}] {scenario['scenario']}")
        print(f"    {scenario['description']}")
        print(f"    Expected: {scenario['expected_result']}")

        for resource in scenario["resources"]:
            total_resources += 1
            if load_resource(args.fhir_url, resource, args.dry_run):
                loaded_resources += 1

    print("\n" + "=" * 60)
    print(f"Summary: {loaded_resources}/{total_resources} resources loaded")

    if not args.dry_run:
        print(f"\nTest data loaded. Run the NHSN monitor to detect candidates:")
        print(f"  python -m nhsn_reporting.src.runner --once --dry-run")


if __name__ == "__main__":
    main()
