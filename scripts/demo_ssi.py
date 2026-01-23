#!/usr/bin/env python3
"""Generate demo SSI (Surgical Site Infection) candidates for dashboard demonstration.

Creates scenarios covering all SSI types:
1. Superficial Incisional SSI
2. Deep Incisional SSI
3. Organ/Space SSI
4. Not SSI cases

Each case includes realistic clinical notes with evidence to help
determine the correct classification.

Usage:
    # Create one SSI + one Not SSI pair
    python demo_ssi.py

    # Create specific scenario types
    python demo_ssi.py --scenario superficial
    python demo_ssi.py --scenario deep
    python demo_ssi.py --scenario organ-space
    python demo_ssi.py --scenario not-ssi

    # Create all scenario types
    python demo_ssi.py --all

    # Dry run (don't upload to FHIR)
    python demo_ssi.py --dry-run
"""

import argparse
import base64
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

# FHIR server
DEFAULT_FHIR_URL = "http://localhost:8081/fhir"

# Locations
LOCATIONS = [
    {"code": "OR1", "display": "Operating Room 1"},
    {"code": "OR2", "display": "Operating Room 2"},
    {"code": "SURG", "display": "Surgery Floor"},
    {"code": "ICU", "display": "Surgical ICU"},
    {"code": "A6N", "display": "Hospital Medicine"},
]

# NHSN Operative Procedure Categories
PROCEDURES = {
    "colectomy": {
        "code": "44140",
        "display": "Sigmoid colectomy",
        "nhsn_category": "COLO",
        "wound_class": 2,  # Clean-contaminated
        "duration": 180,
        "surveillance_days": 30,
    },
    "appendectomy": {
        "code": "44950",
        "display": "Appendectomy, laparoscopic",
        "nhsn_category": "APPY",
        "wound_class": 3,  # Contaminated
        "duration": 60,
        "surveillance_days": 30,
    },
    "cholecystectomy": {
        "code": "47562",
        "display": "Laparoscopic cholecystectomy",
        "nhsn_category": "CHOL",
        "wound_class": 2,
        "duration": 75,
        "surveillance_days": 30,
    },
    "total_knee": {
        "code": "27447",
        "display": "Total knee arthroplasty",
        "nhsn_category": "KPRO",
        "wound_class": 1,  # Clean
        "duration": 120,
        "implant": True,
        "surveillance_days": 90,
    },
    "cabg": {
        "code": "33533",
        "display": "CABG x3 with LIMA",
        "nhsn_category": "CABG",
        "wound_class": 1,
        "duration": 300,
        "implant": True,
        "surveillance_days": 90,
    },
}

# Organisms for wound cultures
ORGANISMS = {
    "staph_aureus": {"code": "3092008", "display": "Staphylococcus aureus"},
    "ecoli": {"code": "112283007", "display": "Escherichia coli"},
    "pseudomonas": {"code": "52499004", "display": "Pseudomonas aeruginosa"},
    "enterococcus": {"code": "76327009", "display": "Enterococcus faecalis"},
    "bacteroides": {"code": "36764009", "display": "Bacteroides fragilis"},
    "strep_pyogenes": {"code": "80166006", "display": "Streptococcus pyogenes"},
}

# Patient names
FIRST_NAMES = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
               "Isabella", "William", "Mia", "James", "Charlotte", "Benjamin"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
              "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Thomas"]

WOUND_CLASS_NAMES = {
    1: "Clean",
    2: "Clean-Contaminated",
    3: "Contaminated",
    4: "Dirty-Infected",
}


def generate_mrn():
    return f"SSI{random.randint(10000, 99999)}"


