#!/usr/bin/env python3
"""Generate mock Clarity data for NHSN reporting development.

This script creates synthetic data in Clarity-native format (SQLite) for:
- Testing hybrid FHIR/Clarity architecture
- Developing denominator aggregation queries
- CLABSI classification testing with realistic clinical notes

Usage:
    python generate_data.py --patients 50 --months 3
    python generate_data.py --all-scenarios
    python generate_data.py --db-path /path/to/mock_clarity.db
"""

import argparse
import random
import sqlite3
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any

from . import get_schema_sql

# Default database path
DEFAULT_DB_PATH = Path.home() / ".asp-alerts" / "mock_clarity.db"

# CCHMC-specific locations (matching NHSN_LOCATION_MAP in schema)
LOCATIONS = [
    {"dept_id": 100, "code": "T5A", "display": "PICU", "type": "ICU"},
    {"dept_id": 101, "code": "T5B", "display": "CICU", "type": "ICU"},
    {"dept_id": 102, "code": "T4", "display": "NICU", "type": "NICU"},
    {"dept_id": 103, "code": "G5S", "display": "Oncology", "type": "Oncology"},
    {"dept_id": 104, "code": "G6N", "display": "BMT", "type": "BMT"},
    {"dept_id": 105, "code": "A6N", "display": "Hospital Medicine", "type": "Ward"},
]

# Central line types
CENTRAL_LINE_TYPES = ["CVC", "PICC", "Tunneled CVC", "Port"]

# Line insertion sites
LINE_SITES = [
    "Right subclavian",
    "Left subclavian",
    "Right IJ",
    "Left IJ",
    "Right femoral",
    "Left femoral",
    "Right basilic (PICC)",
    "Left basilic (PICC)",
]

# Urinary catheter types
URINARY_CATHETER_TYPES = ["Foley", "Indwelling urinary catheter", "3-way Foley"]

# Urinary catheter sizes (French)
URINARY_CATHETER_SIZES = ["8 Fr", "10 Fr", "12 Fr", "14 Fr", "16 Fr", "18 Fr"]

# Ventilator modes
VENTILATOR_MODES = [
    "SIMV",
    "AC/VC",
    "AC/PC",
    "PRVC",
    "PSV",
    "CPAP",
    "BiPAP",
    "HFOV",
]

# ETT sizes (mm)
ETT_SIZES = ["3.0", "3.5", "4.0", "4.5", "5.0", "5.5", "6.0", "6.5", "7.0", "7.5"]

# Pathogenic organisms (clear CLABSI candidates)
PATHOGENIC_ORGANISMS = [
    "Staphylococcus aureus",
    "Escherichia coli",
    "Klebsiella pneumoniae",
    "Pseudomonas aeruginosa",
    "Candida albicans",
    "Enterococcus faecalis",
    "Enterobacter cloacae",
]

# Antimicrobial medications with NHSN codes (for AU data)
ANTIMICROBIALS = [
    {"med_id": 5001, "name": "amikacin", "nhsn": "AMK", "route": "IV", "dose": 500, "unit": "mg"},
    {"med_id": 5002, "name": "ampicillin", "nhsn": "AMP", "route": "IV", "dose": 2000, "unit": "mg"},
    {"med_id": 5006, "name": "cefazolin", "nhsn": "CFZ", "route": "IV", "dose": 1000, "unit": "mg"},
    {"med_id": 5007, "name": "cefepime", "nhsn": "FEP", "route": "IV", "dose": 2000, "unit": "mg"},
    {"med_id": 5009, "name": "ceftriaxone", "nhsn": "CRO", "route": "IV", "dose": 2000, "unit": "mg"},
    {"med_id": 5010, "name": "ciprofloxacin", "nhsn": "CIP", "route": "PO", "dose": 500, "unit": "mg"},
    {"med_id": 5011, "name": "clindamycin", "nhsn": "CLI", "route": "IV", "dose": 600, "unit": "mg"},
    {"med_id": 5014, "name": "gentamicin", "nhsn": "GEN", "route": "IV", "dose": 240, "unit": "mg"},
    {"med_id": 5017, "name": "meropenem", "nhsn": "MEM", "route": "IV", "dose": 1000, "unit": "mg"},
    {"med_id": 5018, "name": "metronidazole", "nhsn": "MTR", "route": "IV", "dose": 500, "unit": "mg"},
    {"med_id": 5019, "name": "piperacillin/tazobactam", "nhsn": "TZP", "route": "IV", "dose": 4500, "unit": "mg"},
    {"med_id": 5021, "name": "vancomycin", "nhsn": "VAN", "route": "IV", "dose": 1000, "unit": "mg"},
    {"med_id": 5022, "name": "fluconazole", "nhsn": "FLU", "route": "IV", "dose": 400, "unit": "mg"},
]

# Organisms for AR data with typical susceptibility patterns
AR_ORGANISMS = [
    {
        "name": "Staphylococcus aureus",
        "group": "Gram-positive cocci",
        "suscept": {"OXA": "S", "VAN": "S", "CLI": "S", "LZD": "S"},  # MSSA
    },
    {
        "name": "Staphylococcus aureus",
        "group": "Gram-positive cocci",
        "suscept": {"OXA": "R", "VAN": "S", "CLI": "S", "LZD": "S"},  # MRSA
        "phenotype": "MRSA",
    },
    {
        "name": "Escherichia coli",
        "group": "Gram-negative bacilli",
        "suscept": {"AMP": "S", "CRO": "S", "CIP": "S", "GEN": "S", "MEM": "S", "TZP": "S"},
    },
    {
        "name": "Escherichia coli",
        "group": "Gram-negative bacilli",
        "suscept": {"AMP": "R", "CRO": "R", "CIP": "R", "GEN": "S", "MEM": "S", "TZP": "S"},  # MDR
    },
    {
        "name": "Klebsiella pneumoniae",
        "group": "Gram-negative bacilli",
        "suscept": {"AMP": "R", "CRO": "S", "CIP": "S", "GEN": "S", "MEM": "S", "TZP": "S"},
    },
    {
        "name": "Klebsiella pneumoniae",
        "group": "Gram-negative bacilli",
        "suscept": {"AMP": "R", "CRO": "R", "CIP": "R", "GEN": "S", "MEM": "R", "TZP": "R", "ETP": "R"},
        "phenotype": "CRE",
    },
    {
        "name": "Pseudomonas aeruginosa",
        "group": "Gram-negative bacilli",
        "suscept": {"CIP": "S", "GEN": "S", "MEM": "S", "TZP": "S", "FEP": "S", "TOB": "S"},
    },
    {
        "name": "Pseudomonas aeruginosa",
        "group": "Gram-negative bacilli",
        "suscept": {"CIP": "R", "GEN": "R", "MEM": "R", "TZP": "R", "FEP": "R", "TOB": "R"},
        "phenotype": "CRPA",
    },
    {
        "name": "Enterococcus faecalis",
        "group": "Gram-positive cocci",
        "suscept": {"AMP": "S", "VAN": "S", "LZD": "S", "DAP": "S"},
    },
    {
        "name": "Enterococcus faecium",
        "group": "Gram-positive cocci",
        "suscept": {"AMP": "R", "VAN": "R", "LZD": "S", "DAP": "S"},
        "phenotype": "VRE",
    },
    {
        "name": "Enterobacter cloacae",
        "group": "Gram-negative bacilli",
        "suscept": {"AMP": "R", "CRO": "S", "CIP": "S", "GEN": "S", "MEM": "S", "TZP": "S"},
    },
]

# Specimen types for cultures
SPECIMEN_TYPES = ["Blood", "Urine", "Respiratory", "Wound", "CSF"]

