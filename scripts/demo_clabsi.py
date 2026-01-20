#!/usr/bin/env python3
"""Generate demo CLABSI candidates for dashboard demonstration.

Creates paired scenarios:
1. A clear CLABSI case (should be classified as CLABSI)
2. A Not CLABSI case (MBI-LCBI, Secondary, or other reason)

Each case includes realistic clinical notes with evidence to help
determine the correct classification.

Usage:
    # Create one CLABSI + one Not CLABSI pair
    python demo_clabsi.py

    # Create specific scenario types
    python demo_clabsi.py --scenario clabsi
    python demo_clabsi.py --scenario mbi
    python demo_clabsi.py --scenario secondary-uti
    python demo_clabsi.py --scenario secondary-pneumonia

    # Create all scenario types
    python demo_clabsi.py --all

    # Dry run (don't upload to FHIR)
    python demo_clabsi.py --dry-run
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
    {"code": "T5A", "display": "PICU"},
    {"code": "T5B", "display": "CICU"},
    {"code": "T4", "display": "NICU"},
    {"code": "G5S", "display": "Oncology"},
    {"code": "G6N", "display": "BMT"},
    {"code": "A6N", "display": "Hospital Medicine"},
]

# Central line types
CENTRAL_LINE_TYPES = [
    {"code": "52124006", "display": "Central venous catheter", "short": "CVC"},
    {"code": "303728004", "display": "Peripherally inserted central catheter", "short": "PICC"},
    {"code": "706689003", "display": "Tunneled central venous catheter", "short": "Tunneled CVC"},
]

# Body sites
LINE_SITES = [
    {"code": "20699002", "display": "Right subclavian vein"},
    {"code": "48345005", "display": "Left subclavian vein"},
    {"code": "83419000", "display": "Right internal jugular vein"},
    {"code": "50094009", "display": "Right basilic vein"},
]

# Organisms
ORGANISMS = {
    "staph_aureus": {"code": "3092008", "display": "Staphylococcus aureus"},
    "ecoli": {"code": "112283007", "display": "Escherichia coli"},
    "klebsiella": {"code": "56415008", "display": "Klebsiella pneumoniae"},
    "pseudomonas": {"code": "52499004", "display": "Pseudomonas aeruginosa"},
    "enterococcus": {"code": "76327009", "display": "Enterococcus faecalis"},
    "candida": {"code": "4298009", "display": "Candida albicans"},
    "cons": {"code": "116197008", "display": "Coagulase-negative staphylococci"},
}

# Patient names
FIRST_NAMES = ["Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
               "Isabella", "William", "Mia", "James", "Charlotte", "Benjamin"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
              "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Thomas"]


def generate_mrn():
    return f"DEMO{random.randint(10000, 99999)}"


def create_patient(patient_id: str, mrn: str) -> dict:
    """Create a FHIR Patient resource."""
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    age_days = random.randint(365, 6570)  # 1-18 years
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


def create_device(device_id: str, line_type: dict) -> dict:
    """Create a FHIR Device resource."""
    return {
        "resourceType": "Device",
        "id": device_id,
        "type": {"coding": [{"system": "http://snomed.info/sct", "code": line_type["code"], "display": line_type["display"]}]},
        "status": "active"
    }


def create_device_use_statement(patient_id: str, device_id: str, line_type: dict, site: dict,
                                 insertion_date: datetime, removal_date: datetime = None) -> dict:
    """Create a FHIR DeviceUseStatement."""
    resource = {
        "resourceType": "DeviceUseStatement",
        "id": f"dus-{uuid.uuid4().hex[:8]}",
        "status": "completed" if removal_date else "active",
        "subject": {"reference": f"Patient/{patient_id}"},
        "device": {
            "reference": {"reference": f"Device/{device_id}"},
            "concept": {"coding": [{"system": "http://snomed.info/sct", "code": line_type["code"], "display": line_type["display"]}]}
        },
        "timingPeriod": {"start": insertion_date.isoformat()},
        "bodySite": {"coding": [{"system": "http://snomed.info/sct", "code": site["code"], "display": site["display"]}]}
    }
    if removal_date:
        resource["timingPeriod"]["end"] = removal_date.isoformat()
    return resource


def create_blood_culture(patient_id: str, collection_date: datetime, organism: dict) -> dict:
    """Create a FHIR DiagnosticReport for blood culture."""
    return {
        "resourceType": "DiagnosticReport",
        "id": f"bc-{uuid.uuid4().hex[:8]}",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "MB", "display": "Microbiology"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "600-7", "display": "Blood culture"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collection_date.isoformat(),
        "issued": (collection_date + timedelta(hours=48)).isoformat(),
        "conclusion": f"Positive for {organism['display']}",
        "conclusionCode": [{"coding": [{"system": "http://snomed.info/sct", "code": organism["code"], "display": organism["display"]}]}]
    }


def create_urine_culture(patient_id: str, collection_date: datetime, organism: dict) -> dict:
    """Create a FHIR DiagnosticReport for urine culture."""
    return {
        "resourceType": "DiagnosticReport",
        "id": f"uc-{uuid.uuid4().hex[:8]}",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "MB", "display": "Microbiology"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "630-4", "display": "Urine culture"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collection_date.isoformat(),
        "issued": (collection_date + timedelta(hours=24)).isoformat(),
        "conclusion": f"Positive for {organism['display']} >100,000 CFU/mL",
        "conclusionCode": [{"coding": [{"system": "http://snomed.info/sct", "code": organism["code"], "display": organism["display"]}]}]
    }


def create_respiratory_culture(patient_id: str, collection_date: datetime, organism: dict) -> dict:
    """Create a FHIR DiagnosticReport for respiratory culture."""
    return {
        "resourceType": "DiagnosticReport",
        "id": f"rc-{uuid.uuid4().hex[:8]}",
        "status": "final",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "MB", "display": "Microbiology"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "6460-0", "display": "Respiratory culture"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collection_date.isoformat(),
        "issued": (collection_date + timedelta(hours=48)).isoformat(),
        "conclusion": f"Positive for {organism['display']}",
        "conclusionCode": [{"coding": [{"system": "http://snomed.info/sct", "code": organism["code"], "display": organism["display"]}]}]
    }


def create_clinical_note(patient_id: str, note_date: datetime, content: str) -> dict:
    """Create a FHIR DocumentReference for clinical note."""
    return {
        "resourceType": "DocumentReference",
        "id": f"note-{uuid.uuid4().hex[:8]}",
        "status": "current",
        "type": {"coding": [{"system": "http://loinc.org", "code": "11506-3", "display": "Progress note"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": note_date.isoformat(),
        "content": [{"attachment": {"contentType": "text/plain", "data": base64.b64encode(content.encode()).decode()}}]
    }


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================

def create_clabsi_scenario(base_time: datetime) -> dict:
    """Clear CLABSI: pathogenic organism, line >2 days, no alternative source."""
    patient_id = f"demo-clabsi-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()
    device_id = f"dev-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=7)
    line_insertion = base_time - timedelta(days=5)
    culture_date = base_time - timedelta(hours=6)
    line_days = (culture_date - line_insertion).days

    location = random.choice([l for l in LOCATIONS if l["code"] in ["T5A", "T5B", "A6N"]])
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = ORGANISMS["staph_aureus"]

    note_content = f"""
