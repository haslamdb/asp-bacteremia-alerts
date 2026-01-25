#!/usr/bin/env python3
"""Generate demo patients with drug-bug mismatches for alert testing.

Creates patients with:
- Positive cultures WITH susceptibility testing
- Antibiotics that the organism is RESISTANT to (triggers mismatch alert)

This triggers drug-bug mismatch alerts when the monitor runs.

Usage:
    # VRE on vancomycin (RESISTANT - should trigger alert)
    python demo_drug_bug.py --scenario vre-vanco

    # MRSA on cefazolin (RESISTANT - should trigger alert)
    python demo_drug_bug.py --scenario mrsa-cefazolin

    # E. coli on ampicillin (RESISTANT - should trigger alert)
    python demo_drug_bug.py --scenario ecoli-amp

    # Pseudomonas on meropenem (SUSCEPTIBLE - no alert)
    python demo_drug_bug.py --scenario pseudomonas-mero

    # Interactive mode
    python demo_drug_bug.py --interactive

    # Run all mismatch scenarios
    python demo_drug_bug.py --all-mismatches
"""

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

# ============================================================================
# ORGANISMS with susceptibility patterns
# ============================================================================
ORGANISMS = {
    "mrsa": {
        "code": "115329001",
        "display": "Methicillin resistant Staphylococcus aureus",
        "susceptibilities": {
            "oxacillin": {"result": "R", "mic": ">4"},
            "cefazolin": {"result": "R", "mic": ">8"},
            "vancomycin": {"result": "S", "mic": "1"},
            "daptomycin": {"result": "S", "mic": "0.5"},
            "linezolid": {"result": "S", "mic": "2"},
            "clindamycin": {"result": "R", "mic": ">8"},
            "trimethoprim-sulfamethoxazole": {"result": "S", "mic": "<=0.5"},
        },
    },
    "vre": {
        "code": "113727004",
        "display": "Vancomycin resistant Enterococcus faecium",
        "susceptibilities": {
            "ampicillin": {"result": "R", "mic": ">16"},
            "vancomycin": {"result": "R", "mic": ">256"},
            "linezolid": {"result": "S", "mic": "2"},
            "daptomycin": {"result": "S", "mic": "2"},
            "gentamicin-synergy": {"result": "R", "mic": ">500"},
        },
    },
    "ecoli-esbl": {
        "code": "112283007",
        "display": "Escherichia coli (ESBL-producing)",
        "susceptibilities": {
            "ampicillin": {"result": "R", "mic": ">32"},
            "ampicillin-sulbactam": {"result": "R", "mic": ">32"},
            "ceftriaxone": {"result": "R", "mic": ">64"},
            "cefepime": {"result": "R", "mic": ">16"},
            "piperacillin-tazobactam": {"result": "I", "mic": "64"},
            "meropenem": {"result": "S", "mic": "<=0.25"},
            "ertapenem": {"result": "S", "mic": "<=0.5"},
            "ciprofloxacin": {"result": "R", "mic": ">4"},
            "gentamicin": {"result": "S", "mic": "<=1"},
        },
    },
    "pseudomonas": {
        "code": "52499004",
        "display": "Pseudomonas aeruginosa",
        "susceptibilities": {
            "piperacillin-tazobactam": {"result": "S", "mic": "<=16"},
            "cefepime": {"result": "S", "mic": "<=2"},
            "ceftazidime": {"result": "S", "mic": "<=4"},
            "meropenem": {"result": "S", "mic": "<=1"},
            "ciprofloxacin": {"result": "I", "mic": "1"},
            "gentamicin": {"result": "S", "mic": "<=1"},
            "tobramycin": {"result": "S", "mic": "<=1"},
            "aztreonam": {"result": "S", "mic": "<=4"},
        },
    },
    "pseudomonas-mdr": {
        "code": "52499004",
        "display": "Pseudomonas aeruginosa (MDR)",
        "susceptibilities": {
            "piperacillin-tazobactam": {"result": "R", "mic": ">128"},
            "cefepime": {"result": "R", "mic": ">32"},
            "ceftazidime": {"result": "R", "mic": ">32"},
            "meropenem": {"result": "R", "mic": ">8"},
            "ciprofloxacin": {"result": "R", "mic": ">4"},
            "gentamicin": {"result": "R", "mic": ">8"},
            "tobramycin": {"result": "I", "mic": "4"},
            "aztreonam": {"result": "R", "mic": ">16"},
            "ceftolozane-tazobactam": {"result": "S", "mic": "2"},
        },
    },
    "klebsiella-cre": {
        "code": "56415008",
        "display": "Klebsiella pneumoniae (CRE)",
        "susceptibilities": {
            "ampicillin": {"result": "R", "mic": ">32"},
            "ceftriaxone": {"result": "R", "mic": ">64"},
            "cefepime": {"result": "R", "mic": ">32"},
            "piperacillin-tazobactam": {"result": "R", "mic": ">128"},
            "meropenem": {"result": "R", "mic": ">8"},
            "ertapenem": {"result": "R", "mic": ">8"},
            "ciprofloxacin": {"result": "R", "mic": ">4"},
            "gentamicin": {"result": "R", "mic": ">8"},
            "tigecycline": {"result": "S", "mic": "1"},
            "colistin": {"result": "S", "mic": "<=0.5"},
            "ceftazidime-avibactam": {"result": "S", "mic": "<=1"},
        },
    },
}

