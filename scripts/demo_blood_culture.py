#!/usr/bin/env python3
"""Generate a demo patient with a positive blood culture for alert testing.

Creates a new patient in the FHIR server with:
- A positive blood culture (organism of your choice)
- Optionally on an antibiotic (may or may not cover the organism)

This triggers bacteremia alerts when the monitor runs.

Usage:
    # MRSA without vancomycin (should trigger alert)
    python demo_blood_culture.py --organism mrsa

    # MRSA with vancomycin (should NOT trigger alert)
    python demo_blood_culture.py --organism mrsa --antibiotic vancomycin

    # Pseudomonas with cefazolin (should trigger alert - inadequate coverage)
    python demo_blood_culture.py --organism pseudomonas --antibiotic cefazolin

    # E. coli with meropenem (appropriate)
    python demo_blood_culture.py --organism ecoli --antibiotic meropenem

    # Interactive mode
    python demo_blood_culture.py --interactive
"""

import argparse
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

# Organism definitions with SNOMED codes and susceptibility patterns
# Susceptibilities: S = Susceptible, I = Intermediate, R = Resistant
ORGANISMS = {
    "mrsa": {
        "code": "115329001",
        "display": "Methicillin resistant Staphylococcus aureus",
        "condition_code": "266096002",
        "condition_display": "MRSA infection",
        "appropriate_abx": ["vancomycin", "daptomycin", "linezolid"],
        "susceptibilities": {
            "oxacillin": {"result": "R", "mic": ">4"},
            "vancomycin": {"result": "S", "mic": "1"},
            "daptomycin": {"result": "S", "mic": "0.5"},
            "linezolid": {"result": "S", "mic": "2"},
            "cefazolin": {"result": "R", "mic": ">8"},
            "clindamycin": {"result": "R", "mic": ">8"},
            "trimethoprim-sulfamethoxazole": {"result": "S", "mic": "<=0.5"},
        },
    },
    "mssa": {
        "code": "3092008",
        "display": "Staphylococcus aureus",
        "condition_code": "3092008",
        "condition_display": "Staphylococcus aureus infection",
        "appropriate_abx": ["cefazolin", "nafcillin", "vancomycin"],
        "susceptibilities": {
            "oxacillin": {"result": "S", "mic": "0.5"},
            "vancomycin": {"result": "S", "mic": "1"},
            "cefazolin": {"result": "S", "mic": "2"},
            "clindamycin": {"result": "S", "mic": "0.25"},
            "trimethoprim-sulfamethoxazole": {"result": "S", "mic": "<=0.5"},
        },
    },
    "ecoli": {
        "code": "112283007",
        "display": "Escherichia coli",
        "condition_code": "112283007",
        "condition_display": "Escherichia coli infection",
        "appropriate_abx": ["ceftriaxone", "meropenem", "piperacillin-tazobactam"],
        "susceptibilities": {
            "ampicillin": {"result": "R", "mic": ">16"},
            "ceftriaxone": {"result": "S", "mic": "<=1"},
            "cefepime": {"result": "S", "mic": "<=1"},
            "piperacillin-tazobactam": {"result": "S", "mic": "<=4"},
            "meropenem": {"result": "S", "mic": "<=0.25"},
            "ciprofloxacin": {"result": "R", "mic": ">2"},
            "gentamicin": {"result": "S", "mic": "<=1"},
        },
    },
    "pseudomonas": {
        "code": "52499004",
        "display": "Pseudomonas aeruginosa",
        "condition_code": "52499004",
        "condition_display": "Pseudomonas aeruginosa infection",
        "appropriate_abx": ["meropenem", "cefepime", "piperacillin-tazobactam"],
        "susceptibilities": {
            "piperacillin-tazobactam": {"result": "S", "mic": "<=16"},
            "cefepime": {"result": "S", "mic": "<=2"},
            "meropenem": {"result": "S", "mic": "<=1"},
            "ciprofloxacin": {"result": "I", "mic": "1"},
            "gentamicin": {"result": "S", "mic": "<=1"},
            "tobramycin": {"result": "S", "mic": "<=1"},
            "ceftazidime": {"result": "S", "mic": "<=4"},
        },
    },
    "klebsiella": {
        "code": "56415008",
        "display": "Klebsiella pneumoniae",
        "condition_code": "56415008",
        "condition_display": "Klebsiella infection",
        "appropriate_abx": ["ceftriaxone", "meropenem", "piperacillin-tazobactam"],
        "susceptibilities": {
            "ampicillin": {"result": "R", "mic": ">16"},
            "ceftriaxone": {"result": "S", "mic": "<=1"},
            "cefepime": {"result": "S", "mic": "<=1"},
            "piperacillin-tazobactam": {"result": "S", "mic": "<=4"},
            "meropenem": {"result": "S", "mic": "<=0.25"},
            "ciprofloxacin": {"result": "S", "mic": "<=0.25"},
            "gentamicin": {"result": "S", "mic": "<=1"},
        },
    },
    "enterococcus": {
        "code": "78065002",
        "display": "Enterococcus faecalis",
        "condition_code": "78065002",
        "condition_display": "Enterococcus infection",
        "appropriate_abx": ["vancomycin", "ampicillin"],
        "susceptibilities": {
            "ampicillin": {"result": "S", "mic": "<=2"},
            "vancomycin": {"result": "S", "mic": "<=1"},
            "linezolid": {"result": "S", "mic": "2"},
            "daptomycin": {"result": "S", "mic": "1"},
        },
    },
    "vre": {
        "code": "113727004",
        "display": "Vancomycin resistant Enterococcus",
        "condition_code": "413563001",
        "condition_display": "VRE infection",
        "appropriate_abx": ["daptomycin", "linezolid"],
        "susceptibilities": {
            "ampicillin": {"result": "R", "mic": ">16"},
            "vancomycin": {"result": "R", "mic": ">256"},
            "linezolid": {"result": "S", "mic": "2"},
            "daptomycin": {"result": "S", "mic": "2"},
        },
    },
    "candida": {
        "code": "78048006",
        "display": "Candida albicans",
        "condition_code": "78048006",
        "condition_display": "Candida infection",
        "appropriate_abx": ["micafungin", "fluconazole", "caspofungin"],
        "susceptibilities": {
            "fluconazole": {"result": "S", "mic": "<=2"},
            "micafungin": {"result": "S", "mic": "<=0.06"},
            "caspofungin": {"result": "S", "mic": "<=0.25"},
            "amphotericin-b": {"result": "S", "mic": "<=1"},
        },
    },
}