# Contaminant organisms (require 2 positive cultures per NHSN)
CONTAMINANT_ORGANISMS = [
    "Coagulase-negative staphylococci",
    "Staphylococcus epidermidis",
    "Corynebacterium species",
    "Micrococcus species",
    "Bacillus species (not anthracis)",
    "Propionibacterium acnes",
]

# GI flora organisms (for MBI-LCBI scenarios)
GI_FLORA_ORGANISMS = [
    "Escherichia coli",
    "Klebsiella pneumoniae",
    "Enterococcus faecalis",
    "Enterococcus faecium (VRE)",
    "Candida species",
    "Enterobacter cloacae",
]

# Pediatric names
FIRST_NAMES = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
    "Isabella", "William", "Mia", "James", "Charlotte", "Benjamin", "Amelia",
    "Lucas", "Harper", "Henry", "Evelyn", "Alexander", "Abigail", "Michael",
    "Emily", "Daniel", "Elizabeth", "Matthew", "Sofia", "Jackson", "Avery",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
]

# Provider names for notes
PROVIDER_NAMES = [
    "Dr. Sarah Chen",
    "Dr. Michael Torres",
    "Dr. Emily Walsh",
    "Dr. James Kim",
    "Dr. Rachel Green",
    "Dr. David Patel",
    "Dr. Lisa Rodriguez",
    "Dr. Mark Johnson",
]


# ============================================================================
# Clinical Note Templates
# ============================================================================

def progress_note_clabsi_candidate(
    age: str,
    gender: str,
    diagnosis: str,
    admission_reason: str,
    line_type: str,
    line_site: str,
    line_days: int,
    organism: str,
    temp: str,
    hr: int,
    bp: str,
    rr: int,
    spo2: int,
) -> str:
    """Generate a progress note for a CLABSI candidate."""
    return f"""SUBJECTIVE:
{age} {gender} with {diagnosis} admitted for {admission_reason}.
Central line ({line_type}) placed at {line_site} - day {line_days} of line.
Fever overnight with Tmax {temp}. Patient reports mild fatigue, no rigors.

OBJECTIVE:
Vitals: T {temp}, HR {hr}, BP {bp}, RR {rr}, SpO2 {spo2}% on RA
General: Alert, appears mildly ill
HEENT: MMM, no thrush
CV: RRR, no murmurs
Lungs: CTAB, no crackles or wheezes
Abdomen: Soft, non-tender, BS+
Central line site ({line_site}): Clean, dry, no erythema or drainage
Extremities: No edema, pulses 2+

Labs:
- WBC 14.2 (elevated)
- Blood cultures: PENDING
- CRP 8.5 (elevated)

ASSESSMENT/PLAN:
1. {diagnosis} - stable
2. Fever with central line in place x {line_days} days
   - Blood cultures sent from line and peripherally
   - Started empiric vancomycin pending cultures
   - No clear alternative source identified
3. Central line ({line_type}, {line_site})
   - Day {line_days}, site appears clean
   - Will monitor closely for signs of infection
   - Consider line removal if cultures positive
"""


def id_consult_note_clabsi(
    organism: str,
    line_type: str,
    line_site: str,
    line_days: int,
    has_alternative_source: bool = False,
    alternative_source: str | None = None,
) -> str:
    """Generate an ID consult note for suspected CLABSI."""
    if has_alternative_source:
        impression = f"""Impression:
Blood culture positive for {organism}.
After review of clinical data, the most likely source is {alternative_source}.
Central line present but does NOT appear to be the primary source.
This does NOT meet NHSN CLABSI criteria."""
        recommendations = f"""Recommendations:
1. Treat underlying {alternative_source} with appropriate antibiotics
2. Central line can remain in place if needed
3. Follow-up cultures not required for CLABSI workup
4. Duration of therapy: per {alternative_source} guidelines"""
    else:
        impression = f"""Impression:
Blood culture positive for {organism}.
Central line ({line_type}) in place for {line_days} days at {line_site}.
No clear alternative source identified on review of imaging and clinical data.
This MEETS criteria for Central Line-Associated Bloodstream Infection (CLABSI)."""
        recommendations = f"""Recommendations:
1. Remove central line if feasible
2. Continue vancomycin (or appropriate antibiotic based on sensitivities)
3. Repeat blood cultures after line removal
4. Duration: minimum 7-14 days depending on organism and response
5. Report to Infection Prevention as NHSN CLABSI"""

    return f"""INFECTIOUS DISEASE CONSULTATION

Reason for consult: Positive blood culture with {organism}

History:
Patient with {line_type} central line placed {line_days} days ago at {line_site}.
Blood cultures drawn for fever evaluation returned positive for {organism}.
Review of recent imaging shows no evidence of pneumonia or intra-abdominal source.
Urinalysis negative. No skin/soft tissue infection noted on exam.

{impression}

{recommendations}

Thank you for this consultation. Will follow.
"""


def id_consult_note_alternative_source(
    organism: str,
    line_days: int,
    alternative_source: str,
    alternative_evidence: str,
) -> str:
    """Generate ID consult note for BSI with alternative source (NOT CLABSI)."""
    return f"""INFECTIOUS DISEASE CONSULTATION

Reason for consult: Positive blood culture with {organism}

History:
Patient with central line in place for {line_days} days.
Blood cultures positive for {organism}.

Clinical Evidence for Alternative Source:
{alternative_evidence}

Impression:
Blood culture positive for {organism}.
Central line present but the clinical picture strongly suggests {alternative_source}
as the primary source of bacteremia.
{alternative_evidence}
This does NOT meet NHSN CLABSI criteria - classified as secondary BSI due to {alternative_source}.

Recommendations:
1. Treat {alternative_source} with appropriate antibiotics
2. Central line may remain if needed for vascular access
3. Not reportable as CLABSI per NHSN criteria
4. Duration of therapy per {alternative_source} guidelines

Thank you for this consultation.
"""


def progress_note_mbi_lcbi(
    organism: str,
    line_days: int,
    days_post_transplant: int,
    anc: int,
    mucositis_grade: int,
) -> str:
    """Generate progress note for MBI-LCBI candidate (BMT patient)."""
    return f"""SUBJECTIVE:
Bone marrow transplant patient, day +{days_post_transplant} post allogeneic BMT.
Fever overnight with rigors. Moderate oral mucositis limiting PO intake.
Reports abdominal cramping and loose stools x2.

OBJECTIVE:
Vitals: T 39.2C, HR 115, BP 95/60, RR 22, SpO2 96% on RA
General: Appears ill, fatigued
HEENT: Grade {mucositis_grade} mucositis with ulcerations
CV: Tachycardic, regular
Lungs: Clear to auscultation
Abdomen: Soft, mild diffuse tenderness, hyperactive bowel sounds
Central line site: Clean, no erythema

Labs:
- WBC 0.3, ANC {anc} (NEUTROPENIC)
- Plt 22 (thrombocytopenic)
- Blood cultures: Positive for {organism}
- Stool C. diff: Negative

ASSESSMENT/PLAN:
1. {organism} bacteremia in neutropenic BMT patient
   - Day +{days_post_transplant}, profound neutropenia (ANC {anc})
   - Grade {mucositis_grade} mucositis present
   - GI organism with intact GI mucositis - likely MBI-LCBI
   - Central line day {line_days} but organism suggests mucosal translocation
2. Mucosal Barrier Injury
   - Continue supportive care
   - TPN for nutritional support
3. Bacteremia management
   - Broad spectrum antibiotics
   - Closely monitor hemodynamics
   - Not classified as CLABSI per NHSN - meets MBI-LCBI criteria
"""