# ============================================================================
# ANTIBIOTICS with RxNorm codes
# ============================================================================
ANTIBIOTICS = {
    "vancomycin": {"code": "11124", "display": "Vancomycin"},
    "meropenem": {"code": "29561", "display": "Meropenem"},
    "cefazolin": {"code": "309090", "display": "Cefazolin"},
    "ceftriaxone": {"code": "309092", "display": "Ceftriaxone"},
    "cefepime": {"code": "309091", "display": "Cefepime"},
    "piperacillin-tazobactam": {"code": "312619", "display": "Piperacillin-tazobactam"},
    "ampicillin": {"code": "733", "display": "Ampicillin"},
    "ampicillin-sulbactam": {"code": "57962", "display": "Ampicillin-sulbactam"},
    "daptomycin": {"code": "262090", "display": "Daptomycin"},
    "linezolid": {"code": "190376", "display": "Linezolid"},
    "ciprofloxacin": {"code": "2551", "display": "Ciprofloxacin"},
    "gentamicin": {"code": "4413", "display": "Gentamicin"},
}

# ============================================================================
# LOINC codes for susceptibility tests
# ============================================================================
SUSCEPTIBILITY_LOINC = {
    "oxacillin": {"code": "6932-8", "display": "Oxacillin [Susceptibility]"},
    "vancomycin": {"code": "20475-8", "display": "Vancomycin [Susceptibility]"},
    "daptomycin": {"code": "35811-4", "display": "Daptomycin [Susceptibility]"},
    "linezolid": {"code": "29258-1", "display": "Linezolid [Susceptibility]"},
    "cefazolin": {"code": "18864-9", "display": "Cefazolin [Susceptibility]"},
    "clindamycin": {"code": "18878-9", "display": "Clindamycin [Susceptibility]"},
    "trimethoprim-sulfamethoxazole": {"code": "18998-5", "display": "TMP-SMX [Susceptibility]"},
    "ampicillin": {"code": "18862-3", "display": "Ampicillin [Susceptibility]"},
    "ampicillin-sulbactam": {"code": "18865-6", "display": "Ampicillin-sulbactam [Susceptibility]"},
    "ceftriaxone": {"code": "18886-2", "display": "Ceftriaxone [Susceptibility]"},
    "cefepime": {"code": "18879-7", "display": "Cefepime [Susceptibility]"},
    "ceftazidime": {"code": "18888-8", "display": "Ceftazidime [Susceptibility]"},
    "piperacillin-tazobactam": {"code": "18945-6", "display": "Piperacillin+Tazobactam [Susceptibility]"},
    "meropenem": {"code": "18932-4", "display": "Meropenem [Susceptibility]"},
    "ertapenem": {"code": "35802-3", "display": "Ertapenem [Susceptibility]"},
    "ciprofloxacin": {"code": "18906-8", "display": "Ciprofloxacin [Susceptibility]"},
    "gentamicin": {"code": "18928-2", "display": "Gentamicin [Susceptibility]"},
    "gentamicin-synergy": {"code": "18929-0", "display": "Gentamicin High Level [Susceptibility]"},
    "tobramycin": {"code": "18996-9", "display": "Tobramycin [Susceptibility]"},
    "aztreonam": {"code": "18868-0", "display": "Aztreonam [Susceptibility]"},
    "tigecycline": {"code": "42357-5", "display": "Tigecycline [Susceptibility]"},
    "colistin": {"code": "18908-4", "display": "Colistin [Susceptibility]"},
    "ceftazidime-avibactam": {"code": "73602-5", "display": "Ceftazidime-avibactam [Susceptibility]"},
    "ceftolozane-tazobactam": {"code": "73603-3", "display": "Ceftolozane-tazobactam [Susceptibility]"},
}