# Antibiotic definitions with RxNorm codes
ANTIBIOTICS = {
    "vancomycin": {"code": "11124", "display": "Vancomycin"},
    "meropenem": {"code": "29561", "display": "Meropenem"},
    "cefazolin": {"code": "309090", "display": "Cefazolin"},
    "ceftriaxone": {"code": "309092", "display": "Ceftriaxone"},
    "cefepime": {"code": "309091", "display": "Cefepime"},
    "piperacillin-tazobactam": {"code": "312619", "display": "Piperacillin-tazobactam"},
    "ampicillin": {"code": "733", "display": "Ampicillin"},
    "daptomycin": {"code": "262090", "display": "Daptomycin"},
    "linezolid": {"code": "190376", "display": "Linezolid"},
    "micafungin": {"code": "121243", "display": "Micafungin"},
    "fluconazole": {"code": "4450", "display": "Fluconazole"},
    "nafcillin": {"code": "7233", "display": "Nafcillin"},
    "caspofungin": {"code": "202553", "display": "Caspofungin"},
}

# LOINC codes for antibiotic susceptibility tests
SUSCEPTIBILITY_LOINC = {
    "oxacillin": {"code": "6932-8", "display": "Oxacillin [Susceptibility]"},
    "vancomycin": {"code": "20475-8", "display": "Vancomycin [Susceptibility]"},
    "daptomycin": {"code": "35811-4", "display": "Daptomycin [Susceptibility]"},
    "linezolid": {"code": "29258-1", "display": "Linezolid [Susceptibility]"},
    "cefazolin": {"code": "18864-9", "display": "Cefazolin [Susceptibility]"},
    "clindamycin": {"code": "18878-9", "display": "Clindamycin [Susceptibility]"},
    "trimethoprim-sulfamethoxazole": {"code": "18998-5", "display": "Trimethoprim+Sulfamethoxazole [Susceptibility]"},
    "ampicillin": {"code": "18862-3", "display": "Ampicillin [Susceptibility]"},
    "ceftriaxone": {"code": "18886-2", "display": "Ceftriaxone [Susceptibility]"},
    "cefepime": {"code": "18879-7", "display": "Cefepime [Susceptibility]"},
    "piperacillin-tazobactam": {"code": "18945-6", "display": "Piperacillin+Tazobactam [Susceptibility]"},
    "meropenem": {"code": "18932-4", "display": "Meropenem [Susceptibility]"},
    "ciprofloxacin": {"code": "18906-8", "display": "Ciprofloxacin [Susceptibility]"},
    "gentamicin": {"code": "18928-2", "display": "Gentamicin [Susceptibility]"},
    "tobramycin": {"code": "18996-9", "display": "Tobramycin [Susceptibility]"},
    "ceftazidime": {"code": "18888-8", "display": "Ceftazidime [Susceptibility]"},
    "fluconazole": {"code": "18924-1", "display": "Fluconazole [Susceptibility]"},
    "micafungin": {"code": "57095-2", "display": "Micafungin [Susceptibility]"},
    "caspofungin": {"code": "35783-5", "display": "Caspofungin [Susceptibility]"},
    "amphotericin-b": {"code": "18863-1", "display": "Amphotericin B [Susceptibility]"},
}