def create_patient(patient_id: str, mrn: str) -> dict:
    """Create a FHIR Patient resource."""
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    age_days = random.randint(365 * 30, 365 * 75)  # 30-75 years for surgical patients
    birth_date = (datetime.now() - timedelta(days=age_days)).strftime("%Y-%m-%d")

    return {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [{
            "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]},
            "value": mrn
        }],
        "name": [{"family": last_name, "given": [first_name]}],
        "gender": random.choice(["male", "female"]),
        "birthDate": birth_date,
    }


def create_encounter(patient_id: str, location: dict, start_date: datetime) -> dict:
    """Create a FHIR Encounter resource."""
    return {
        "resourceType": "Encounter",
        "id": f"enc-{uuid.uuid4().hex[:8]}",
        "status": "in-progress",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient"},
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": start_date.isoformat()},
        "location": [{"location": {"display": f"{location['code']} - {location['display']}"}, "status": "active"}]
    }


def create_procedure(patient_id: str, procedure_info: dict, procedure_date: datetime) -> dict:
    """Create a FHIR Procedure resource."""
    end_time = procedure_date + timedelta(minutes=procedure_info.get("duration", 120))

    resource = {
        "resourceType": "Procedure",
        "id": f"proc-{uuid.uuid4().hex[:8]}",
        "status": "completed",
        "category": {
            "coding": [{
                "system": "http://snomed.info/sct",
                "code": "387713003",
                "display": "Surgical procedure"
            }]
        },
        "code": {
            "coding": [{
                "system": "http://www.ama-assn.org/go/cpt",
                "code": procedure_info["code"],
                "display": procedure_info["display"]
            }]
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "performedPeriod": {
            "start": procedure_date.isoformat(),
            "end": end_time.isoformat()
        },
    }

    # Add wound class extension
    if "wound_class" in procedure_info:
        resource["extension"] = [{
            "url": "http://example.org/fhir/StructureDefinition/wound-class",
            "valueInteger": procedure_info["wound_class"]
        }]

    return resource


def create_wound_culture(patient_id: str, collection_date: datetime, organism: dict,
                         culture_type: str = "wound") -> dict:
    """Create a FHIR DiagnosticReport for wound/tissue culture."""
    culture_codes = {
        "wound": {"code": "6462-6", "display": "Wound culture"},
        "abscess": {"code": "43411-4", "display": "Abscess culture"},
        "tissue": {"code": "6463-4", "display": "Tissue culture"},
        "drain": {"code": "88184-0", "display": "Drain fluid culture"},
    }
    code_info = culture_codes.get(culture_type, culture_codes["wound"])

    return {
        "resourceType": "DiagnosticReport",
        "id": f"wc-{uuid.uuid4().hex[:8]}",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "MB", "display": "Microbiology"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code_info["code"], "display": code_info["display"]}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collection_date.isoformat(),
        "issued": (collection_date + timedelta(hours=48)).isoformat(),
        "conclusion": f"Positive for {organism['display']}",
        "conclusionCode": [{"coding": [{"system": "http://snomed.info/sct", "code": organism["code"], "display": organism["display"]}]}]
    }


def create_imaging_report(patient_id: str, report_date: datetime, modality: str,
                          finding: str, body_site: str) -> dict:
    """Create a FHIR DiagnosticReport for imaging (CT/MRI)."""
    modality_codes = {
        "CT": {"code": "24627-2", "display": "CT Abdomen"},
        "MRI": {"code": "24561-3", "display": "MRI"},
        "XR": {"code": "30746-2", "display": "Chest X-ray"},
    }
    code_info = modality_codes.get(modality, modality_codes["CT"])

    return {
        "resourceType": "DiagnosticReport",
        "id": f"img-{uuid.uuid4().hex[:8]}",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "RAD", "display": "Radiology"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": code_info["code"], "display": code_info["display"]}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": report_date.isoformat(),
        "conclusion": f"{body_site}: {finding}",
    }