def discharge_summary_clabsi(
    diagnosis: str,
    organism: str,
    line_type: str,
    admission_date: str,
    discharge_date: str,
    antibiotic: str,
    treatment_duration: int,
) -> str:
    """Generate discharge summary for confirmed CLABSI."""
    return f"""DISCHARGE SUMMARY

Admission Date: {admission_date}
Discharge Date: {discharge_date}

Principal Diagnosis:
Central Line-Associated Bloodstream Infection (CLABSI)

Secondary Diagnoses:
1. {diagnosis}
2. {organism} bacteremia

Hospital Course:
Patient admitted for {diagnosis}. During hospitalization, required {line_type}
central line for vascular access. On hospital day X, developed fever and
blood cultures returned positive for {organism}.

Infectious Disease was consulted. After review, no alternative source for
bacteremia was identified. The {line_type} was removed and tip sent for culture.
Patient treated with {antibiotic} for total of {treatment_duration} days.

Repeat blood cultures after line removal were negative. Patient defervesced
and clinically improved.

This event was reported to Infection Prevention as NHSN CLABSI.

Discharge Diagnoses:
1. Central Line-Associated Bloodstream Infection ({organism})
2. {diagnosis}

Discharge Medications:
- {antibiotic} to complete {treatment_duration} day course

Follow-up:
- Infectious Disease clinic in 2 weeks
- PCP in 1 week
"""


# ============================================================================
# Data Generation Functions
# ============================================================================

def generate_mrn() -> str:
    """Generate a realistic MRN."""
    return f"MC{random.randint(100000, 999999)}"


def random_pediatric_birthdate() -> tuple[date, int]:
    """Generate random pediatric birth date. Returns (birth_date, age_years)."""
    age_days = random.choices(
        [
            random.randint(1, 28),       # Neonate
            random.randint(29, 365),     # Infant
            random.randint(366, 1825),   # Toddler (1-5)
            random.randint(1826, 4380),  # Child (5-12)
            random.randint(4381, 6570),  # Adolescent (12-18)
        ],
        weights=[15, 20, 25, 25, 15],
    )[0]
    birth_date = (datetime.now() - timedelta(days=age_days)).date()
    age_years = age_days // 365
    return birth_date, age_years


def age_string(age_years: int) -> str:
    """Convert age in years to descriptive string."""
    if age_years < 1:
        return "infant"
    elif age_years < 2:
        return "1 year old"
    elif age_years < 13:
        return f"{age_years} year old"
    else:
        return f"{age_years} year old adolescent"