# Interpretation codes
INTERPRETATION = {
    "S": {"code": "S", "display": "Susceptible", "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"},
    "I": {"code": "I", "display": "Intermediate", "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"},
    "R": {"code": "R", "display": "Resistant", "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"},
}

# ============================================================================
# PREDEFINED SCENARIOS for testing drug-bug mismatches
# ============================================================================
SCENARIOS = {
    # Mismatch scenarios (should trigger alerts)
    "vre-vanco": {
        "name": "VRE on Vancomycin",
        "description": "VRE patient on vancomycin - RESISTANT - Critical mismatch",
        "organism": "vre",
        "antibiotic": "vancomycin",
        "specimen_type": "Blood",
        "expected_alert": True,
        "alert_severity": "critical",
    },
    "mrsa-cefazolin": {
        "name": "MRSA on Cefazolin",
        "description": "MRSA patient on cefazolin - RESISTANT - Critical mismatch",
        "organism": "mrsa",
        "antibiotic": "cefazolin",
        "specimen_type": "Blood",
        "expected_alert": True,
        "alert_severity": "critical",
    },
    "ecoli-amp": {
        "name": "ESBL E. coli on Ampicillin",
        "description": "ESBL E. coli UTI on ampicillin - RESISTANT - Critical mismatch",
        "organism": "ecoli-esbl",
        "antibiotic": "ampicillin",
        "specimen_type": "Urine",
        "expected_alert": True,
        "alert_severity": "critical",
    },
    "ecoli-ceftriaxone": {
        "name": "ESBL E. coli on Ceftriaxone",
        "description": "ESBL E. coli bacteremia on ceftriaxone - RESISTANT - Critical mismatch",
        "organism": "ecoli-esbl",
        "antibiotic": "ceftriaxone",
        "specimen_type": "Blood",
        "expected_alert": True,
        "alert_severity": "critical",
    },
    "pseudomonas-cipro": {
        "name": "Pseudomonas on Ciprofloxacin",
        "description": "Pseudomonas pneumonia on ciprofloxacin - INTERMEDIATE - Warning mismatch",
        "organism": "pseudomonas",
        "antibiotic": "ciprofloxacin",
        "specimen_type": "Respiratory",
        "expected_alert": True,
        "alert_severity": "warning",
    },
    "mdr-pseudo-mero": {
        "name": "MDR Pseudomonas on Meropenem",
        "description": "MDR Pseudomonas wound infection on meropenem - RESISTANT - Critical mismatch",
        "organism": "pseudomonas-mdr",
        "antibiotic": "meropenem",
        "specimen_type": "Wound",
        "expected_alert": True,
        "alert_severity": "critical",
    },
    "cre-mero": {
        "name": "CRE Klebsiella on Meropenem",
        "description": "CRE Klebsiella bacteremia on meropenem - RESISTANT - Critical mismatch",
        "organism": "klebsiella-cre",
        "antibiotic": "meropenem",
        "specimen_type": "Blood",
        "expected_alert": True,
        "alert_severity": "critical",
    },
    # Non-mismatch scenarios (should NOT trigger alerts)
    "mrsa-vanco": {
        "name": "MRSA on Vancomycin",
        "description": "MRSA patient on vancomycin - SUSCEPTIBLE - No alert",
        "organism": "mrsa",
        "antibiotic": "vancomycin",
        "specimen_type": "Blood",
        "expected_alert": False,
    },
    "pseudomonas-mero": {
        "name": "Pseudomonas on Meropenem",
        "description": "Pseudomonas on meropenem - SUSCEPTIBLE - No alert",
        "organism": "pseudomonas",
        "antibiotic": "meropenem",
        "specimen_type": "Respiratory",
        "expected_alert": False,
    },
    "vre-dapto": {
        "name": "VRE on Daptomycin",
        "description": "VRE on daptomycin - SUSCEPTIBLE - No alert",
        "organism": "vre",
        "antibiotic": "daptomycin",
        "specimen_type": "Blood",
        "expected_alert": False,
    },
    "ecoli-mero": {
        "name": "ESBL E. coli on Meropenem",
        "description": "ESBL E. coli on meropenem - SUSCEPTIBLE - No alert",
        "organism": "ecoli-esbl",
        "antibiotic": "meropenem",
        "specimen_type": "Urine",
        "expected_alert": False,
    },
}