# Interpretation codes for S/I/R
SUSCEPTIBILITY_INTERPRETATION = {
    "S": {"code": "S", "display": "Susceptible", "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"},
    "I": {"code": "I", "display": "Intermediate", "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"},
    "R": {"code": "R", "display": "Resistant", "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"},
}

# Names for demo patients
FIRST_NAMES = ["Demo", "Test", "Alert", "Sample", "Trial"]
LAST_NAMES = ["Patient", "Case", "Subject", "Example", "Scenario"]


def generate_mrn() -> str:
    """Generate a demo MRN."""
    return f"DEMO{random.randint(1000, 9999)}"


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
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code": "MR",
                        }
                    ]
                },
                "value": mrn,
            }
        ],
        "name": [{"family": last_name, "given": [first_name]}],
        "gender": random.choice(["male", "female"]),
        "birthDate": (datetime.now() - timedelta(days=random.randint(365, 6570))).strftime(
            "%Y-%m-%d"
        ),
    }


def create_encounter(patient_id: str) -> dict:
    """Create an inpatient Encounter FHIR resource."""
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
        "period": {"start": datetime.now(timezone.utc).isoformat()},
    }


def create_blood_culture_report(
    patient_id: str, organism_key: str, hours_ago: float = 2
) -> dict:
    """Create a positive blood culture DiagnosticReport FHIR resource.

    This matches Epic's FHIR structure where blood cultures are returned
    as DiagnosticReport resources with organism info in conclusion/conclusionCode.
    """
    organism = ORGANISMS[organism_key]
    collected_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    resulted_time = datetime.now(timezone.utc) - timedelta(hours=max(0, hours_ago - 1))

    return {
        "resourceType": "DiagnosticReport",
        "id": str(uuid.uuid4()),
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                        "code": "LAB",
                        "display": "Laboratory",
                    },
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                        "code": "MB",
                        "display": "Microbiology",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "600-7",
                    "display": "Bacteria identified in Blood by Culture",
                }
            ],
            "text": "Blood Culture",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collected_time.isoformat(),
        "issued": resulted_time.isoformat(),
        "conclusion": organism["display"],
        "conclusionCode": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": organism["code"],
                        "display": organism["display"],
                    }
                ],
                "text": organism["display"],
            }
        ],
    }


