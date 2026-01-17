#!/usr/bin/env python3
"""Generate pediatric-specific test data for ASP Alerts modules.

Creates synthetic FHIR resources for testing:
- Bacteremia alerts: Positive blood cultures with/without antibiotics
- Antimicrobial usage alerts: Broad-spectrum antibiotics at various durations

Uses CCHMC-specific units and departments for realistic scenarios.
"""

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests

# CCHMC-specific locations
CCHMC_UNITS = {
    "A6N": {"beds": 42, "department": "Hospital Medicine"},
    "A6S": {"beds": 36, "department": "Hospital Medicine"},
    "G5S": {"beds": 24, "department": "Oncology"},
    "G6N": {"beds": 24, "department": "Bone Marrow Transplant"},
    "T5A": {"beds": 20, "department": "PICU"},
    "T5B": {"beds": 16, "department": "CICU"},
    "T4": {"beds": 48, "department": "NICU"},
    "A5N": {"beds": 28, "department": "Pulmonary"},
    "A5S": {"beds": 28, "department": "Neurology"},
}

# Common pediatric names
FIRST_NAMES = [
    "Olivia", "Liam", "Emma", "Noah", "Ava", "Oliver", "Sophia", "Elijah",
    "Isabella", "James", "Mia", "William", "Charlotte", "Benjamin", "Amelia",
    "Lucas", "Harper", "Henry", "Evelyn", "Alexander", "Luna", "Mason",
    "Gianna", "Ethan", "Chloe", "Daniel", "Penelope", "Jacob", "Layla", "Michael",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Thompson",
]

# Monitored medications (RxNorm codes)
MEDICATIONS = {
    "29561": {"name": "Meropenem", "dose": "40 mg/kg", "route": "IV"},
    "11124": {"name": "Vancomycin", "dose": "15 mg/kg", "route": "IV"},
}

# Common bacteria for blood cultures
ORGANISMS = [
    ("Staphylococcus aureus", "3092008"),
    ("Escherichia coli", "112283007"),
    ("Klebsiella pneumoniae", "56415008"),
    ("Pseudomonas aeruginosa", "52499004"),
    ("Streptococcus pneumoniae", "9861002"),
    ("Enterococcus faecalis", "78065002"),
]


def generate_patient(mrn_prefix: str = "CCHMC", mrn_number: int = 1) -> dict:
    """Generate a synthetic pediatric patient."""
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    gender = random.choice(["male", "female"])

    # Pediatric age range (0-18 years)
    age_days = random.randint(0, 18 * 365)
    birth_date = datetime.now() - timedelta(days=age_days)

    unit = random.choice(list(CCHMC_UNITS.keys()))
    unit_info = CCHMC_UNITS[unit]
    bed = random.randint(1, unit_info["beds"])

    patient_id = str(uuid.uuid4())

    return {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [
            {
                "type": {
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "MR"}]
                },
                "value": f"{mrn_prefix}{mrn_number:03d}",
            }
        ],
        "name": [{"family": last_name, "given": [first_name]}],
        "gender": gender,
        "birthDate": birth_date.strftime("%Y-%m-%d"),
        "extension": [
            {"url": "http://example.org/fhir/location", "valueString": f"{unit}-{bed}"},
            {"url": "http://example.org/fhir/department", "valueString": unit_info["department"]},
        ],
    }


def generate_medication_request(
    patient_id: str,
    rxnorm_code: str,
    hours_ago: float,
) -> dict:
    """Generate a medication request for a broad-spectrum antibiotic."""
    med_info = MEDICATIONS[rxnorm_code]
    start_time = datetime.now() - timedelta(hours=hours_ago)

    return {
        "resourceType": "MedicationRequest",
        "id": str(uuid.uuid4()),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": rxnorm_code,
                    "display": med_info["name"],
                }
            ],
            "text": med_info["name"],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "authoredOn": start_time.isoformat(),
        "dosageInstruction": [
            {
                "doseAndRate": [{"doseQuantity": {"value": 40, "unit": "mg/kg"}}],
                "route": {
                    "coding": [{"system": "http://snomed.info/sct", "code": "47625008", "display": "IV"}]
                },
            }
        ],
    }