PROGRESS NOTE - {culture_date.strftime('%Y-%m-%d %H:%M')}

SUBJECTIVE:
Patient is a {random.randint(5, 15)} year old admitted for management of acute illness.
New fever to 39.2C overnight. No respiratory symptoms, no urinary symptoms.
Central line has been in place for {line_days} days.

OBJECTIVE:
Vitals: T 39.2, HR 120, BP 95/60, RR 22, SpO2 98% RA
General: Ill-appearing, flushed
HEENT: MMM, no oral lesions
Lungs: Clear to auscultation bilaterally, no wheezes or crackles
Abdomen: Soft, non-tender, no distension
Skin: No rashes. Central line site with mild erythema and tenderness at insertion site.
       No purulent drainage but surrounding warmth noted.

LABS:
- Blood culture ({culture_date.strftime('%Y-%m-%d')}): POSITIVE for {organism['display']}
- WBC 18.5, Bands 15%
- Procalcitonin 8.2 ng/mL
- Urinalysis: Negative for infection
- Chest X-ray: No infiltrates or consolidation

ASSESSMENT/PLAN:
1. {organism['display']} bacteremia - LIKELY CATHETER-RELATED BLOODSTREAM INFECTION
   - Central line in place for {line_days} days with signs of local infection at insertion site
   - No alternative source identified:
     * Urinalysis negative
     * Chest X-ray clear, no respiratory symptoms
     * No abdominal source
     * No skin/soft tissue infection besides line site
   - Recommend line removal and culture of catheter tip
   - Continue vancomycin pending sensitivities