def create_clinical_note(patient_id: str, note_date: datetime, content: str, author: str | None = None) -> dict:
    """Create a FHIR DocumentReference for clinical note."""
    doc = {
        "resourceType": "DocumentReference",
        "id": f"note-{uuid.uuid4().hex[:8]}",
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": "11506-3", "display": "Progress note"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": note_date.isoformat(),
        "content": [{"attachment": {"contentType": "text/plain", "data": base64.b64encode(content.encode()).decode()}}]
    }
    if author:
        doc["author"] = [{"display": author}]
    return doc


# Demo authors for realistic notes
DEMO_AUTHORS = [
    "Dr. Sarah Chen, MD",
    "Dr. James Wilson, MD",
    "Dr. Maria Garcia, MD",
    "Dr. Robert Kim, DO",
    "NP Jennifer Brown, MSN, APRN",
]


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================

def create_superficial_ssi_scenario(base_time: datetime) -> dict:
    """Superficial Incisional SSI: purulent drainage from superficial incision."""
    patient_id = f"demo-ssi-sup-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()

    procedure = PROCEDURES["cholecystectomy"]
    procedure_date = base_time - timedelta(days=8)
    admission_date = procedure_date - timedelta(days=1)
    culture_date = base_time - timedelta(days=1)
    days_post_op = 8

    location = random.choice([l for l in LOCATIONS if l["code"] in ["SURG", "A6N"]])
    organism = ORGANISMS["staph_aureus"]
    author = random.choice(DEMO_AUTHORS)

    note_content = f"""
PROGRESS NOTE - {base_time.strftime('%Y-%m-%d %H:%M')}
Author: {author}

SUBJECTIVE:
Patient is post-operative day {days_post_op} from {procedure['display']}.
Reports increasing pain and redness at surgical incision site over past 2 days.
Noticed yellowish discharge from wound this morning. Low-grade fever (38.2C).

OBJECTIVE:
Vitals: T 38.2, HR 92, BP 128/78, RR 16
General: Alert, appears uncomfortable
Abdomen: Soft, mildly tender near incision
Surgical Site:
  - Midline laparoscopic port site with purulent drainage (yellow-green)
  - 2cm erythema surrounding incision
  - Warmth and tenderness at site
  - Superficial incision only - no fascial involvement appreciated
  - No crepitus, no wound dehiscence

LABS/CULTURES:
- Wound culture ({culture_date.strftime('%Y-%m-%d')}): POSITIVE for {organism['display']}
- WBC 12.5
- No abscess on clinical exam - superficial cellulitis with purulent drainage

ASSESSMENT/PLAN:
1. SUPERFICIAL INCISIONAL SURGICAL SITE INFECTION
   - Procedure: {procedure['display']} ({procedure['nhsn_category']})
   - Wound Class: {procedure['wound_class']} ({WOUND_CLASS_NAMES[procedure['wound_class']]})
   - Post-op day {days_post_op} (within 30-day surveillance window)
   - Purulent drainage from superficial incision
   - Positive wound culture for {organism['display']}
   - Meets NHSN criteria for Superficial Incisional SSI

2. Management:
   - Open and drain superficial infection
   - Oral antibiotics (cephalexin)
   - Daily wound care
   - No need for reoperation - superficial only
"""

    return {
        "scenario_type": "superficial_ssi",
        "description": f"Superficial SSI: purulent drainage + positive culture after {procedure['display']}",
        "expected_classification": "Superficial Incisional SSI",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": organism["display"],
        "procedure": procedure["display"],
        "days_post_op": days_post_op,
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_procedure(patient_id, procedure, procedure_date),
            create_wound_culture(patient_id, culture_date, organism),
            create_clinical_note(patient_id, base_time, note_content, author=author),
        ]
    }