class MockClarityGenerator:
    """Generate mock Clarity database with CLABSI scenarios."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # ID counters
        self.pat_id_counter = 1000
        self.enc_id_counter = 10000
        self.note_id_counter = 100000
        self.order_id_counter = 200000
        self.fsd_id_counter = 300000
        self.prov_id_counter = 500
        self.order_med_id_counter = 400000
        self.mar_admin_id_counter = 500000
        self.culture_id_counter = 600000
        self.culture_org_id_counter = 700000
        self.suscept_id_counter = 800000

        # Track generated data
        self.patients: list[dict] = []
        self.encounters: list[dict] = []
        self.notes: list[dict] = []
        self.flowsheets: list[dict] = []
        self.cultures: list[dict] = []
        self.providers: list[dict] = []
        # AU/AR data
        self.medication_orders: list[dict] = []
        self.mar_administrations: list[dict] = []
        self.ar_cultures: list[dict] = []
        self.ar_organisms: list[dict] = []
        self.ar_susceptibilities: list[dict] = []

    def initialize_database(self):
        """Create database and schema."""
        conn = sqlite3.connect(self.db_path)
        conn.executescript(get_schema_sql())
        conn.commit()
        conn.close()
        print(f"Initialized database at {self.db_path}")

    def _next_pat_id(self) -> int:
        self.pat_id_counter += 1
        return self.pat_id_counter

    def _next_enc_id(self) -> int:
        self.enc_id_counter += 1
        return self.enc_id_counter

    def _next_note_id(self) -> int:
        self.note_id_counter += 1
        return self.note_id_counter

    def _next_order_id(self) -> int:
        self.order_id_counter += 1
        return self.order_id_counter

    def _next_fsd_id(self) -> int:
        self.fsd_id_counter += 1
        return self.fsd_id_counter

    def _next_prov_id(self) -> int:
        self.prov_id_counter += 1
        return self.prov_id_counter

    def _next_order_med_id(self) -> int:
        self.order_med_id_counter += 1
        return self.order_med_id_counter

    def _next_mar_admin_id(self) -> int:
        self.mar_admin_id_counter += 1
        return self.mar_admin_id_counter

    def _next_culture_id(self) -> int:
        self.culture_id_counter += 1
        return self.culture_id_counter

    def _next_culture_org_id(self) -> int:
        self.culture_org_id_counter += 1
        return self.culture_org_id_counter

    def _next_suscept_id(self) -> int:
        self.suscept_id_counter += 1
        return self.suscept_id_counter

    def generate_providers(self):
        """Generate provider records."""
        for name in PROVIDER_NAMES:
            self.providers.append({
                "prov_id": self._next_prov_id(),
                "prov_name": name,
            })

    def generate_patient(self) -> dict:
        """Generate a patient record."""
        birth_date, age_years = random_pediatric_birthdate()
        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)
        gender = random.choice(["male", "female"])

        patient = {
            "pat_id": self._next_pat_id(),
            "pat_mrn_id": generate_mrn(),
            "pat_name": f"{last_name}, {first_name}",
            "birth_date": birth_date,
            "age_years": age_years,
            "gender": gender,
            "first_name": first_name,
        }
        self.patients.append(patient)
        return patient

    def generate_encounter(
        self,
        patient: dict,
        location: dict,
        admit_date: datetime,
        discharge_date: datetime | None = None,
    ) -> dict:
        """Generate an encounter record."""
        enc_id = self._next_enc_id()
        encounter = {
            "pat_enc_csn_id": enc_id,
            "pat_id": patient["pat_id"],
            "inpatient_data_id": enc_id,  # Use same ID for simplicity
            "hosp_admit_dttm": admit_date,
            "hosp_disch_dttm": discharge_date,
            "department_id": location["dept_id"],
            "location": location,
        }
        self.encounters.append(encounter)
        return encounter

    def generate_central_line_flowsheets(
        self,
        encounter: dict,
        line_type: str,
        site: str,
        insertion_date: datetime,
        removal_date: datetime | None = None,
    ) -> list[dict]:
        """Generate daily flowsheet entries for central line presence."""
        flowsheets = []
        fsd_id = self._next_fsd_id()

        # Flowsheet record
        flowsheets.append({
            "fsd_id": fsd_id,
            "inpatient_data_id": encounter["inpatient_data_id"],
        })

        # Generate daily measurements from insertion to removal (or now)
        end_date = removal_date or datetime.now()
        current_date = insertion_date

        while current_date <= end_date:
            # Central line present entry
            flowsheets.append({
                "flo_meas_id": 1001,  # Central Line Present
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": line_type if current_date < (removal_date or datetime.max) else "removed",
            })

            # Site entry
            flowsheets.append({
                "flo_meas_id": 1002,  # Central Line Site
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": site,
            })

            current_date += timedelta(days=1)

        self.flowsheets.extend(flowsheets)
        return flowsheets

    def generate_urinary_catheter_flowsheets(
        self,
        encounter: dict,
        catheter_type: str,
        catheter_size: str,
        insertion_date: datetime,
        removal_date: datetime | None = None,
    ) -> list[dict]:
        """Generate daily flowsheet entries for urinary catheter presence."""
        flowsheets = []
        fsd_id = self._next_fsd_id()

        # Flowsheet record
        flowsheets.append({
            "fsd_id": fsd_id,
            "inpatient_data_id": encounter["inpatient_data_id"],
        })

        # Generate daily measurements from insertion to removal (or now)
        end_date = removal_date or datetime.now()
        current_date = insertion_date

        while current_date <= end_date:
            # Foley catheter present entry
            flowsheets.append({
                "flo_meas_id": 2101,  # Foley Catheter Present
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": catheter_type if current_date < (removal_date or datetime.max) else "removed",
            })

            # Size entry
            flowsheets.append({
                "flo_meas_id": 2103,  # Foley Catheter Size
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": catheter_size,
            })

            current_date += timedelta(days=1)

        self.flowsheets.extend(flowsheets)
        return flowsheets

    def generate_ventilator_flowsheets(
        self,
        encounter: dict,
        vent_mode: str,
        ett_size: str,
        intubation_date: datetime,
        extubation_date: datetime | None = None,
    ) -> list[dict]:
        """Generate daily flowsheet entries for mechanical ventilation."""
        flowsheets = []
        fsd_id = self._next_fsd_id()

        # Flowsheet record
        flowsheets.append({
            "fsd_id": fsd_id,
            "inpatient_data_id": encounter["inpatient_data_id"],
        })

        # Generate daily measurements from intubation to extubation (or now)
        end_date = extubation_date or datetime.now()
        current_date = intubation_date

        while current_date <= end_date:
            is_active = current_date < (extubation_date or datetime.max)

            # Ventilator mode entry
            flowsheets.append({
                "flo_meas_id": 3101,  # Ventilator Mode
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": vent_mode if is_active else "extubated",
            })

            # Mechanical ventilation status
            flowsheets.append({
                "flo_meas_id": 3102,  # Mechanical Ventilation
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": "Yes" if is_active else "No - extubated",
            })

            # ETT size
            flowsheets.append({
                "flo_meas_id": 3105,  # ETT Size
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": ett_size,
            })

            # Ventilator settings (FiO2 and PEEP with some variation)
            fio2 = random.randint(21, 60) if is_active else 21
            peep = random.randint(5, 12) if is_active else 0

            flowsheets.append({
                "flo_meas_id": 3106,  # Ventilator FiO2
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": f"{fio2}%",
            })

            flowsheets.append({
                "flo_meas_id": 3107,  # Ventilator PEEP
                "fsd_id": fsd_id,
                "recorded_time": current_date,
                "meas_value": f"{peep} cmH2O",
            })

            current_date += timedelta(days=1)

        self.flowsheets.extend(flowsheets)
        return flowsheets

    def generate_blood_culture(
        self,
        patient: dict,
        collection_date: datetime,
        organism: str | None,
        is_positive: bool = True,
    ) -> dict:
        """Generate blood culture order and result."""
        order_proc_id = self._next_order_id()
        order_id = self._next_order_id()
        result_date = collection_date + timedelta(hours=random.randint(24, 72))

        if is_positive and organism:
            ord_value = f"Positive - Growth of {organism}"
        elif is_positive:
            ord_value = "Positive - organism pending identification"
        else:
            ord_value = "No growth after 5 days"

        culture = {
            "order_proc_id": order_proc_id,
            "order_id": order_id,
            "pat_id": patient["pat_id"],
            "proc_name": "Blood Culture",
            "specimn_taken_time": collection_date,
            "result_time": result_date,
            "component_id": 2002 if organism else 2001,
            "organism": organism,
            "ord_value": ord_value,
        }
        self.cultures.append(culture)
        return culture

    def generate_clinical_note(
        self,
        encounter: dict,
        note_type_c: int,
        note_date: datetime,
        content: str,
    ) -> dict:
        """Generate a clinical note."""
        note = {
            "note_id": self._next_note_id(),
            "pat_enc_csn_id": encounter["pat_enc_csn_id"],
            "entry_instant_dttm": note_date,
            "entry_user_id": random.choice(self.providers)["prov_id"],
            "note_type_c": note_type_c,
            "note_text": content,
        }
        self.notes.append(note)
        return note

    # ========================================================================
    # AU/AR Data Generators
    # ========================================================================

    def generate_medication_order(
        self,
        encounter: dict,
        antimicrobial: dict,
        start_date: datetime,
        duration_days: int,
        frequency_hours: int = 8,
    ) -> dict:
        """Generate a medication order with administrations.

        Args:
            encounter: Patient encounter dict
            antimicrobial: Antimicrobial from ANTIMICROBIALS list
            start_date: When the order was started
            duration_days: How many days of therapy
            frequency_hours: Hours between doses (e.g., 8 for Q8H)
        """
        order_med_id = self._next_order_med_id()

        # Create the order
        order = {
            "order_med_id": order_med_id,
            "pat_enc_csn_id": encounter["pat_enc_csn_id"],
            "medication_id": antimicrobial["med_id"],
            "ordering_date": start_date,
            "admin_route": antimicrobial["route"],
            "dose": antimicrobial["dose"],
            "dose_unit": antimicrobial["unit"],
            "frequency": f"Q{frequency_hours}H",
        }
        self.medication_orders.append(order)

        # Generate administrations for each dose
        doses_per_day = 24 // frequency_hours
        current_time = start_date

        for day in range(duration_days):
            for dose_num in range(doses_per_day):
                # 90% chance each dose was actually given
                action = "Given" if random.random() < 0.9 else random.choice(["Held", "Refused"])

                admin = {
                    "mar_admin_id": self._next_mar_admin_id(),
                    "order_med_id": order_med_id,
                    "taken_time": current_time,
                    "action_name": action,
                    "dose_given": antimicrobial["dose"] / 1000 if action == "Given" else 0,  # Convert mg to g
                    "dose_unit": "g",
                }
                self.mar_administrations.append(admin)
                current_time += timedelta(hours=frequency_hours)

        return order

    def generate_ar_culture(
        self,
        patient: dict,
        encounter: dict,
        specimen_date: datetime,
        organism_data: dict,
        specimen_type: str = "Blood",
    ) -> dict:
        """Generate a culture with organism and susceptibility data for AR reporting.

        Args:
            patient: Patient dict
            encounter: Patient encounter dict
            specimen_date: When the specimen was collected
            organism_data: Organism from AR_ORGANISMS list
            specimen_type: Type of specimen
        """
        culture_id = self._next_culture_id()
        culture_org_id = self._next_culture_org_id()
        result_date = specimen_date + timedelta(hours=random.randint(24, 72))

        # Create culture result
        culture = {
            "culture_id": culture_id,
            "pat_id": patient["pat_id"],
            "pat_enc_csn_id": encounter["pat_enc_csn_id"],
            "specimen_taken_time": specimen_date,
            "result_time": result_date,
            "specimen_type": specimen_type,
            "specimen_source": random.choice(["Peripheral", "Central Line", "Midstream", "Catheter"]),
            "culture_status": "Positive",
        }
        self.ar_cultures.append(culture)

        # Create organism
        organism = {
            "culture_organism_id": culture_org_id,
            "culture_id": culture_id,
            "organism_name": organism_data["name"],
            "organism_group": organism_data["group"],
            "cfu_count": ">100000" if specimen_type == "Urine" else None,
            "is_primary": 1,
        }
        self.ar_organisms.append(organism)

        # Create susceptibility results
        abx_names = {
            "OXA": "Oxacillin", "VAN": "Vancomycin", "CLI": "Clindamycin", "LZD": "Linezolid",
            "DAP": "Daptomycin", "AMP": "Ampicillin", "CRO": "Ceftriaxone", "CIP": "Ciprofloxacin",
            "GEN": "Gentamicin", "MEM": "Meropenem", "TZP": "Piperacillin/Tazobactam",
            "FEP": "Cefepime", "TOB": "Tobramycin", "ETP": "Ertapenem", "CTX": "Cefotaxime",
            "CAZ": "Ceftazidime", "IPM": "Imipenem",
        }

        for abx_code, interpretation in organism_data["suscept"].items():
            suscept = {
                "susceptibility_id": self._next_suscept_id(),
                "culture_organism_id": culture_org_id,
                "antibiotic": abx_names.get(abx_code, abx_code),
                "antibiotic_code": abx_code,
                "mic": random.uniform(0.25, 16) if interpretation == "R" else random.uniform(0.1, 1),
                "mic_units": "mcg/mL",
                "interpretation": interpretation,
                "method": "MIC",
            }
            self.ar_susceptibilities.append(suscept)

        return culture

    def generate_au_data_for_encounter(
        self,
        encounter: dict,
        num_antibiotics: int = None,
    ):
        """Generate AU (antibiotic usage) data for an encounter.

        Args:
            encounter: Patient encounter dict
            num_antibiotics: Number of antibiotics (random 1-3 if not specified)
        """
        if num_antibiotics is None:
            num_antibiotics = random.randint(1, 3)

        admit_date = encounter["hosp_admit_dttm"]
        discharge_date = encounter.get("hosp_disch_dttm") or (admit_date + timedelta(days=random.randint(5, 14)))
        los = (discharge_date - admit_date).days

        # Pick random antibiotics
        selected_abx = random.sample(ANTIMICROBIALS, min(num_antibiotics, len(ANTIMICROBIALS)))

        for abx in selected_abx:
            # Start 0-2 days after admission
            start_offset = random.randint(0, min(2, max(0, los - 1)))
            start_date = admit_date + timedelta(days=start_offset)

            # Duration: 2-7 days, but not past discharge
            max_duration = max(2, (discharge_date - start_date).days)
            duration = random.randint(2, min(7, max_duration))

            # Random frequency
            frequency = random.choice([6, 8, 12, 24])

            self.generate_medication_order(
                encounter=encounter,
                antimicrobial=abx,
                start_date=start_date,
                duration_days=duration,
                frequency_hours=frequency,
            )

    def generate_ar_data_for_encounter(
        self,
        patient: dict,
        encounter: dict,
        num_cultures: int = None,
    ):
        """Generate AR (antimicrobial resistance) data for an encounter.

        Args:
            patient: Patient dict
            encounter: Patient encounter dict
            num_cultures: Number of cultures (random 1-2 if not specified)
        """
        if num_cultures is None:
            num_cultures = random.randint(1, 2)

        admit_date = encounter["hosp_admit_dttm"]
        discharge_date = encounter.get("hosp_disch_dttm") or (admit_date + timedelta(days=random.randint(5, 14)))
        los = (discharge_date - admit_date).days

        for _ in range(num_cultures):
            # Culture date: random during admission
            culture_offset = random.randint(0, max(0, los - 1))
            culture_date = admit_date + timedelta(days=culture_offset)

            # Pick random organism
            organism = random.choice(AR_ORGANISMS)

            # Pick random specimen type
            specimen_type = random.choice(SPECIMEN_TYPES)

            self.generate_ar_culture(
                patient=patient,
                encounter=encounter,
                specimen_date=culture_date,
                organism_data=organism,
                specimen_type=specimen_type,
            )

    def generate_au_ar_data(
        self,
        months: int = 3,
        encounters_with_au: int = 50,
        encounters_with_ar: int = 30,
        base_time: datetime | None = None,
    ):
        """Generate AU and AR demo data using existing patients/encounters.

        Args:
            months: Months of historical data
            encounters_with_au: Number of encounters to add AU data
            encounters_with_ar: Number of encounters to add AR data
            base_time: Base time for data generation
        """
        base_time = base_time or datetime.now()
        start_date = base_time - timedelta(days=months * 30)

        print(f"\nGenerating AU/AR demo data...")
        print(f"  Date range: {start_date.date()} to {base_time.date()}")

        # Use existing encounters or create new ones if not enough
        available_encounters = [e for e in self.encounters if e.get("hosp_admit_dttm")]

        # Generate AU data
        au_encounters = random.sample(
            available_encounters,
            min(encounters_with_au, len(available_encounters))
        ) if available_encounters else []

        for enc in au_encounters:
            self.generate_au_data_for_encounter(enc)

        print(f"  Generated AU data for {len(au_encounters)} encounters")
        print(f"    - {len(self.medication_orders)} medication orders")
        print(f"    - {len(self.mar_administrations)} MAR administrations")

        # Generate AR data
        ar_encounters = random.sample(
            available_encounters,
            min(encounters_with_ar, len(available_encounters))
        ) if available_encounters else []

        for enc in ar_encounters:
            # Find the patient for this encounter
            patient = next(
                (p for p in self.patients if p["pat_id"] == enc["pat_id"]),
                None
            )
            if patient:
                self.generate_ar_data_for_encounter(patient, enc)

        print(f"  Generated AR data for {len(ar_encounters)} encounters")
        print(f"    - {len(self.ar_cultures)} cultures")
        print(f"    - {len(self.ar_organisms)} organisms")
        print(f"    - {len(self.ar_susceptibilities)} susceptibility results")

    # ========================================================================
    # Scenario Generators
    # ========================================================================

    def scenario_true_clabsi(self, base_time: datetime) -> dict:
        """Generate a true CLABSI case."""
        patient = self.generate_patient()
        location = random.choice([l for l in LOCATIONS if l["type"] == "ICU"])

        admission_date = base_time - timedelta(days=random.randint(5, 14))
        line_insertion = admission_date + timedelta(days=1)
        culture_date = base_time - timedelta(hours=random.randint(12, 48))
        line_days = (culture_date - line_insertion).days

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(PATHOGENIC_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion
        )
        self.generate_blood_culture(patient, culture_date, organism)

        # Progress note
        self.generate_clinical_note(
            encounter,
            1,  # Progress note
            culture_date + timedelta(hours=6),
            progress_note_clabsi_candidate(
                age=age_string(patient["age_years"]),
                gender=patient["gender"],
                diagnosis="acute lymphoblastic leukemia" if random.random() > 0.5 else "respiratory failure",
                admission_reason="fever and neutropenia" if random.random() > 0.5 else "respiratory distress",
                line_type=line_type,
                line_site=site,
                line_days=line_days,
                organism=organism,
                temp="38.9C",
                hr=random.randint(100, 130),
                bp=f"{random.randint(90, 110)}/{random.randint(55, 70)}",
                rr=random.randint(18, 28),
                spo2=random.randint(94, 99),
            ),
        )

        # ID consult
        self.generate_clinical_note(
            encounter,
            10,  # ID Consult
            culture_date + timedelta(hours=12),
            id_consult_note_clabsi(
                organism=organism,
                line_type=line_type,
                line_site=site,
                line_days=line_days,
                has_alternative_source=False,
            ),
        )

        return {
            "scenario": "true_clabsi",
            "expected": "CLABSI confirmed",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
            "line_days": line_days,
        }

    def scenario_contaminant_single(self, base_time: datetime) -> dict:
        """Generate a single contaminant culture (should be rejected)."""
        patient = self.generate_patient()
        location = random.choice(LOCATIONS)

        admission_date = base_time - timedelta(days=random.randint(3, 10))
        line_insertion = admission_date + timedelta(days=1)
        culture_date = base_time - timedelta(hours=random.randint(12, 48))

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(CONTAMINANT_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion
        )
        self.generate_blood_culture(patient, culture_date, organism)

        return {
            "scenario": "contaminant_single",
            "expected": "Reject - single contaminant culture",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_contaminant_confirmed(self, base_time: datetime) -> dict:
        """Generate confirmed contaminant (2 cultures on different days = CLABSI)."""
        patient = self.generate_patient()
        location = random.choice(LOCATIONS)

        admission_date = base_time - timedelta(days=random.randint(5, 10))
        line_insertion = admission_date + timedelta(days=1)
        culture_date1 = base_time - timedelta(hours=48)
        culture_date2 = base_time - timedelta(hours=24)
        line_days = (culture_date1 - line_insertion).days

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(CONTAMINANT_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion
        )
        self.generate_blood_culture(patient, culture_date1, organism)
        self.generate_blood_culture(patient, culture_date2, organism)

        # Note mentioning two positive cultures
        self.generate_clinical_note(
            encounter,
            1,
            culture_date2 + timedelta(hours=6),
            f"""ASSESSMENT/PLAN:
Patient with two positive blood cultures for {organism} drawn on separate days.
Central line in place for {line_days} days.
Per NHSN criteria, two positive cultures for common skin contaminant organism
from separate blood draws on different days meets CLABSI definition.
No alternative source identified.
Recommend line removal and antibiotic therapy.
""",
        )

        return {
            "scenario": "contaminant_confirmed",
            "expected": "CLABSI confirmed (2 contaminant cultures)",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_secondary_bsi_uti(self, base_time: datetime) -> dict:
        """Generate BSI secondary to UTI (NOT CLABSI)."""
        patient = self.generate_patient()
        location = random.choice(LOCATIONS)

        admission_date = base_time - timedelta(days=random.randint(5, 10))
        line_insertion = admission_date + timedelta(days=1)
        culture_date = base_time - timedelta(hours=random.randint(12, 48))
        line_days = (culture_date - line_insertion).days

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(["Escherichia coli", "Klebsiella pneumoniae", "Enterococcus faecalis"])

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion
        )
        self.generate_blood_culture(patient, culture_date, organism)

        # ID consult documenting UTI as source
        self.generate_clinical_note(
            encounter,
            10,
            culture_date + timedelta(hours=12),
            id_consult_note_alternative_source(
                organism=organism,
                line_days=line_days,
                alternative_source="urinary tract infection",
                alternative_evidence=f"""- Urinalysis shows pyuria (>50 WBC/hpf) and bacteriuria