def create_susceptibility_observations(
    patient_id: str,
    diagnostic_report_id: str,
    organism_key: str,
    hours_ago: float = 1,
) -> list[dict]:
    """Create susceptibility Observation FHIR resources for an organism.

    Returns a list of Observation resources, one for each antibiotic tested.
    These link back to the DiagnosticReport via derivedFrom.
    """
    organism = ORGANISMS[organism_key]
    susceptibilities = organism.get("susceptibilities", {})

    if not susceptibilities:
        return []

    resulted_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    observations = []

    for antibiotic_name, result_data in susceptibilities.items():
        # Get LOINC code for this antibiotic test
        loinc_info = SUSCEPTIBILITY_LOINC.get(antibiotic_name)
        if not loinc_info:
            continue

        # Get interpretation (S/I/R)
        interpretation = SUSCEPTIBILITY_INTERPRETATION.get(result_data["result"])
        if not interpretation:
            continue

        obs_id = str(uuid.uuid4())

        observation = {
            "resourceType": "Observation",
            "id": obs_id,
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "laboratory",
                            "display": "Laboratory",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": loinc_info["code"],
                        "display": loinc_info["display"],
                    }
                ],
                "text": f"{antibiotic_name.replace('-', ' ').title()} Susceptibility",
            },
            "subject": {"reference": f"Patient/{patient_id}"},
            "effectiveDateTime": resulted_time.isoformat(),
            # Note: In Epic, these would be linked via DiagnosticReport.result
            # The diagnostic_report_id is stored in a note/extension for reference
            "note": [{"text": f"Culture: {diagnostic_report_id}"}],
            "valueCodeableConcept": {
                "coding": [
                    {
                        "system": interpretation["system"],
                        "code": interpretation["code"],
                        "display": interpretation["display"],
                    }
                ],
                "text": interpretation["display"],
            },
            "interpretation": [
                {
                    "coding": [
                        {
                            "system": interpretation["system"],
                            "code": interpretation["code"],
                            "display": interpretation["display"],
                        }
                    ]
                }
            ],
        }

        # Add MIC value as a component if available
        if result_data.get("mic"):
            observation["component"] = [
                {
                    "code": {
                        "coding": [
                            {
                                "system": "http://loinc.org",
                                "code": "35659-7",
                                "display": "Minimum inhibitory concentration (MIC)",
                            }
                        ],
                        "text": "MIC",
                    },
                    "valueString": f"{result_data['mic']} mcg/mL",
                }
            ]

        observations.append(observation)

    return observations


def create_medication_request(
    patient_id: str, antibiotic_key: str, hours_ago: float = 4
) -> dict:
    """Create a MedicationRequest FHIR resource."""
    antibiotic = ANTIBIOTICS[antibiotic_key]
    start_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)

    return {
        "resourceType": "MedicationRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": antibiotic["code"],
                    "display": antibiotic["display"],
                }
            ],
            "text": antibiotic["display"],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": start_time.isoformat(),
    }


def upload_to_fhir(resource: dict, fhir_url: str) -> bool:
    """Upload a resource to the FHIR server."""
    resource_type = resource["resourceType"]
    resource_id = resource["id"]
    url = f"{fhir_url}/{resource_type}/{resource_id}"

    try:
        response = requests.put(
            url,
            json=resource,
            headers={
                "Content-Type": "application/fhir+json",
                "Accept": "application/fhir+json",
            },
        )
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"  Error uploading {resource_type}: {e}")
        return False


def interactive_mode() -> tuple[str, str | None]:
    """Run interactive prompts to select organism and antibiotic."""
    print("\n=== Blood Culture Demo - Interactive Mode ===\n")

    print("Available organisms:")
    for i, (key, org) in enumerate(ORGANISMS.items(), 1):
        print(f"  {i}. {key}: {org['display']}")

    while True:
        try:
            choice = input("\nSelect organism (number or name): ").strip().lower()
            if choice.isdigit():
                idx = int(choice) - 1
                organism_key = list(ORGANISMS.keys())[idx]
            elif choice in ORGANISMS:
                organism_key = choice
            else:
                print("Invalid choice. Try again.")
                continue
            break
        except (ValueError, IndexError):
            print("Invalid choice. Try again.")

    organism = ORGANISMS[organism_key]
    print(f"\nSelected: {organism['display']}")
    print(f"Appropriate antibiotics: {', '.join(organism['appropriate_abx'])}")

    print("\nAvailable antibiotics:")
    print("  0. None (no antibiotic)")
    for i, (key, abx) in enumerate(ANTIBIOTICS.items(), 1):
        coverage = "✓" if key in organism["appropriate_abx"] else "✗"
        print(f"  {i}. {key}: {abx['display']} [{coverage}]")

    while True:
        try:
            choice = input("\nSelect antibiotic (number, name, or 0 for none): ").strip().lower()
            if choice == "0" or choice == "none":
                antibiotic_key = None
            elif choice.isdigit():
                idx = int(choice) - 1
                antibiotic_key = list(ANTIBIOTICS.keys())[idx]
            elif choice in ANTIBIOTICS:
                antibiotic_key = choice
            else:
                print("Invalid choice. Try again.")
                continue
            break
        except (ValueError, IndexError):
            print("Invalid choice. Try again.")

    return organism_key, antibiotic_key