def create_deep_ssi_scenario(base_time: datetime) -> dict:
    """Deep Incisional SSI: fascial dehiscence with fever."""
    patient_id = f"demo-ssi-deep-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()

    procedure = PROCEDURES["colectomy"]
    procedure_date = base_time - timedelta(days=12)
    admission_date = procedure_date - timedelta(days=1)
    days_post_op = 12

    location = {"code": "SURG", "display": "Surgery Floor"}
    organism = ORGANISMS["ecoli"]
    author = random.choice(DEMO_AUTHORS)

    note_content = f"""
PROGRESS NOTE - {base_time.strftime('%Y-%m-%d %H:%M')}
Author: {author}

SUBJECTIVE:
Patient is post-operative day {days_post_op} from {procedure['display']}.
Developed high fever overnight (39.2C) with severe abdominal pain at incision.
Patient felt "something give way" in abdomen this morning when coughing.

OBJECTIVE:
Vitals: T 39.2, HR 118, BP 105/65, RR 22
General: Ill-appearing, diaphoretic
Abdomen:
  - Midline incision with FASCIAL DEHISCENCE
  - Purulent serosanguinous drainage from deep tissues
  - Exposed fascia visible through wound
  - Surrounding erythema and induration
  - Deep tissue involvement confirmed - not just superficial

LABS:
- WBC 22.3 with left shift (bands 18%)
- Wound culture sent
- CT Abdomen: Fluid collection at fascial level, no intra-abdominal abscess

ASSESSMENT/PLAN:
1. DEEP INCISIONAL SURGICAL SITE INFECTION
   - Procedure: {procedure['display']} ({procedure['nhsn_category']})
   - Wound Class: {procedure['wound_class']} ({WOUND_CLASS_NAMES[procedure['wound_class']]})
   - Post-op day {days_post_op}
   - MEETS NHSN CRITERIA FOR DEEP INCISIONAL SSI:
     * Fascial dehiscence (spontaneous)
     * Fever >38C (39.2C documented)
     * Localized pain at deep incision
   - Involves fascia/muscle layer - not just superficial

2. Plan:
   - Urgent return to OR for washout and closure
   - IV antibiotics (piperacillin-tazobactam)
   - Wound VAC after debridement
"""

    return {
        "scenario_type": "deep_ssi",
        "description": f"Deep SSI: fascial dehiscence with fever after {procedure['display']}",
        "expected_classification": "Deep Incisional SSI",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": "Pending culture",
        "procedure": procedure["display"],
        "days_post_op": days_post_op,
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_procedure(patient_id, procedure, procedure_date),
            create_imaging_report(patient_id, base_time - timedelta(hours=4), "CT",
                                  "Fluid collection at fascial level", "Abdomen"),
            create_clinical_note(patient_id, base_time, note_content, author=author),
        ]
    }