- Urine culture positive for same organism ({organism})
- Patient with indwelling Foley catheter x 5 days
- Symptoms of dysuria and suprapubic tenderness
- Blood culture organism matches urine culture organism
- Central line site clean with no signs of infection""",
            ),
        )

        return {
            "scenario": "secondary_bsi_uti",
            "expected": "Reject - secondary BSI from UTI",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_secondary_bsi_pneumonia(self, base_time: datetime) -> dict:
        """Generate BSI secondary to pneumonia (NOT CLABSI)."""
        patient = self.generate_patient()
        location = random.choice([l for l in LOCATIONS if l["type"] == "ICU"])

        admission_date = base_time - timedelta(days=random.randint(7, 14))
        line_insertion = admission_date + timedelta(days=1)
        culture_date = base_time - timedelta(hours=random.randint(12, 48))
        line_days = (culture_date - line_insertion).days

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(["Pseudomonas aeruginosa", "Klebsiella pneumoniae", "Staphylococcus aureus"])

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion
        )
        self.generate_blood_culture(patient, culture_date, organism)

        # ID consult documenting pneumonia as source
        self.generate_clinical_note(
            encounter,
            10,
            culture_date + timedelta(hours=12),
            id_consult_note_alternative_source(
                organism=organism,
                line_days=line_days,
                alternative_source="ventilator-associated pneumonia",
                alternative_evidence=f"""- Chest X-ray shows new right lower lobe consolidation