def generate_positive_blood_culture(
    patient_id: str,
    hours_ago: float = 2,
    organism: tuple | None = None,
) -> dict:
    """Generate a positive blood culture diagnostic report."""
    if organism is None:
        organism = random.choice(ORGANISMS)

    collected_time = datetime.now() - timedelta(hours=hours_ago)

    return {
        "resourceType": "DiagnosticReport",
        "id": str(uuid.uuid4()),
        "status": "final",
        "category": [
            {
                "coding": [
                    {"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "MB", "display": "Microbiology"}
                ]
            }
        ],
        "code": {
            "coding": [{"system": "http://loinc.org", "code": "600-7", "display": "Blood culture"}],
            "text": "Blood Culture",
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": collected_time.isoformat(),
        "conclusion": f"POSITIVE for {organism[0]}",
        "conclusionCode": [
            {
                "coding": [
                    {"system": "http://snomed.info/sct", "code": organism[1], "display": organism[0]}
                ]
            }
        ],
    }


def create_test_scenarios(
    fhir_base_url: str,
    count: int = 20,
    mrn_prefix: str = "SYNTH",
) -> None:
    """Create a mix of test scenarios for both ASP modules."""

    print(f"Creating {count} test patients with various scenarios...")

    # Define scenario distribution
    scenarios = [
        # Bacteremia scenarios (40%)
        {"type": "bacteremia_no_abx", "weight": 10},
        {"type": "bacteremia_with_abx", "weight": 10},
        {"type": "bacteremia_broad_spectrum", "weight": 20},

        # Antimicrobial usage scenarios (60%)
        {"type": "meropenem_under_threshold", "weight": 15},
        {"type": "meropenem_over_threshold", "weight": 15},
        {"type": "vancomycin_under_threshold", "weight": 10},
        {"type": "vancomycin_over_threshold", "weight": 10},
        {"type": "dual_therapy_over_threshold", "weight": 10},
    ]

    # Build weighted list
    weighted_scenarios = []
    for s in scenarios:
        weighted_scenarios.extend([s["type"]] * s["weight"])

    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/fhir+json",
        "Accept": "application/fhir+json",
    })

    created = 0
    for i in range(count):
        scenario = random.choice(weighted_scenarios)

        # Generate patient
        patient = generate_patient(mrn_prefix, i + 1)
        patient_id = patient["id"]

        # Create patient
        response = session.put(f"{fhir_base_url}/Patient/{patient_id}", json=patient)
        response.raise_for_status()

        resources_created = [f"Patient {patient['name'][0]['given'][0]} {patient['name'][0]['family']}"]

        # Create scenario-specific resources
        if scenario == "bacteremia_no_abx":
            # Positive blood culture, no antibiotics yet
            bc = generate_positive_blood_culture(patient_id, hours_ago=random.uniform(1, 6))
            response = session.put(f"{fhir_base_url}/DiagnosticReport/{bc['id']}", json=bc)
            response.raise_for_status()
            resources_created.append("positive blood culture (no abx)")

        elif scenario == "bacteremia_with_abx":
            # Positive blood culture with non-monitored antibiotic
            bc = generate_positive_blood_culture(patient_id, hours_ago=random.uniform(12, 48))
            response = session.put(f"{fhir_base_url}/DiagnosticReport/{bc['id']}", json=bc)
            response.raise_for_status()
            resources_created.append("positive blood culture (generic abx)")

        elif scenario == "bacteremia_broad_spectrum":
            # Positive blood culture with broad-spectrum antibiotic
            bc = generate_positive_blood_culture(patient_id, hours_ago=random.uniform(24, 72))
            response = session.put(f"{fhir_base_url}/DiagnosticReport/{bc['id']}", json=bc)
            response.raise_for_status()

            med = generate_medication_request(patient_id, "29561", hours_ago=random.uniform(20, 70))
            response = session.put(f"{fhir_base_url}/MedicationRequest/{med['id']}", json=med)
            response.raise_for_status()
            resources_created.append("bacteremia + meropenem")

        elif scenario == "meropenem_under_threshold":
            # Meropenem started recently (under 72h)
            hours = random.uniform(12, 70)
            med = generate_medication_request(patient_id, "29561", hours_ago=hours)
            response = session.put(f"{fhir_base_url}/MedicationRequest/{med['id']}", json=med)
            response.raise_for_status()
            resources_created.append(f"meropenem {hours:.0f}h")

        elif scenario == "meropenem_over_threshold":
            # Meropenem over 72h threshold
            hours = random.uniform(73, 168)
            med = generate_medication_request(patient_id, "29561", hours_ago=hours)
            response = session.put(f"{fhir_base_url}/MedicationRequest/{med['id']}", json=med)
            response.raise_for_status()
            resources_created.append(f"meropenem {hours:.0f}h (ALERT)")

        elif scenario == "vancomycin_under_threshold":
            # Vancomycin started recently
            hours = random.uniform(12, 70)
            med = generate_medication_request(patient_id, "11124", hours_ago=hours)
            response = session.put(f"{fhir_base_url}/MedicationRequest/{med['id']}", json=med)
            response.raise_for_status()
            resources_created.append(f"vancomycin {hours:.0f}h")

        elif scenario == "vancomycin_over_threshold":
            # Vancomycin over 72h threshold
            hours = random.uniform(73, 144)
            med = generate_medication_request(patient_id, "11124", hours_ago=hours)
            response = session.put(f"{fhir_base_url}/MedicationRequest/{med['id']}", json=med)
            response.raise_for_status()
            resources_created.append(f"vancomycin {hours:.0f}h (ALERT)")

        elif scenario == "dual_therapy_over_threshold":
            # Both meropenem and vancomycin over threshold
            hours = random.uniform(80, 120)
            med1 = generate_medication_request(patient_id, "29561", hours_ago=hours)
            med2 = generate_medication_request(patient_id, "11124", hours_ago=hours)
            response = session.put(f"{fhir_base_url}/MedicationRequest/{med1['id']}", json=med1)
            response.raise_for_status()
            response = session.put(f"{fhir_base_url}/MedicationRequest/{med2['id']}", json=med2)
            response.raise_for_status()
            resources_created.append(f"dual therapy {hours:.0f}h (ALERT)")

        created += 1
        print(f"  [{created}/{count}] {', '.join(resources_created)}")

    print(f"\nCreated {created} test patients")


def main():
    parser = argparse.ArgumentParser(
        description="Generate pediatric test data for ASP Alerts",
    )
    parser.add_argument(
        "--fhir-url",
        default="http://localhost:8081/fhir",
        help="FHIR server base URL",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of patients to create (default: 20)",
    )
    parser.add_argument(
        "--mrn-prefix",
        default="SYNTH",
        help="Prefix for generated MRNs (default: SYNTH)",
    )

    args = parser.parse_args()

    # Check FHIR server
    try:
        response = requests.get(f"{args.fhir_url}/metadata")
        response.raise_for_status()
        print(f"Connected to FHIR server at {args.fhir_url}")
    except Exception as e:
        print(f"Error: Cannot connect to FHIR server: {e}")
        return 1

    create_test_scenarios(args.fhir_url, args.count, args.mrn_prefix)
    return 0


if __name__ == "__main__":
    exit(main())