2. Central venous catheter - REMOVE TODAY
   - Evidence of local infection at site
   - New line placement at different site after blood cultures clear
"""

    return {
        "scenario_type": "clabsi",
        "description": f"Clear CLABSI: {organism['display']}, {line_type['short']} in place {line_days} days, line site infection, no alternative source",
        "expected_classification": "CLABSI",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": organism["display"],
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture(patient_id, culture_date, organism),
            create_clinical_note(patient_id, culture_date + timedelta(hours=4), note_content),
        ]
    }


def create_mbi_lcbi_scenario(base_time: datetime) -> dict:
    """MBI-LCBI: BMT patient with neutropenia, mucositis, and gut organism."""
    patient_id = f"demo-mbi-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()
    device_id = f"dev-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=21)
    line_insertion = base_time - timedelta(days=20)
    culture_date = base_time - timedelta(hours=6)
    line_days = (culture_date - line_insertion).days

    location = random.choice([l for l in LOCATIONS if l["code"] in ["G5S", "G6N"]])
    line_type = CENTRAL_LINE_TYPES[2]  # Tunneled CVC for BMT
    site = LINE_SITES[0]
    organism = ORGANISMS["ecoli"]  # Gut organism

    note_content = f"""
PROGRESS NOTE - {culture_date.strftime('%Y-%m-%d %H:%M')}

SUBJECTIVE:
Patient is day +12 post allogeneic bone marrow transplant for ALL.
Developed fever to 38.9C this morning. Reports severe mouth pain and difficulty swallowing.
Has had watery diarrhea x 3 days (non-bloody).

OBJECTIVE:
Vitals: T 38.9, HR 115, BP 100/65, RR 20, SpO2 99% RA
General: Cachectic, ill-appearing
HEENT: Severe oral mucositis - Grade 3 with confluent ulcerations of buccal mucosa,
       tongue, and oropharynx. Unable to tolerate PO intake.
Lungs: Clear bilaterally
Abdomen: Soft, mild diffuse tenderness, hyperactive bowel sounds
Central line site: Tunneled catheter site clean, well-healed, no erythema or drainage

LABS:
- Blood culture ({culture_date.strftime('%Y-%m-%d')}): POSITIVE for {organism['display']}
- WBC 0.1 (ANC 0 - profound neutropenia, day 12 post-BMT)
- Platelets 12
- Procalcitonin 4.5 ng/mL

ASSESSMENT/PLAN:
1. {organism['display']} bacteremia in setting of:
   - Profound neutropenia (ANC 0)
   - Severe Grade 3 mucositis with mucosal breakdown
   - GI symptoms (diarrhea)

   THIS IS LIKELY MBI-LCBI (Mucosal Barrier Injury Laboratory-Confirmed Bloodstream Infection)
   - Gut organism ({organism['display']}) in neutropenic BMT patient with severe mucositis
   - Organism likely translocated across damaged GI mucosa
   - Central line site appears clean with no signs of infection
   - Meets NHSN criteria for MBI-LCBI: neutropenia + mucositis + gut organism

2. Continue broad spectrum antibiotics (meropenem + vancomycin)
3. G-CSF as per BMT protocol
4. Supportive care for mucositis
5. DO NOT remove central line - not the source of infection
"""

    return {
        "scenario_type": "mbi_lcbi",
        "description": f"MBI-LCBI: {organism['display']} in BMT patient with ANC 0 and Grade 3 mucositis",
        "expected_classification": "Not CLABSI - MBI-LCBI",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": organism["display"],
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_blood_culture(patient_id, culture_date, organism),
            create_clinical_note(patient_id, culture_date + timedelta(hours=4), note_content),
        ]
    }


def create_secondary_uti_scenario(base_time: datetime) -> dict:
    """Secondary BSI from UTI - same organism in blood and urine."""
    patient_id = f"demo-uti-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()
    device_id = f"dev-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=10)
    line_insertion = base_time - timedelta(days=8)
    culture_date = base_time - timedelta(hours=6)
    urine_culture_date = culture_date - timedelta(hours=12)  # Urine collected before blood
    line_days = (culture_date - line_insertion).days

    location = random.choice(LOCATIONS)
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = ORGANISMS["ecoli"]

    note_content = f"""