- Increased ventilator requirements over past 48 hours
- Purulent secretions from ETT
- Respiratory culture positive for same organism ({organism})
- Patient intubated x 7 days, high risk for VAP
- Central line site clean with no signs of infection""",
            ),
        )

        return {
            "scenario": "secondary_bsi_pneumonia",
            "expected": "Reject - secondary BSI from pneumonia",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_no_central_line(self, base_time: datetime) -> dict:
        """Generate positive culture with no central line (NOT CLABSI candidate)."""
        patient = self.generate_patient()
        location = random.choice(LOCATIONS)

        admission_date = base_time - timedelta(days=random.randint(2, 5))
        culture_date = base_time - timedelta(hours=random.randint(12, 48))
        organism = random.choice(PATHOGENIC_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        # No central line flowsheets!
        self.generate_blood_culture(patient, culture_date, organism)

        self.generate_clinical_note(
            encounter,
            1,
            culture_date + timedelta(hours=6),
            f"""ASSESSMENT/PLAN:
{organism} bacteremia. Patient has peripheral IV only, no central line present.
Workup for source ongoing.
Not eligible for CLABSI - no central venous catheter.
""",
        )

        return {
            "scenario": "no_central_line",
            "expected": "Reject - no central line present",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_line_just_removed(self, base_time: datetime) -> dict:
        """Generate culture within 1 day of line removal (CLABSI eligible)."""
        patient = self.generate_patient()
        location = random.choice(LOCATIONS)

        admission_date = base_time - timedelta(days=random.randint(7, 14))
        line_insertion = admission_date + timedelta(days=1)
        line_removal = base_time - timedelta(hours=36)
        culture_date = base_time - timedelta(hours=12)  # Within 1 day of removal
        line_days = (line_removal - line_insertion).days

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(PATHOGENIC_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion, line_removal
        )
        self.generate_blood_culture(patient, culture_date, organism)

        self.generate_clinical_note(
            encounter,
            1,
            culture_date + timedelta(hours=6),
            f"""ASSESSMENT/PLAN:
{organism} bacteremia 24 hours after central line removal.
Line was in place for {line_days} days prior to removal.
Per NHSN criteria, BSI within 1 calendar day of line removal
can be attributed to the central line.
Meets CLABSI criteria.
""",
        )

        return {
            "scenario": "line_just_removed",
            "expected": "CLABSI confirmed (within 1 day of removal)",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_line_removed_too_long(self, base_time: datetime) -> dict:
        """Generate culture >1 day after line removal (NOT CLABSI)."""
        patient = self.generate_patient()
        location = random.choice(LOCATIONS)

        admission_date = base_time - timedelta(days=random.randint(7, 14))
        line_insertion = admission_date + timedelta(days=1)
        line_removal = base_time - timedelta(days=3)
        culture_date = base_time - timedelta(hours=12)  # >1 day after removal

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(PATHOGENIC_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion, line_removal
        )
        self.generate_blood_culture(patient, culture_date, organism)

        self.generate_clinical_note(
            encounter,
            1,
            culture_date + timedelta(hours=6),
            f"""ASSESSMENT/PLAN:
{organism} bacteremia. Central line was removed 3 days ago.
Per NHSN criteria, BSI occurring >1 day after line removal
cannot be attributed to the central line.
Does NOT meet CLABSI criteria.
""",
        )

        return {
            "scenario": "line_removed_too_long",
            "expected": "Reject - line removed >1 day before culture",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_short_dwell(self, base_time: datetime) -> dict:
        """Generate culture with line <2 days (NOT CLABSI eligible)."""
        patient = self.generate_patient()
        location = random.choice(LOCATIONS)

        admission_date = base_time - timedelta(days=2)
        line_insertion = base_time - timedelta(days=1)  # Only 1 day
        culture_date = base_time - timedelta(hours=6)

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(PATHOGENIC_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion
        )
        self.generate_blood_culture(patient, culture_date, organism)

        return {
            "scenario": "short_dwell",
            "expected": "Reject - line present <2 days",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def scenario_mbi_lcbi(self, base_time: datetime) -> dict:
        """Generate MBI-LCBI case (BMT patient with GI organism)."""
        patient = self.generate_patient()
        location = random.choice([l for l in LOCATIONS if l["code"] in ["G5S", "G6N"]])

        admission_date = base_time - timedelta(days=random.randint(14, 21))
        line_insertion = admission_date + timedelta(days=1)
        culture_date = base_time - timedelta(hours=random.randint(12, 48))
        line_days = (culture_date - line_insertion).days
        days_post_transplant = random.randint(7, 14)

        line_type = random.choice(CENTRAL_LINE_TYPES)
        site = random.choice(LINE_SITES)
        organism = random.choice(GI_FLORA_ORGANISMS)

        encounter = self.generate_encounter(patient, location, admission_date)
        self.generate_central_line_flowsheets(
            encounter, line_type, site, line_insertion
        )
        self.generate_blood_culture(patient, culture_date, organism)

        # MBI-LCBI specific progress note
        self.generate_clinical_note(
            encounter,
            1,
            culture_date + timedelta(hours=6),
            progress_note_mbi_lcbi(
                organism=organism,
                line_days=line_days,
                days_post_transplant=days_post_transplant,
                anc=random.randint(0, 100),
                mucositis_grade=random.randint(2, 4),
            ),
        )

        return {
            "scenario": "mbi_lcbi",
            "expected": "MBI-LCBI (not counted as CLABSI)",
            "patient_mrn": patient["pat_mrn_id"],
            "organism": organism,
        }

    def generate_random_patients(
        self,
        count: int,
        months: int,
        base_time: datetime | None = None,
    ):
        """Generate random patients with encounters and various devices."""
        base_time = base_time or datetime.now()
        start_date = base_time - timedelta(days=months * 30)

        for _ in range(count):
            patient = self.generate_patient()
            location = random.choice(LOCATIONS)

            # Random admission within the date range
            days_offset = random.randint(0, months * 30 - 7)
            admission_date = start_date + timedelta(days=days_offset)
            los = random.randint(3, 21)
            discharge_date = admission_date + timedelta(days=los)
            if discharge_date > base_time:
                discharge_date = None

            encounter = self.generate_encounter(
                patient, location, admission_date, discharge_date
            )

            # 60% chance of having a central line
            if random.random() < 0.6:
                line_insertion = admission_date + timedelta(days=random.randint(0, 2))
                line_type = random.choice(CENTRAL_LINE_TYPES)
                site = random.choice(LINE_SITES)

                # 30% chance line was removed
                days_until_discharge = (discharge_date - line_insertion).days if discharge_date else 0
                if random.random() < 0.3 and discharge_date and days_until_discharge >= 3:
                    removal_date = line_insertion + timedelta(
                        days=random.randint(3, days_until_discharge)
                    )
                else:
                    removal_date = None

                self.generate_central_line_flowsheets(
                    encounter, line_type, site, line_insertion, removal_date
                )

            # 40% chance of having urinary catheter
            if random.random() < 0.4:
                catheter_insertion = admission_date + timedelta(days=random.randint(0, 2))
                catheter_type = random.choice(URINARY_CATHETER_TYPES)
                catheter_size = random.choice(URINARY_CATHETER_SIZES)

                # 50% chance catheter was removed before discharge
                if random.random() < 0.5 and discharge_date:
                    max_days = max(1, (discharge_date - catheter_insertion).days)
                    removal_date = catheter_insertion + timedelta(
                        days=random.randint(1, max_days)
                    )
                else:
                    removal_date = None

                self.generate_urinary_catheter_flowsheets(
                    encounter, catheter_type, catheter_size, catheter_insertion, removal_date
                )

            # 25% chance of mechanical ventilation (higher in ICU)
            vent_probability = 0.5 if location["type"] == "ICU" else 0.15
            if random.random() < vent_probability:
                intubation_date = admission_date + timedelta(days=random.randint(0, 2))
                vent_mode = random.choice(VENTILATOR_MODES)
                ett_size = random.choice(ETT_SIZES)

                # 60% chance of extubation before discharge
                if random.random() < 0.6 and discharge_date:
                    max_days = max(1, (discharge_date - intubation_date).days)
                    extubation_date = intubation_date + timedelta(
                        days=random.randint(1, max_days)
                    )
                else:
                    extubation_date = None

                self.generate_ventilator_flowsheets(
                    encounter, vent_mode, ett_size, intubation_date, extubation_date
                )

            # Generate some notes
            num_notes = random.randint(1, 4)
            for i in range(num_notes):
                note_date = admission_date + timedelta(days=i)
                self.generate_clinical_note(
                    encounter,
                    random.choice([1, 2]),  # Progress notes
                    note_date,
                    f"Day {i+1} progress note. Patient stable, continue current management.",
                )

    def generate_all_scenarios(self, base_time: datetime | None = None):
        """Generate one of each scenario type."""
        base_time = base_time or datetime.now()
        scenarios = []

        scenario_methods = [
            self.scenario_true_clabsi,
            self.scenario_true_clabsi,  # Weight: more true positives
            self.scenario_contaminant_single,
            self.scenario_contaminant_confirmed,
            self.scenario_secondary_bsi_uti,
            self.scenario_secondary_bsi_pneumonia,
            self.scenario_no_central_line,
            self.scenario_line_just_removed,
            self.scenario_line_removed_too_long,
            self.scenario_short_dwell,
            self.scenario_mbi_lcbi,
        ]

        for method in scenario_methods:
            result = method(base_time)
            scenarios.append(result)
            print(f"  Generated: {result['scenario']} - {result['patient_mrn']}")

        return scenarios

    def load_to_database(self):
        """Load all generated data to the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Load providers
        for prov in self.providers:
            cursor.execute(
                "INSERT OR REPLACE INTO CLARITY_EMP (PROV_ID, PROV_NAME) VALUES (?, ?)",
                (prov["prov_id"], prov["prov_name"]),
            )

        # Load patients
        for pat in self.patients:
            cursor.execute(
                """INSERT OR REPLACE INTO PATIENT (PAT_ID, PAT_MRN_ID, PAT_NAME, BIRTH_DATE)
                   VALUES (?, ?, ?, ?)""",
                (pat["pat_id"], pat["pat_mrn_id"], pat["pat_name"], pat["birth_date"]),
            )

        # Load encounters
        for enc in self.encounters:
            cursor.execute(
                """INSERT OR REPLACE INTO PAT_ENC
                   (PAT_ENC_CSN_ID, PAT_ID, INPATIENT_DATA_ID, HOSP_ADMIT_DTTM,
                    HOSP_DISCH_DTTM, DEPARTMENT_ID)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    enc["pat_enc_csn_id"],
                    enc["pat_id"],
                    enc["inpatient_data_id"],
                    enc["hosp_admit_dttm"],
                    enc["hosp_disch_dttm"],
                    enc["department_id"],
                ),
            )

        # Load notes
        for note in self.notes:
            cursor.execute(
                """INSERT OR REPLACE INTO HNO_INFO
                   (NOTE_ID, PAT_ENC_CSN_ID, ENTRY_INSTANT_DTTM, ENTRY_USER_ID, NOTE_TEXT)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    note["note_id"],
                    note["pat_enc_csn_id"],
                    note["entry_instant_dttm"],
                    note["entry_user_id"],
                    note["note_text"],
                ),
            )
            cursor.execute(
                """INSERT OR REPLACE INTO IP_NOTE_TYPE (NOTE_ID, NOTE_TYPE_C)
                   VALUES (?, ?)""",
                (note["note_id"], note["note_type_c"]),
            )

        # Load flowsheets
        fsd_ids_loaded = set()
        for fs in self.flowsheets:
            if "fsd_id" in fs and "inpatient_data_id" in fs:
                if fs["fsd_id"] not in fsd_ids_loaded:
                    cursor.execute(
                        """INSERT OR REPLACE INTO IP_FLWSHT_REC (FSD_ID, INPATIENT_DATA_ID)
                           VALUES (?, ?)""",
                        (fs["fsd_id"], fs["inpatient_data_id"]),
                    )
                    fsd_ids_loaded.add(fs["fsd_id"])
            elif "flo_meas_id" in fs:
                cursor.execute(
                    """INSERT OR REPLACE INTO IP_FLWSHT_MEAS
                       (FLO_MEAS_ID, FSD_ID, RECORDED_TIME, MEAS_VALUE)
                       VALUES (?, ?, ?, ?)""",
                    (fs["flo_meas_id"], fs["fsd_id"], fs["recorded_time"], fs["meas_value"]),
                )

        # Load cultures
        for culture in self.cultures:
            cursor.execute(
                """INSERT OR REPLACE INTO ORDER_PROC (ORDER_PROC_ID, PAT_ID, PROC_NAME)
                   VALUES (?, ?, ?)""",
                (culture["order_proc_id"], culture["pat_id"], culture["proc_name"]),
            )
            cursor.execute(
                """INSERT OR REPLACE INTO ORDER_RESULTS
                   (ORDER_ID, ORDER_PROC_ID, SPECIMN_TAKEN_TIME, RESULT_TIME,
                    COMPONENT_ID, ORD_VALUE)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    culture["order_id"],
                    culture["order_proc_id"],
                    culture["specimn_taken_time"],
                    culture["result_time"],
                    culture["component_id"],
                    culture["ord_value"],
                ),
            )
            if culture["organism"]:
                cursor.execute(
                    """INSERT OR REPLACE INTO CLARITY_COMPONENT (COMPONENT_ID, NAME)
                       VALUES (?, ?)""",
                    (culture["component_id"], culture["organism"]),
                )

        # Load AU data - medication orders
        for order in self.medication_orders:
            cursor.execute(
                """INSERT OR REPLACE INTO ORDER_MED
                   (ORDER_MED_ID, PAT_ENC_CSN_ID, MEDICATION_ID, ORDERING_DATE,
                    ADMIN_ROUTE, DOSE, DOSE_UNIT, FREQUENCY)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order["order_med_id"],
                    order["pat_enc_csn_id"],
                    order["medication_id"],
                    order["ordering_date"],
                    order["admin_route"],
                    order["dose"],
                    order["dose_unit"],
                    order["frequency"],
                ),
            )

        # Load AU data - MAR administrations
        for admin in self.mar_administrations:
            cursor.execute(
                """INSERT OR REPLACE INTO MAR_ADMIN_INFO
                   (MAR_ADMIN_ID, ORDER_MED_ID, TAKEN_TIME, ACTION_NAME, DOSE_GIVEN, DOSE_UNIT)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    admin["mar_admin_id"],
                    admin["order_med_id"],
                    admin["taken_time"],
                    admin["action_name"],
                    admin["dose_given"],
                    admin["dose_unit"],
                ),
            )

        # Load AR data - cultures
        for culture in self.ar_cultures:
            cursor.execute(
                """INSERT OR REPLACE INTO CULTURE_RESULTS
                   (CULTURE_ID, PAT_ID, PAT_ENC_CSN_ID, SPECIMEN_TAKEN_TIME,
                    RESULT_TIME, SPECIMEN_TYPE, SPECIMEN_SOURCE, CULTURE_STATUS)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    culture["culture_id"],
                    culture["pat_id"],
                    culture["pat_enc_csn_id"],
                    culture["specimen_taken_time"],
                    culture["result_time"],
                    culture["specimen_type"],
                    culture["specimen_source"],
                    culture["culture_status"],
                ),
            )

        # Load AR data - organisms
        for org in self.ar_organisms:
            cursor.execute(
                """INSERT OR REPLACE INTO CULTURE_ORGANISM
                   (CULTURE_ORGANISM_ID, CULTURE_ID, ORGANISM_NAME, ORGANISM_GROUP,
                    CFU_COUNT, IS_PRIMARY)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    org["culture_organism_id"],
                    org["culture_id"],
                    org["organism_name"],
                    org["organism_group"],
                    org["cfu_count"],
                    org["is_primary"],
                ),
            )

        # Load AR data - susceptibilities
        for suscept in self.ar_susceptibilities:
            cursor.execute(
                """INSERT OR REPLACE INTO SUSCEPTIBILITY_RESULTS
                   (SUSCEPTIBILITY_ID, CULTURE_ORGANISM_ID, ANTIBIOTIC, ANTIBIOTIC_CODE,
                    MIC, MIC_UNITS, INTERPRETATION, METHOD)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    suscept["susceptibility_id"],
                    suscept["culture_organism_id"],
                    suscept["antibiotic"],
                    suscept["antibiotic_code"],
                    suscept["mic"],
                    suscept["mic_units"],
                    suscept["interpretation"],
                    suscept["method"],
                ),
            )

        conn.commit()
        conn.close()

        print(f"\nLoaded to database:")
        print(f"  - {len(self.patients)} patients")
        print(f"  - {len(self.encounters)} encounters")
        print(f"  - {len(self.notes)} notes")
        print(f"  - {len(self.cultures)} cultures (HAI)")
        print(f"  - {len(fsd_ids_loaded)} flowsheet records")
        print(f"  - {len(self.medication_orders)} medication orders (AU)")
        print(f"  - {len(self.mar_administrations)} MAR administrations (AU)")
        print(f"  - {len(self.ar_cultures)} cultures (AR)")
        print(f"  - {len(self.ar_organisms)} organisms (AR)")
        print(f"  - {len(self.ar_susceptibilities)} susceptibilities (AR)")