# Patient name components
FIRST_NAMES = ["Demo", "Test", "DrugBug", "Mismatch", "Alert"]
LAST_NAMES = ["Patient", "Case", "Scenario", "Example", "Subject"]


def generate_mrn() -> str:
    """Generate a demo MRN."""
    return f"DBM{random.randint(10000, 99999)}"


def create_patient(mrn: str) -> dict:
    """Create a Patient FHIR resource."""
    patient_id = str(uuid.uuid4())
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)

    return {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [
            {
                "type": {
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]
                },
                "value": mrn,
            }
        ],
        "name": [{"family": last_name, "given": [first_name]}],
        "gender": random.choice(["male", "female"]),
        "birthDate": (datetime.now() - timedelta(days=random.randint(7300, 29200))).strftime("%Y-%m-%d"),
    }


def create_encounter(patient_id: str) -> dict:
    """Create an inpatient Encounter."""
    return {
        "resourceType": "Encounter",
        "id": str(uuid.uuid4()),
        "status": "in-progress",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "IMP",
            "display": "inpatient encounter",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": (datetime.now(timezone.utc) - timedelta(days=random.randint(1, 5))).isoformat()},
    }


def create_culture_report(patient_id: str, organism_key: str, hours_ago: float = 4, specimen_type: str = "Blood") -> dict:
    """Create a microbiology DiagnosticReport with organism identification."""
    organism = ORGANISMS[organism_key]
    collected_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    resulted_time = datetime.now(timezone.utc) - timedelta(hours=max(0.5, hours_ago - 2))

    # Map specimen type to LOINC codes
    specimen_loinc = {
        "Blood": {"code": "600-7", "display": "Bacteria identified in Blood by Culture"},
        "Urine": {"code": "630-4", "display": "Bacteria identified in Urine by Culture"},
        "Wound": {"code": "6462-6", "display": "Bacteria identified in Wound by Culture"},
        "Respiratory": {"code": "624-7", "display": "Bacteria identified in Sputum by Culture"},
    }
    loinc = specimen_loinc.get(specimen_type, specimen_loinc["Blood"])

    return {
        "resourceType": "DiagnosticReport",
        "id": str(uuid.uuid4()),
        "status": "final",
        "category": [
            {
                "coding": [
                    {"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "LAB"},
                    {"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "MB", "display": "Microbiology"},
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": loinc["code"], "display": loinc["display"]}],
            "text": f"{specimen_type} Culture",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collected_time.isoformat(),
        "issued": resulted_time.isoformat(),
        "specimen": [{"display": specimen_type}],
        "conclusion": organism["display"],
        "conclusionCode": [
            {
                "coding": [{"system": "http://snomed.info/sct", "code": organism["code"], "display": organism["display"]}],
                "text": organism["display"],
            }
        ],
        # result array will be populated with observation references
        "result": [],
    }


def create_susceptibility_observation(
    patient_id: str,
    report_id: str,
    organism_display: str,
    antibiotic_name: str,
    result_data: dict,
    resulted_time: datetime,
) -> dict:
    """Create a single susceptibility Observation."""
    loinc = SUSCEPTIBILITY_LOINC.get(antibiotic_name)
    if not loinc:
        # Use a generic LOINC code if specific one not found
        loinc = {"code": "18769-0", "display": f"{antibiotic_name} [Susceptibility]"}

    interp = INTERPRETATION[result_data["result"]]
    obs_id = str(uuid.uuid4())

    observation = {
        "resourceType": "Observation",
        "id": obs_id,
        "status": "final",
        "category": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "laboratory"}]}
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": loinc["code"], "display": loinc["display"]}],
            "text": f"{antibiotic_name.replace('-', ' ').title()} Susceptibility",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": resulted_time.isoformat(),
        # Link to culture via specimen note (DiagnosticReport.result will also link back)
        "note": [{"text": f"Culture: DiagnosticReport/{report_id}"}],
        "specimen": {"display": f"Blood culture - {organism_display}"},
        "valueCodeableConcept": {
            "coding": [{"system": interp["system"], "code": interp["code"], "display": interp["display"]}],
            "text": interp["display"],
        },
        "interpretation": [
            {"coding": [{"system": interp["system"], "code": interp["code"], "display": interp["display"]}]}
        ],
    }

    # Add MIC value
    if result_data.get("mic"):
        mic_text = result_data["mic"]
        observation["component"] = [
            {
                "code": {
                    "coding": [{"system": "http://loinc.org", "code": "35659-7", "display": "MIC"}],
                    "text": "MIC",
                },
                "valueString": f"{mic_text} mcg/mL",
            }
        ]

    return observation


def create_all_susceptibility_observations(
    patient_id: str,
    report: dict,
    organism_key: str,
    hours_ago: float,
) -> list[dict]:
    """Create all susceptibility observations for an organism."""
    organism = ORGANISMS[organism_key]
    resulted_time = datetime.now(timezone.utc) - timedelta(hours=max(0.5, hours_ago - 2))
    observations = []

    for abx_name, result_data in organism["susceptibilities"].items():
        obs = create_susceptibility_observation(
            patient_id,
            report["id"],
            organism["display"],
            abx_name,
            result_data,
            resulted_time,
        )
        observations.append(obs)
        # Add reference to report
        report["result"].append({"reference": f"Observation/{obs['id']}"})

    return observations


def create_medication_request(patient_id: str, antibiotic_key: str, hours_ago: float = 8) -> dict:
    """Create a MedicationRequest for an antibiotic."""
    antibiotic = ANTIBIOTICS[antibiotic_key]
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

    return {
        "resourceType": "MedicationRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {"system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": antibiotic["code"], "display": antibiotic["display"]}
            ],
            "text": antibiotic["display"],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": start_time.isoformat(),
        "dosageInstruction": [
            {
                "route": {
                    "coding": [{"system": "http://snomed.info/sct", "code": "47625008", "display": "Intravenous"}]
                }
            }
        ],
    }


def upload_resource(resource: dict, fhir_url: str) -> bool:
    """Upload a FHIR resource."""
    url = f"{fhir_url}/{resource['resourceType']}/{resource['id']}"
    try:
        response = requests.put(url, json=resource, headers={"Content-Type": "application/fhir+json"})
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"  Error uploading {resource['resourceType']}: {e}")
        return False