PROGRESS NOTE - {culture_date.strftime('%Y-%m-%d %H:%M')}

SUBJECTIVE:
Patient admitted for IV antibiotics. Has had indwelling Foley catheter for 1 week.
Developed fever, chills, and flank pain yesterday. Reports dysuria and cloudy urine.
Central line placed {line_days} days ago for IV access.

OBJECTIVE:
Vitals: T 39.5, HR 130, BP 90/55, RR 24, SpO2 97% RA
General: Ill-appearing, rigors observed
Abdomen: Soft, suprapubic tenderness
CVA: Right CVA tenderness on percussion
GU: Foley catheter in place, cloudy urine with sediment
Central line site: Clean, dry, no erythema or tenderness

LABS:
- Urine culture ({urine_culture_date.strftime('%Y-%m-%d')}): POSITIVE for {organism['display']} >100,000 CFU/mL
- Blood culture ({culture_date.strftime('%Y-%m-%d')}): POSITIVE for {organism['display']}
- WBC 22.3 with left shift
- Urinalysis: Large leukocyte esterase, positive nitrites, >50 WBC/hpf, bacteria present
- CT Abdomen: Right pyelonephritis with perinephric stranding

ASSESSMENT/PLAN:
1. {organism['display']} bacteremia SECONDARY TO URINARY TRACT INFECTION
   - Same organism isolated from both urine and blood cultures
   - Clinical presentation consistent with pyelonephritis (flank pain, CVA tenderness)
   - CT confirms right pyelonephritis
   - Urine culture positive BEFORE blood culture - suggests ascending infection
   - THIS IS NOT A CLABSI - blood infection is secondary to urinary source

2. Complicated UTI / Pyelonephritis with bacteremia
   - Continue ceftriaxone, transition to oral after afebrile 48 hours
   - Remove Foley catheter if possible

3. Central line - MAY KEEP IN PLACE
   - No evidence of line infection
   - Line site clean
   - Blood infection clearly secondary to UTI, not line-related
"""

    return {
        "scenario_type": "secondary_uti",
        "description": f"Secondary BSI from UTI: {organism['display']} in blood AND urine, pyelonephritis on CT",
        "expected_classification": "Not CLABSI - Secondary to UTI",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": organism["display"],
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_urine_culture(patient_id, urine_culture_date, organism),
            create_blood_culture(patient_id, culture_date, organism),
            create_clinical_note(patient_id, culture_date + timedelta(hours=4), note_content),
        ]
    }


def create_secondary_pneumonia_scenario(base_time: datetime) -> dict:
    """Secondary BSI from pneumonia - same organism in blood and respiratory."""
    patient_id = f"demo-pna-{uuid.uuid4().hex[:8]}"
    mrn = generate_mrn()
    device_id = f"dev-{uuid.uuid4().hex[:8]}"

    admission_date = base_time - timedelta(days=8)
    line_insertion = base_time - timedelta(days=6)
    culture_date = base_time - timedelta(hours=6)
    resp_culture_date = culture_date - timedelta(hours=6)
    line_days = (culture_date - line_insertion).days

    location = {"code": "T5A", "display": "PICU"}
    line_type = random.choice(CENTRAL_LINE_TYPES)
    site = random.choice(LINE_SITES)
    organism = ORGANISMS["pseudomonas"]

    note_content = f"""
PROGRESS NOTE - {culture_date.strftime('%Y-%m-%d %H:%M')}

SUBJECTIVE:
Patient intubated {admission_date.strftime('%Y-%m-%d')} for respiratory failure.
Has been on mechanical ventilation for 8 days. Increasing ventilator requirements
over past 48 hours with new infiltrate on chest X-ray.
Central line placed {line_days} days ago for vasoactive medications.