def main():
    parser = argparse.ArgumentParser(
        description="Generate mock Clarity data for NHSN reporting"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--patients",
        type=int,
        default=50,
        help="Number of random patients to generate (default: 50)",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="Months of historical data (default: 3)",
    )
    parser.add_argument(
        "--all-scenarios",
        action="store_true",
        help="Generate one of each CLABSI scenario type",
    )
    parser.add_argument(
        "--scenarios-only",
        action="store_true",
        help="Only generate scenarios, no random patients",
    )
    parser.add_argument(
        "--au-ar",
        action="store_true",
        help="Generate AU (antibiotic usage) and AR (antimicrobial resistance) data",
    )
    parser.add_argument(
        "--au-encounters",
        type=int,
        default=50,
        help="Number of encounters with AU data (default: 50)",
    )
    parser.add_argument(
        "--ar-encounters",
        type=int,
        default=30,
        help="Number of encounters with AR data (default: 30)",
    )

    args = parser.parse_args()

    print(f"Mock Clarity Data Generator")
    print(f"=" * 50)
    print(f"Database: {args.db_path}")

    generator = MockClarityGenerator(args.db_path)
    generator.initialize_database()
    generator.generate_providers()

    if not args.scenarios_only:
        print(f"\nGenerating {args.patients} random patients over {args.months} months...")
        generator.generate_random_patients(args.patients, args.months)

    if args.all_scenarios or args.scenarios_only:
        print(f"\nGenerating CLABSI test scenarios...")
        scenarios = generator.generate_all_scenarios()
        print(f"\nScenario Summary:")
        for s in scenarios:
            print(f"  - {s['scenario']}: {s['patient_mrn']} ({s['expected']})")

    # Generate AU/AR data if requested
    if args.au_ar:
        generator.generate_au_ar_data(
            months=args.months,
            encounters_with_au=args.au_encounters,
            encounters_with_ar=args.ar_encounters,
        )

    generator.load_to_database()
    print(f"\nDone! Database ready at: {args.db_path}")


if __name__ == "__main__":
    main()