def create_organ_space_ssi_scenario(base_time: datetime) -> dict:
    """Organ/Space SSI: intra-abdominal abscess post-colectomy."""
    patient_id = f"demo-ssi-organ-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()

    procedure = PROCEDURES["colectomy"]
    procedure_date = base_time - timedelta(days=14)
    admission_date = procedure_date - timedelta(days=1)
    culture_date = base_time - timedelta(days=1)
    days_post_op = 14

    location = {"code": "SURG", "display": "Surgery Floor"}
    organism = ORGANISMS["ecoli"]
    author = random.choice(DEMO_AUTHORS)

    note_content = f"""
PROGRESS NOTE - {base_time.strftime('%Y-%m-%d %H:%M')}
Author: {author}

SUBJECTIVE:
Patient is post-operative day {days_post_op} from {procedure['display']}.
Was discharged on POD 5 but readmitted 2 days ago with fever, chills, and abdominal pain.
Pain localized to LLQ near anastomotic site.

OBJECTIVE:
Vitals: T 38.8, HR 105, BP 118/72, RR 18
General: Febrile, uncomfortable
Abdomen:
  - Midline incision healing well, no superficial infection
  - Deep LLQ tenderness
  - Guarding in lower abdomen
  - JP drain placed yesterday - purulent output

LABS/IMAGING:
- WBC 18.5
- Procalcitonin 8.5 ng/mL
- CT Abdomen ({(base_time - timedelta(days=2)).strftime('%Y-%m-%d')}):
  5.2 cm PELVIC ABSCESS adjacent to colorectal anastomosis
  Compatible with anastomotic leak with contained abscess
- Drain fluid culture ({culture_date.strftime('%Y-%m-%d')}): POSITIVE for {organism['display']}

ASSESSMENT/PLAN:
1. ORGAN/SPACE SURGICAL SITE INFECTION - Intra-abdominal Abscess (IAB)
   - Procedure: {procedure['display']} ({procedure['nhsn_category']})
   - Post-op day {days_post_op}
   - MEETS NHSN CRITERIA FOR ORGAN/SPACE SSI:
     * Abscess identified on CT imaging (5.2 cm pelvic abscess)
     * Organ/space involved: PELVIS (NHSN code: IAB)
     * Positive culture from drain in organ/space ({organism['display']})
   - Likely anastomotic leak with contained infection
   - Incision itself is NOT infected (no superficial or deep SSI)

2. Management:
   - Percutaneous drainage (JP drain in place)
   - IV antibiotics (ertapenem)
   - NPO, TPN
   - Discuss need for surgical exploration if no improvement
"""

    return {
        "scenario_type": "organ_space_ssi",
        "description": f"Organ/Space SSI: pelvic abscess with positive drain culture after {procedure['display']}",
        "expected_classification": "Organ/Space SSI",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": organism["display"],
        "procedure": procedure["display"],
        "days_post_op": days_post_op,
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_procedure(patient_id, procedure, procedure_date),
            create_imaging_report(patient_id, base_time - timedelta(days=2), "CT",
                                  "5.2 cm pelvic abscess adjacent to anastomosis", "Pelvis"),
            create_wound_culture(patient_id, culture_date, organism, "drain"),
            create_clinical_note(patient_id, base_time, note_content, author=author),
        ]
    }


def create_not_ssi_scenario(base_time: datetime) -> dict:
    """Not SSI: wound healing well, normal post-op course."""
    patient_id = f"demo-ssi-neg-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()

    procedure = PROCEDURES["total_knee"]
    procedure_date = base_time - timedelta(days=14)
    admission_date = procedure_date - timedelta(days=1)
    days_post_op = 14

    location = {"code": "SURG", "display": "Surgery Floor"}
    author = random.choice(DEMO_AUTHORS)

    note_content = f"""
PROGRESS NOTE - {base_time.strftime('%Y-%m-%d %H:%M')}
Author: {author}

SUBJECTIVE:
Patient is post-operative day {days_post_op} from {procedure['display']}.
Doing well with physical therapy. Mild expected post-operative discomfort.
No fevers, chills, or wound drainage. Incision looks good per patient.

OBJECTIVE:
Vitals: T 36.8, HR 78, BP 132/78, RR 14
General: Alert, comfortable, ambulatory with walker
Right Knee:
  - Surgical incision clean, dry, intact
  - No erythema (expected mild bruising only)
  - No drainage
  - No warmth or fluctuance
  - Staples in place, well-approximated
  - Range of motion improving with PT

LABS:
- WBC 7.2 (normal)
- ESR and CRP trending down (expected post-op)

ASSESSMENT/PLAN:
1. POST-OPERATIVE DAY {days_post_op} - {procedure['display'].upper()}
   - Procedure: {procedure['display']} ({procedure['nhsn_category']})
   - Implant: Yes (prosthetic knee)
   - Surveillance window: 90 days (due to implant)
   - NO SIGNS OF SURGICAL SITE INFECTION:
     * Wound healing well, no drainage
     * No erythema, warmth, or tenderness
     * Afebrile, normal WBC
     * Patient progressing as expected

2. Continue current management:
   - Continue DVT prophylaxis
   - Physical therapy as tolerated
   - Staple removal in 1 week
   - Follow-up in clinic in 2 weeks
"""

    return {
        "scenario_type": "not_ssi",
        "description": f"Not SSI: wound healing normally after {procedure['display']}",
        "expected_classification": "Not SSI",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": "N/A",
        "procedure": procedure["display"],
        "days_post_op": days_post_op,
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_procedure(patient_id, procedure, procedure_date),
            create_clinical_note(patient_id, base_time, note_content, author=author),
        ]
    }