def main():
    parser = argparse.ArgumentParser(
        description="Generate a demo patient with positive blood culture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--organism", "-o",
        choices=list(ORGANISMS.keys()),
        help="Organism for blood culture",
    )
    parser.add_argument(
        "--antibiotic", "-a",
        choices=list(ANTIBIOTICS.keys()),
        help="Current antibiotic (optional)",
    )
    parser.add_argument(
        "--fhir-url",
        default="http://localhost:8081/fhir",
        help="FHIR server base URL",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode",
    )
    parser.add_argument(
        "--culture-hours",
        type=float,
        default=2,
        help="Hours ago blood culture was collected (default: 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resources without uploading",
    )

    args = parser.parse_args()

    # Interactive or command-line mode
    if args.interactive:
        organism_key, antibiotic_key = interactive_mode()
    elif args.organism:
        organism_key = args.organism
        antibiotic_key = args.antibiotic
    else:
        parser.error("Either --organism or --interactive is required")

    organism = ORGANISMS[organism_key]

    # Generate resources
    mrn = generate_mrn()
    patient = create_patient(mrn)
    patient_id = patient["id"]
    patient_name = f"{patient['name'][0]['given'][0]} {patient['name'][0]['family']}"

    encounter = create_encounter(patient_id)
    diagnostic_report = create_blood_culture_report(patient_id, organism_key, args.culture_hours)
    diagnostic_report_id = diagnostic_report["id"]

    # Create susceptibility observations linked to the diagnostic report
    susceptibility_observations = create_susceptibility_observations(
        patient_id, diagnostic_report_id, organism_key, args.culture_hours - 1
    )

    medication = None
    if antibiotic_key:
        medication = create_medication_request(patient_id, antibiotic_key)

    # Determine if alert should trigger
    will_alert = antibiotic_key is None or antibiotic_key not in organism["appropriate_abx"]

    print(f"\n{'='*60}")
    print("DEMO BLOOD CULTURE SCENARIO")
    print(f"{'='*60}")
    print(f"Patient:     {patient_name} (MRN: {mrn})")
    print(f"Organism:    {organism['display']}")
    print(f"Suscept.:    {len(susceptibility_observations)} antibiotic tests")
    if antibiotic_key:
        coverage = "adequate" if antibiotic_key in organism["appropriate_abx"] else "INADEQUATE"
        print(f"Antibiotic:  {ANTIBIOTICS[antibiotic_key]['display']} ({coverage})")
    else:
        print("Antibiotic:  None")
    print(f"Alert:       {'YES - should trigger alert' if will_alert else 'No - adequate coverage'}")
    print(f"{'='*60}\n")

    if args.dry_run:
        print("Dry run - resources not uploaded\n")
        print("Patient:", json.dumps(patient, indent=2)[:500], "...\n")
        print("DiagnosticReport:", json.dumps(diagnostic_report, indent=2)[:500], "...\n")
        if susceptibility_observations:
            print(f"Susceptibilities: {len(susceptibility_observations)} observations\n")
        if medication:
            print("Medication:", json.dumps(medication, indent=2)[:500], "...\n")
        return 0

    # Upload to FHIR server
    print(f"Uploading to {args.fhir_url}...")

    try:
        requests.get(f"{args.fhir_url}/metadata").raise_for_status()
    except Exception as e:
        print(f"Error: Cannot connect to FHIR server: {e}")
        return 1

    resources = [patient, encounter, diagnostic_report]
    # Add susceptibility observations
    resources.extend(susceptibility_observations)
    if medication:
        resources.append(medication)

    for resource in resources:
        rtype = resource["resourceType"]
        if upload_to_fhir(resource, args.fhir_url):
            if rtype == "Observation":
                # Don't print each susceptibility observation
                pass
            else:
                print(f"  ✓ {rtype} created")
        else:
            print(f"  ✗ {rtype} failed")
            return 1

    if susceptibility_observations:
        print(f"  ✓ {len(susceptibility_observations)} Susceptibility Observations created")

    print(f"\n✓ Demo patient created successfully!")
    print(f"  Patient ID: {patient_id}")
    print(f"  Culture ID: {diagnostic_report_id}")
    print(f"  MRN: {mrn}")
    if will_alert:
        print(f"\n  Run the bacteremia monitor to see the alert trigger.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