def run_scenario(scenario_key: str, fhir_url: str, dry_run: bool = False) -> dict:
    """Run a single scenario and return results."""
    scenario = SCENARIOS[scenario_key]
    organism = ORGANISMS[scenario["organism"]]
    antibiotic = ANTIBIOTICS.get(scenario["antibiotic"])

    # Check what the susceptibility result is for this antibiotic
    susc_result = None
    for susc_name, susc_data in organism["susceptibilities"].items():
        if scenario["antibiotic"] in susc_name or susc_name in scenario["antibiotic"]:
            susc_result = susc_data["result"]
            break

    # Create resources
    mrn = generate_mrn()
    patient = create_patient(mrn)
    patient_id = patient["id"]
    patient_name = f"{patient['name'][0]['given'][0]} {patient['name'][0]['family']}"

    encounter = create_encounter(patient_id)
    specimen_type = scenario.get("specimen_type", "Blood")
    culture = create_culture_report(patient_id, scenario["organism"], specimen_type=specimen_type)
    # Create observations first (they reference the culture via derivedFrom)
    susceptibilities = create_all_susceptibility_observations(patient_id, culture, scenario["organism"], 4)
    medication = create_medication_request(patient_id, scenario["antibiotic"])

    # Store the result references separately - we'll update the culture after uploading observations
    culture_result_refs = culture.pop("result", [])

    result = {
        "scenario": scenario_key,
        "name": scenario["name"],
        "patient_name": patient_name,
        "mrn": mrn,
        "patient_id": patient_id,
        "culture_id": culture["id"],
        "organism": organism["display"],
        "antibiotic": antibiotic["display"],
        "susceptibility": susc_result,
        "expected_alert": scenario["expected_alert"],
        "success": False,
    }

    print(f"\n{'─'*60}")
    print(f"Scenario: {scenario['name']}")
    print(f"{'─'*60}")
    print(f"  Patient:      {patient_name} (MRN: {mrn})")
    print(f"  Organism:     {organism['display']}")
    print(f"  Antibiotic:   {antibiotic['display']}")
    print(f"  Suscept.:     {susc_result or 'N/A'}")
    print(f"  Expected:     {'ALERT' if scenario['expected_alert'] else 'No alert'}")

    if dry_run:
        print("  [DRY RUN - not uploaded]")
        result["success"] = True
        return result

    # Upload resources in correct order:
    # 1. Patient, Encounter first
    # 2. Culture (without result refs)
    # 3. Susceptibility observations (reference culture via derivedFrom)
    # 4. Update culture with result references
    # 5. Medication

    print(f"\n  Uploading to {fhir_url}...")

    # Upload patient and encounter
    for resource in [patient, encounter]:
        if upload_resource(resource, fhir_url):
            print(f"    ✓ {resource['resourceType']}")
        else:
            print(f"    ✗ {resource['resourceType']} FAILED")
            return result

    # Upload culture without result references
    if upload_resource(culture, fhir_url):
        print(f"    ✓ DiagnosticReport")
    else:
        print(f"    ✗ DiagnosticReport FAILED")
        return result

    # Upload susceptibility observations
    for obs in susceptibilities:
        if not upload_resource(obs, fhir_url):
            print(f"    ✗ Observation FAILED")
            return result
    print(f"    ✓ {len(susceptibilities)} Susceptibility Observations")

    # Update culture with result references
    if culture_result_refs:
        culture["result"] = culture_result_refs
        if upload_resource(culture, fhir_url):
            print(f"    ✓ DiagnosticReport updated with result refs")
        else:
            print(f"    ⚠ DiagnosticReport result refs update failed (non-fatal)")

    # Upload medication
    if upload_resource(medication, fhir_url):
        print(f"    ✓ MedicationRequest")
    else:
        print(f"    ✗ MedicationRequest FAILED")
        return result

    result["success"] = True
    return result