SCENARIO_FUNCTIONS = {
    "superficial": create_superficial_ssi_scenario,
    "deep": create_deep_ssi_scenario,
    "organ-space": create_organ_space_ssi_scenario,
    "not-ssi": create_not_ssi_scenario,
}


def upload_resource(resource: dict, fhir_url: str) -> bool:
    """Upload a resource to FHIR server."""
    resource_type = resource["resourceType"]
    resource_id = resource["id"]
    url = f"{fhir_url}/{resource_type}/{resource_id}"

    try:
        response = requests.put(url, json=resource, headers={"Content-Type": "application/fhir+json"}, timeout=10)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"  Error uploading {resource_type}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Generate demo SSI candidates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--scenario", "-s", choices=list(SCENARIO_FUNCTIONS.keys()),
                        help="Specific scenario to create")
    parser.add_argument("--all", "-a", action="store_true",
                        help="Create all scenario types")
    parser.add_argument("--fhir-url", default=DEFAULT_FHIR_URL,
                        help=f"FHIR server URL (default: {DEFAULT_FHIR_URL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be created without uploading")

    args = parser.parse_args()

    base_time = datetime.now(timezone.utc)
    scenarios_to_create = []

    if args.all:
        scenarios_to_create = list(SCENARIO_FUNCTIONS.keys())
    elif args.scenario:
        scenarios_to_create = [args.scenario]
    else:
        # Default: create one SSI + one Not SSI (random SSI type)
        scenarios_to_create = [random.choice(["superficial", "deep", "organ-space"]), "not-ssi"]

    # Check FHIR server
    if not args.dry_run:
        try:
            requests.get(f"{args.fhir_url}/metadata", timeout=5).raise_for_status()
            print(f"Connected to FHIR server at {args.fhir_url}\n")
        except requests.RequestException as e:
            print(f"Error: Cannot connect to FHIR server: {e}")
            return 1

    print("=" * 70)
    print("SSI DEMO SCENARIOS")
    print("=" * 70)

    for scenario_name in scenarios_to_create:
        scenario_fn = SCENARIO_FUNCTIONS[scenario_name]
        scenario = scenario_fn(base_time)

        print(f"\n{'-' * 70}")
        print(f"Scenario: {scenario['scenario_type'].upper()}")
        print(f"{'-' * 70}")
        print(f"  Patient MRN:    {scenario['mrn']}")
        print(f"  Procedure:      {scenario['procedure']}")
        print(f"  Days Post-Op:   {scenario['days_post_op']}")
        print(f"  Organism:       {scenario['organism']}")
        print(f"  Description:    {scenario['description']}")
        print(f"  Expected:       {scenario['expected_classification']}")

        if args.dry_run:
            print(f"\n  [DRY RUN] Would create {len(scenario['resources'])} FHIR resources")
        else:
            print(f"\n  Uploading {len(scenario['resources'])} resources...")
            success = True
            for resource in scenario["resources"]:
                if not upload_resource(resource, args.fhir_url):
                    success = False
                    break
            if success:
                print(f"  Created successfully")
            else:
                print(f"  Failed")

    print(f"\n{'=' * 70}")
    if not args.dry_run:
        print("\nDemo data created. To see the candidates:")
        print("  1. Run the NHSN monitor: cd nhsn-reporting && python -m src.runner --full")
        print("  2. View in dashboard: https://aegis-asp.com/hai-detection/")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