OBJECTIVE:
Vitals: T 39.1, HR 125, BP 85/50 (on norepinephrine), RR 28 (ventilated), SpO2 92% on FiO2 70%
General: Intubated, sedated
Lungs: Coarse breath sounds bilaterally, rhonchi in right lung fields,
       increased secretions - thick, yellow-green purulent sputum
Central line site: Clean, no erythema

LABS:
- Respiratory culture ({resp_culture_date.strftime('%Y-%m-%d')}): HEAVY GROWTH {organism['display']}
- Blood culture ({culture_date.strftime('%Y-%m-%d')}): POSITIVE for {organism['display']}
- WBC 19.8, Bands 20%
- Procalcitonin 12.5 ng/mL
- Chest X-ray: New right lower lobe consolidation with air bronchograms, consistent with pneumonia
- CPIS score: 8 (high probability of VAP)

ASSESSMENT/PLAN:
1. {organism['display']} bacteremia SECONDARY TO VENTILATOR-ASSOCIATED PNEUMONIA
   - Same organism ({organism['display']}) isolated from respiratory AND blood cultures
   - Clinical presentation consistent with VAP:
     * New infiltrate on CXR
     * Purulent secretions
     * Fever, leukocytosis
     * Increased ventilator requirements
   - Blood culture likely represents hematogenous spread from pulmonary source
   - THIS IS NOT A CLABSI - the pneumonia is the primary infection

2. Ventilator-associated pneumonia with secondary bacteremia
   - Antipseudomonal coverage: Cefepime + Tobramycin
   - Continue mechanical ventilation with lung-protective settings

3. Central line - NO NEED TO REMOVE
   - Not the source of infection
   - Blood infection is secondary to pneumonia
   - Line site appears clean
"""

    return {
        "scenario_type": "secondary_pneumonia",
        "description": f"Secondary BSI from VAP: {organism['display']} in blood AND respiratory, new infiltrate",
        "expected_classification": "Not CLABSI - Secondary to Pneumonia",
        "patient_id": patient_id,
        "mrn": mrn,
        "organism": organism["display"],
        "resources": [
            create_patient(patient_id, mrn),
            create_encounter(patient_id, location, admission_date),
            create_device(device_id, line_type),
            create_device_use_statement(patient_id, device_id, line_type, site, line_insertion),
            create_respiratory_culture(patient_id, resp_culture_date, organism),
            create_blood_culture(patient_id, culture_date, organism),
            create_clinical_note(patient_id, culture_date + timedelta(hours=4), note_content),
        ]
    }


SCENARIO_FUNCTIONS = {
    "clabsi": create_clabsi_scenario,
    "mbi": create_mbi_lcbi_scenario,
    "secondary-uti": create_secondary_uti_scenario,
    "secondary-pneumonia": create_secondary_pneumonia_scenario,
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
        description="Generate demo CLABSI candidates",
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
        # Default: create one CLABSI + one Not CLABSI (random)
        scenarios_to_create = ["clabsi", random.choice(["mbi", "secondary-uti", "secondary-pneumonia"])]

    # Check FHIR server
    if not args.dry_run:
        try:
            requests.get(f"{args.fhir_url}/metadata", timeout=5).raise_for_status()
            print(f"Connected to FHIR server at {args.fhir_url}\n")
        except requests.RequestException as e:
            print(f"Error: Cannot connect to FHIR server: {e}")
            return 1

    print("=" * 70)
    print("CLABSI DEMO SCENARIOS")
    print("=" * 70)

    for scenario_name in scenarios_to_create:
        scenario_fn = SCENARIO_FUNCTIONS[scenario_name]
        scenario = scenario_fn(base_time)

        print(f"\n{'─' * 70}")
        print(f"Scenario: {scenario['scenario_type'].upper()}")
        print(f"{'─' * 70}")
        print(f"  Patient MRN:    {scenario['mrn']}")
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
                print(f"  ✓ Created successfully")
            else:
                print(f"  ✗ Failed")

    print(f"\n{'=' * 70}")
    if not args.dry_run:
        print("\nDemo data created. To see the candidates:")
        print("  1. Run the NHSN monitor: cd nhsn-reporting && python -m src.runner --once")
        print("  2. View in dashboard: https://alerts.aegis-asp.com:8444/hai-detection/")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