def interactive_mode(fhir_url: str, dry_run: bool) -> list[dict]:
    """Run interactive scenario selection."""
    print("\n=== Drug-Bug Mismatch Demo - Interactive Mode ===\n")

    print("Available scenarios:\n")
    print("MISMATCH scenarios (should trigger alerts):")
    for key, scenario in SCENARIOS.items():
        if scenario["expected_alert"]:
            print(f"  {key:25} - {scenario['description']}")

    print("\nNO-MISMATCH scenarios (should NOT trigger alerts):")
    for key, scenario in SCENARIOS.items():
        if not scenario["expected_alert"]:
            print(f"  {key:25} - {scenario['description']}")

    while True:
        choice = input("\nEnter scenario name (or 'q' to quit): ").strip().lower()
        if choice == "q":
            return []
        if choice in SCENARIOS:
            return [run_scenario(choice, fhir_url, dry_run)]
        print("Invalid scenario. Try again.")


def main():
    parser = argparse.ArgumentParser(
        description="Generate drug-bug mismatch demo scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--scenario", "-s", choices=list(SCENARIOS.keys()), help="Specific scenario to run")
    parser.add_argument("--all-mismatches", action="store_true", help="Run all mismatch scenarios")
    parser.add_argument("--all", action="store_true", help="Run ALL scenarios (including non-mismatches)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--fhir-url", default="http://localhost:8081/fhir", help="FHIR server URL")
    parser.add_argument("--dry-run", action="store_true", help="Print without uploading")
    parser.add_argument("--list", "-l", action="store_true", help="List available scenarios")

    args = parser.parse_args()

    if args.list:
        print("\nAvailable scenarios:\n")
        print(f"{'Scenario':<25} {'Organism':<30} {'Antibiotic':<20} {'Result':<8} {'Alert?'}")
        print("─" * 100)
        for key, scenario in SCENARIOS.items():
            org = ORGANISMS[scenario["organism"]]
            # Find susceptibility result
            susc = "N/A"
            for s_name, s_data in org["susceptibilities"].items():
                if scenario["antibiotic"] in s_name or s_name in scenario["antibiotic"]:
                    susc = s_data["result"]
                    break
            alert = "YES" if scenario["expected_alert"] else "No"
            print(f"{key:<25} {org['display'][:28]:<30} {scenario['antibiotic']:<20} {susc:<8} {alert}")
        return 0

    # Check FHIR server connectivity
    if not args.dry_run:
        try:
            requests.get(f"{args.fhir_url}/metadata", timeout=5).raise_for_status()
        except Exception as e:
            print(f"Error: Cannot connect to FHIR server at {args.fhir_url}: {e}")
            return 1

    results = []

    if args.interactive:
        results = interactive_mode(args.fhir_url, args.dry_run)
    elif args.scenario:
        results = [run_scenario(args.scenario, args.fhir_url, args.dry_run)]
    elif args.all_mismatches:
        print("\n" + "=" * 60)
        print("RUNNING ALL MISMATCH SCENARIOS")
        print("=" * 60)
        for key, scenario in SCENARIOS.items():
            if scenario["expected_alert"]:
                results.append(run_scenario(key, args.fhir_url, args.dry_run))
    elif args.all:
        print("\n" + "=" * 60)
        print("RUNNING ALL SCENARIOS")
        print("=" * 60)
        for key in SCENARIOS:
            results.append(run_scenario(key, args.fhir_url, args.dry_run))
    else:
        parser.error("Specify --scenario, --all-mismatches, --all, or --interactive")

    # Summary
    if results:
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        success_count = sum(1 for r in results if r["success"])
        alert_count = sum(1 for r in results if r["success"] and r["expected_alert"])

        print(f"\nCreated {success_count}/{len(results)} scenarios successfully")
        print(f"Expected alerts: {alert_count}")

        if not args.dry_run:
            print("\nTo test, run the drug-bug mismatch monitor:")
            print("  cd drug-bug-mismatch && python -m src.runner --lookback 24")

    return 0


if __name__ == "__main__":
    sys.exit(main())
