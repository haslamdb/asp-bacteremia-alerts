"""NHSN criteria reference data and constants.

This module contains the authoritative lists and criteria from the NHSN
Patient Safety Component Manual. These should be updated annually when
NHSN publishes new guidelines.

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 4
https://www.cdc.gov/nhsn/pdfs/pscmanual/pcsmanual_current.pdf
"""

from datetime import datetime, timedelta

# =============================================================================
# NHSN Version and Update Tracking
# =============================================================================

NHSN_MANUAL_VERSION = "2024"
NHSN_MANUAL_EFFECTIVE_DATE = "2024-01-01"
LAST_UPDATED = "2025-01-18"


# =============================================================================
# CLABSI Basic Eligibility Criteria
# =============================================================================

# Minimum days central line must be in place for CLABSI eligibility
# "Central line must be in place for >2 calendar days"
MIN_LINE_DAYS = 2

# Days after line removal that BSI can still be attributed
# "on the day of or the day after the device is removed"
POST_REMOVAL_ATTRIBUTION_DAYS = 1

# Minimum patient days for HAI attribution (not present on admission)
# "Infection window period begins on day 3"
MIN_PATIENT_DAYS_FOR_HAI = 3

# Days for commensal matching culture window
# "Two positive blood cultures drawn on separate days"
COMMENSAL_MATCHING_CULTURE_WINDOW_DAYS = 2


# =============================================================================
# Common Commensal Organisms (NHSN Table 3)
#
# These organisms require TWO positive cultures from separate blood draws
# on separate days to meet CLABSI criteria.
# =============================================================================

COMMON_COMMENSALS = {
    # Coagulase-negative staphylococci (group)
    "coagulase-negative staphylococci",
    "staphylococcus epidermidis",
    "staphylococcus hominis",
    "staphylococcus haemolyticus",
    "staphylococcus capitis",
    "staphylococcus warneri",
    "staphylococcus saprophyticus",
    "staphylococcus lugdunensis",  # Note: some consider pathogenic, but NHSN lists as commensal

    # Other skin flora
    "corynebacterium species",
    "corynebacterium",
    "diphtheroids",
    "micrococcus species",
    "micrococcus",

    # Bacillus (not anthracis)
    "bacillus species",
    "bacillus",
    "bacillus cereus",
    "bacillus subtilis",

    # Propionibacterium
    "propionibacterium acnes",
    "cutibacterium acnes",  # Renamed from P. acnes
    "propionibacterium species",

    # Viridans group streptococci
    "viridans group streptococci",
    "viridans streptococci",
    "streptococcus viridans",
    "alpha-hemolytic streptococcus",

    # Aerococcus
    "aerococcus species",
    "aerococcus",
    "aerococcus viridans",
    "aerococcus urinae",

    # Rhodococcus
    "rhodococcus species",
    "rhodococcus",
}


def is_commensal_organism(organism: str) -> bool:
    """Check if an organism is on the NHSN common commensal list.

    Args:
        organism: Organism name from culture result

    Returns:
        True if organism is a common commensal requiring 2 cultures
    """
    if not organism:
        return False
    organism_lower = organism.lower().strip()

    # Direct match
    if organism_lower in COMMON_COMMENSALS:
        return True

    # Partial match for variations
    for commensal in COMMON_COMMENSALS:
        if commensal in organism_lower or organism_lower in commensal:
            return True

    # Check for CoNS abbreviation
    if "cons" in organism_lower or "coag neg" in organism_lower:
        return True

    return False


# =============================================================================
# MBI-LCBI Eligible Organisms (NHSN Table 2)
#
# These are intestinal organisms that can cause MBI-LCBI in eligible
# patients (allogeneic HSCT or neutropenic with mucosal barrier injury).
# =============================================================================

MBI_LCBI_ORGANISMS = {
    # Bacteroides group
    "bacteroides",
    "bacteroides fragilis",
    "bacteroides distasonis",
    "bacteroides ovatus",
    "bacteroides thetaiotaomicron",
    "bacteroides uniformis",
    "bacteroides vulgatus",

    # Candida species
    "candida",
    "candida albicans",
    "candida glabrata",
    "candida krusei",
    "candida parapsilosis",
    "candida tropicalis",
    "candida auris",

    # Clostridium species
    "clostridium",
    "clostridium perfringens",
    "clostridium difficile",
    "clostridioides difficile",
    "clostridium species",

    # Enterococcus
    "enterococcus",
    "enterococcus faecalis",
    "enterococcus faecium",
    "vancomycin-resistant enterococcus",
    "vre",

    # Fusobacterium
    "fusobacterium",
    "fusobacterium nucleatum",
    "fusobacterium species",

    # Peptostreptococcus
    "peptostreptococcus",
    "peptostreptococcus species",

    # Prevotella
    "prevotella",
    "prevotella species",

    # Veillonella
    "veillonella",
    "veillonella species",

    # Enterobacteriaceae / Enterobacterales
    "enterobacter",
    "enterobacter cloacae",
    "enterobacter aerogenes",
    "escherichia coli",
    "e. coli",
    "klebsiella",
    "klebsiella pneumoniae",
    "klebsiella oxytoca",
    "proteus",
    "proteus mirabilis",
    "proteus vulgaris",
    "serratia",
    "serratia marcescens",
    "citrobacter",
    "citrobacter freundii",
    "citrobacter koseri",

    # Viridans group streptococci (oral flora - mucosal origin)
    "streptococcus mitis",
    "streptococcus oralis",
    "streptococcus salivarius",
    "streptococcus sanguinis",
    "streptococcus mutans",
    "streptococcus gordonii",
    "streptococcus parasanguinis",
}


def is_mbi_eligible_organism(organism: str) -> bool:
    """Check if organism is on MBI-LCBI eligible organism list.

    Args:
        organism: Organism name from culture result

    Returns:
        True if organism can cause MBI-LCBI in eligible patients
    """
    if not organism:
        return False
    organism_lower = organism.lower().strip()

    # Direct match
    if organism_lower in MBI_LCBI_ORGANISMS:
        return True

    # Partial match
    for mbi_org in MBI_LCBI_ORGANISMS:
        if mbi_org in organism_lower or organism_lower in mbi_org:
            return True

    return False


# =============================================================================
# MBI-LCBI Patient Eligibility Criteria
# =============================================================================

# Allogeneic HSCT within this many days
ALLO_HSCT_MBI_WINDOW_DAYS = 365

# ANC threshold for neutropenia
NEUTROPENIA_ANC_THRESHOLD = 500  # cells/microL


# =============================================================================
# Secondary BSI Attribution Sites
#
# These are infection sites that can be primary sources of bacteremia.
# If the same organism is isolated from one of these sites AND the blood,
# the BSI is secondary (not a CLABSI).
# =============================================================================

SECONDARY_BSI_SITES = {
    # Lower respiratory
    "pneumonia",
    "ventilator-associated pneumonia",
    "vap",
    "lung infection",
    "respiratory infection",

    # Urinary tract
    "urinary tract infection",
    "uti",
    "catheter-associated uti",
    "cauti",
    "pyelonephritis",

    # Intra-abdominal
    "intra-abdominal infection",
    "abdominal abscess",
    "peritonitis",
    "cholangitis",
    "cholecystitis",
    "appendicitis",
    "diverticulitis",

    # Skin and soft tissue
    "skin infection",
    "soft tissue infection",
    "ssti",
    "cellulitis",
    "wound infection",
    "surgical site infection",
    "ssi",
    "abscess",
    "necrotizing fasciitis",

    # Bone/joint
    "osteomyelitis",
    "septic arthritis",
    "bone infection",
    "joint infection",

    # Cardiovascular
    "endocarditis",
    "infective endocarditis",
    "vascular graft infection",

    # CNS
    "meningitis",
    "brain abscess",
    "ventriculitis",

    # Other
    "sinusitis",
    "mastoiditis",
    "mediastinitis",
}


# =============================================================================
# Location Types
# =============================================================================

ICU_LOCATION_TYPES = {
    "icu",
    "picu",
    "nicu",
    "cicu",
    "micu",
    "sicu",
    "cvicu",
    "neuro icu",
    "burn icu",
}


# =============================================================================
# LCBI Criterion Pathogen Groups
#
# NHSN has 3 LCBI criteria. Criterion 1 uses "recognized pathogens."
# =============================================================================

# Organisms that meet LCBI Criterion 1 with single positive culture
# (recognized pathogens - single culture sufficient)
RECOGNIZED_PATHOGENS = {
    "staphylococcus aureus",
    "streptococcus pneumoniae",
    "streptococcus pyogenes",
    "streptococcus agalactiae",
    "listeria monocytogenes",
    "haemophilus influenzae",
    "neisseria meningitidis",

    # Gram negatives
    "escherichia coli",
    "klebsiella pneumoniae",
    "klebsiella oxytoca",
    "pseudomonas aeruginosa",
    "acinetobacter baumannii",
    "enterobacter cloacae",
    "serratia marcescens",
    "proteus mirabilis",
    "salmonella",
    "stenotrophomonas maltophilia",
    "burkholderia cepacia",

    # Fungi
    "candida albicans",
    "candida glabrata",
    "candida krusei",
    "candida parapsilosis",
    "candida tropicalis",
    "candida auris",
    "aspergillus",
    "cryptococcus",
}


def is_recognized_pathogen(organism: str) -> bool:
    """Check if organism is a recognized pathogen (single culture sufficient).

    Args:
        organism: Organism name from culture result

    Returns:
        True if organism is a recognized pathogen
    """
    if not organism:
        return False
    organism_lower = organism.lower().strip()

    # Direct match
    if organism_lower in RECOGNIZED_PATHOGENS:
        return True

    # Partial match
    for pathogen in RECOGNIZED_PATHOGENS:
        if pathogen in organism_lower or organism_lower in pathogen:
            return True

    return False


# =============================================================================
# Repeat Infection Timeframe (RIT)
#
# Once an NHSN event is reported, a new event with the same organism
# cannot be reported within the RIT.
# =============================================================================

REPEAT_INFECTION_TIMEFRAME_DAYS = 14


# =============================================================================
# Helper Functions
# =============================================================================

def get_lcbi_criterion(organism: str, has_second_culture: bool) -> int | None:
    """Determine which LCBI criterion is met.

    LCBI Criterion 1: Recognized pathogen (single culture)
    LCBI Criterion 2: Common commensal + 2 cultures + symptoms
    LCBI Criterion 3: Common commensal + 2 cultures + antimicrobial started

    Args:
        organism: Organism name
        has_second_culture: Whether a second matching culture exists

    Returns:
        Criterion number (1, 2, or 3) or None if not met
    """
    if is_recognized_pathogen(organism):
        return 1

    if is_commensal_organism(organism):
        if has_second_culture:
            return 2  # Could be 2 or 3, needs symptom check
        return None  # Single commensal = not LCBI

    # Other organisms - default to criterion 1 if not clearly commensal
    return 1


# =============================================================================
# SSI (Surgical Site Infection) Criteria
# =============================================================================

# SSI Surveillance Periods
SSI_SURVEILLANCE_DAYS_STANDARD = 30
SSI_SURVEILLANCE_DAYS_IMPLANT = 90

# NHSN Operative Procedure Categories
# Reference: NHSN Operative Procedure Category Mapping (2024)
NHSN_OPERATIVE_CATEGORIES = {
    # Abdominal
    "AAA": "Abdominal aortic aneurysm repair",
    "APPY": "Appendectomy",
    "BILI": "Bile duct, liver, or pancreatic surgery",
    "CEA": "Carotid endarterectomy",
    "CHOL": "Gallbladder surgery",
    "COLO": "Colon surgery",
    "GAST": "Gastric surgery",
    "HER": "Herniorrhaphy",
    "REC": "Rectal surgery",
    "SB": "Small bowel surgery",
    "SPLE": "Spleen surgery",
    "XLAP": "Exploratory laparotomy",

    # Cardiac
    "CABG": "Coronary artery bypass graft",
    "CARD": "Cardiac surgery",
    "CBGB": "CABG with both chest and donor incisions",
    "CBGC": "CABG with chest incision only",
    "PACE": "Pacemaker surgery",
    "VSHU": "Ventricular shunt",

    # Thoracic
    "BRST": "Breast surgery",
    "LUNG": "Lung surgery",
    "THOR": "Thoracic surgery",

    # Orthopedic
    "FX": "Open reduction of fracture",
    "FUSN": "Spinal fusion",
    "HPRO": "Hip prosthesis",
    "KPRO": "Knee prosthesis",
    "LAM": "Laminectomy",
    "PRST": "Prosthetic joint replacement (other)",

    # Neurosurgery
    "CRAN": "Craniotomy",

    # Vascular
    "AMP": "Limb amputation",
    "PVBY": "Peripheral vascular bypass surgery",

    # Genitourinary
    "HYS": "Abdominal hysterectomy",
    "CSEC": "Cesarean section",
    "KTP": "Kidney transplant",
    "NEPH": "Kidney surgery",
    "OVRY": "Ovarian surgery",
    "PROS": "Prostate surgery",
    "VHYS": "Vaginal hysterectomy",

    # Other
    "LTP": "Liver transplant",
    "NECK": "Neck surgery",
    "SKLP": "Skin graft",
    "THYP": "Thyroid and/or parathyroid surgery",
}

# Procedures that include an implant (90-day surveillance)
NHSN_IMPLANT_PROCEDURES = {
    "HPRO",   # Hip prosthesis
    "KPRO",   # Knee prosthesis
    "PRST",   # Other prosthetic joint replacement
    "FUSN",   # Spinal fusion (if hardware used)
    "CABG",   # CABG (sternotomy)
    "CBGB",   # CABG with both incisions
    "CBGC",   # CABG chest only
    "CARD",   # Cardiac surgery (often involves implants)
    "PACE",   # Pacemaker
    "VSHU",   # Ventricular shunt
    "BRST",   # Breast surgery (if implant reconstruction)
    "HER",    # Herniorrhaphy (mesh)
}

# Wound Classification
WOUND_CLASSES = {
    1: {
        "name": "Clean",
        "description": "Uninfected operative wound in which no inflammation is encountered "
                      "and the respiratory, alimentary, genital, or uninfected urinary tracts "
                      "are not entered."
    },
    2: {
        "name": "Clean-Contaminated",
        "description": "Operative wound in which the respiratory, alimentary, genital, "
                      "or urinary tract is entered under controlled conditions without "
                      "unusual contamination."
    },
    3: {
        "name": "Contaminated",
        "description": "Open, fresh accidental wounds. Operations with major breaks in "
                      "sterile technique or gross spillage from the GI tract."
    },
    4: {
        "name": "Dirty-Infected",
        "description": "Old traumatic wounds with retained devitalized tissue, or involving "
                      "existing clinical infection or perforated viscera."
    },
}

# ASA Physical Status Classification
ASA_SCORES = {
    1: "Normal healthy patient",
    2: "Patient with mild systemic disease",
    3: "Patient with severe systemic disease",
    4: "Patient with severe systemic disease that is a constant threat to life",
    5: "Moribund patient not expected to survive without the operation",
    6: "Declared brain-dead patient whose organs are being removed for donor purposes",
}

# SSI Types
SSI_TYPES = {
    "superficial_incisional": {
        "name": "Superficial Incisional SSI",
        "code": "SIP",
        "description": "Infection involving only skin and subcutaneous tissue of the incision",
    },
    "deep_incisional": {
        "name": "Deep Incisional SSI",
        "code": "DIP",
        "description": "Infection involving deep soft tissues (fascia and muscle) of the incision",
    },
    "organ_space": {
        "name": "Organ/Space SSI",
        "code": "O/S",
        "description": "Infection involving any part of the body deeper than the fascial/muscle layers "
                      "that is opened or manipulated during the operative procedure",
    },
}

# SSI keywords for note scanning (detection triggers)
SSI_DETECTION_KEYWORDS = {
    # General wound infection terms
    "wound infection",
    "surgical site infection",
    "ssi",
    "post-operative infection",
    "postoperative infection",
    "incisional infection",

    # Superficial indicators
    "wound dehiscence",
    "wound breakdown",
    "incision opened",
    "wound drainage",
    "purulent drainage",
    "wound erythema",
    "cellulitis around incision",
    "stitch abscess",
    "suture abscess",

    # Deep indicators
    "fascial dehiscence",
    "fascial disruption",
    "deep wound infection",
    "wound hematoma infected",
    "seroma infected",

    # Organ/space indicators
    "intra-abdominal abscess",
    "pelvic abscess",
    "anastomotic leak",
    "mediastinitis",
    "osteomyelitis",
    "empyema",
    "meningitis",
    "organ space infection",
    "deep abscess",

    # Treatment indicators
    "wound vac",
    "negative pressure wound therapy",
    "i&d",
    "incision and drainage",
    "wound washout",
    "reoperation for infection",
    "return to or for infection",
}

# Organ/Space specific sites (for NHSN reporting)
SSI_ORGAN_SPACE_SITES = {
    "BONE": "Osteomyelitis",
    "BRST": "Breast abscess or mastitis",
    "CARD": "Myocarditis or pericarditis",
    "DISC": "Disc space infection",
    "EAR": "Ear, mastoid",
    "EMET": "Endometritis",
    "ENDO": "Endocarditis",
    "EYE": "Eye (excluding conjunctivitis)",
    "GIT": "Gastrointestinal tract",
    "IAB": "Intra-abdominal, not specified elsewhere",
    "IC": "Intracranial (brain abscess, subdural/epidural infection)",
    "JNT": "Joint or bursa",
    "LUNG": "Other infections of the lower respiratory tract",
    "MED": "Mediastinitis",
    "MEN": "Meningitis or ventriculitis",
    "ORAL": "Oral cavity (mouth, tongue, or gums)",
    "OREP": "Other male or female reproductive tract infection",
    "OUTI": "Other infections of the urinary tract",
    "PJI": "Periprosthetic joint infection",
    "SA": "Spinal abscess without meningitis",
    "SINU": "Sinusitis",
    "UR": "Upper respiratory tract infection",
    "VASC": "Arterial or venous infection",
    "VCUF": "Vaginal cuff infection",
}


def is_nhsn_operative_procedure(category: str) -> bool:
    """Check if a procedure category is an NHSN operative procedure.

    Args:
        category: NHSN procedure category code (e.g., "COLO", "HPRO")

    Returns:
        True if it's a valid NHSN operative procedure category
    """
    return category.upper() in NHSN_OPERATIVE_CATEGORIES


def is_implant_procedure(category: str) -> bool:
    """Check if a procedure category typically involves an implant.

    Args:
        category: NHSN procedure category code

    Returns:
        True if procedure typically involves implant (90-day surveillance)
    """
    return category.upper() in NHSN_IMPLANT_PROCEDURES


def get_surveillance_window(category: str, has_implant: bool = False) -> int:
    """Get surveillance window in days for a procedure category.

    Args:
        category: NHSN procedure category code
        has_implant: Override to indicate implant was used

    Returns:
        Surveillance window in days (30 or 90)
    """
    if has_implant or is_implant_procedure(category):
        return SSI_SURVEILLANCE_DAYS_IMPLANT
    return SSI_SURVEILLANCE_DAYS_STANDARD


def get_wound_class_name(wound_class: int) -> str:
    """Get the name for a wound classification number.

    Args:
        wound_class: Integer 1-4

    Returns:
        Wound class name (e.g., "Clean", "Clean-Contaminated")
    """
    if wound_class in WOUND_CLASSES:
        return WOUND_CLASSES[wound_class]["name"]
    return f"Unknown ({wound_class})"


def get_ssi_type_name(ssi_type: str) -> str:
    """Get the display name for an SSI type.

    Args:
        ssi_type: SSI type code (superficial_incisional, deep_incisional, organ_space)

    Returns:
        Display name
    """
    if ssi_type in SSI_TYPES:
        return SSI_TYPES[ssi_type]["name"]
    return ssi_type.replace("_", " ").title()


# =============================================================================
# VAE (Ventilator-Associated Event) Criteria
# =============================================================================

# Minimum mechanical ventilation days for VAE eligibility
# "Patient must be on mechanical ventilation for ≥2 calendar days"
VAE_MIN_VENT_DAYS = 2

# Days of stable/improving ventilator settings required before worsening
# "≥2 calendar days of stable or decreasing daily minimum FiO2 or PEEP values"
VAE_BASELINE_PERIOD_DAYS = 2

# Days of sustained worsening required for VAC
# "≥2 calendar days of increased daily minimum FiO2 or PEEP"
VAE_WORSENING_PERIOD_DAYS = 2

# FiO2 increase threshold (percentage points)
# "Increase in daily minimum FiO2 of ≥20 percentage points over the daily minimum FiO2 of the first day of the baseline period"
VAE_FIO2_INCREASE_THRESHOLD = 20.0

# PEEP increase threshold (cmH2O)
# "Increase in daily minimum PEEP of ≥3 cmH2O over the daily minimum PEEP of the first day of the baseline period"
VAE_PEEP_INCREASE_THRESHOLD = 3.0

# VAC onset occurs on the first day of sustained worsening after the baseline period
# This is calendar day 3 or later of mechanical ventilation (day 1 + 2 baseline + worsening)

# =============================================================================
# IVAC (Infection-Related Ventilator-Associated Complication) Criteria
# =============================================================================

# Temperature thresholds for IVAC
# "Temperature >38°C or <36°C"
IVAC_FEVER_THRESHOLD_CELSIUS = 38.0
IVAC_HYPOTHERMIA_THRESHOLD_CELSIUS = 36.0

# WBC thresholds for IVAC
# "WBC count ≥12,000 cells/mm³ or ≤4,000 cells/mm³"
IVAC_LEUKOCYTOSIS_THRESHOLD = 12000
IVAC_LEUKOPENIA_THRESHOLD = 4000

# Antimicrobial duration requirement for IVAC
# "New antimicrobial agent(s) started and continued for ≥4 calendar days"
IVAC_ANTIMICROBIAL_MIN_DAYS = 4

# Window for antimicrobial start relative to worsening
# "Started on the day of or within 2 days before or after the onset of worsening oxygenation"
IVAC_ANTIMICROBIAL_WINDOW_DAYS_BEFORE = 2
IVAC_ANTIMICROBIAL_WINDOW_DAYS_AFTER = 2

# Qualifying antimicrobial classes for IVAC/VAP
QUALIFYING_ANTIMICROBIALS = {
    # Beta-lactams
    "piperacillin-tazobactam", "piperacillin/tazobactam", "zosyn",
    "ampicillin-sulbactam", "ampicillin/sulbactam", "unasyn",
    "amoxicillin-clavulanate", "amoxicillin/clavulanate", "augmentin",
    "ticarcillin-clavulanate", "ticarcillin/clavulanate", "timentin",
    "ceftriaxone", "rocephin",
    "ceftazidime", "fortaz", "tazicef",
    "cefepime", "maxipime",
    "ceftazidime-avibactam", "ceftazidime/avibactam", "avycaz",
    "ceftolozane-tazobactam", "ceftolozane/tazobactam", "zerbaxa",
    "meropenem", "merrem",
    "imipenem-cilastatin", "imipenem/cilastatin", "primaxin",
    "ertapenem", "invanz",
    "doripenem", "doribax",
    "aztreonam", "azactam",

    # Fluoroquinolones
    "ciprofloxacin", "cipro",
    "levofloxacin", "levaquin",
    "moxifloxacin", "avelox",

    # Aminoglycosides
    "gentamicin", "garamycin",
    "tobramycin", "tobi", "nebcin",
    "amikacin", "amikin",

    # Glycopeptides
    "vancomycin", "vancocin",
    "telavancin", "vibativ",
    "dalbavancin", "dalvance",
    "oritavancin", "orbactiv",

    # Oxazolidinones
    "linezolid", "zyvox",
    "tedizolid", "sivextro",

    # Lipopeptides
    "daptomycin", "cubicin",

    # Polymyxins
    "colistin", "colistimethate", "coly-mycin",
    "polymyxin b",

    # Tetracyclines
    "tigecycline", "tygacil",

    # Other
    "metronidazole", "flagyl",
    "clindamycin", "cleocin",
    "trimethoprim-sulfamethoxazole", "tmp-smx", "bactrim", "septra",

    # Antifungals (for VAP evaluation)
    "fluconazole", "diflucan",
    "voriconazole", "vfend",
    "posaconazole", "noxafil",
    "isavuconazole", "cresemba",
    "micafungin", "mycamine",
    "caspofungin", "cancidas",
    "anidulafungin", "eraxis",
    "amphotericin b", "ambisome", "abelcet",
}


def is_qualifying_antimicrobial(drug_name: str) -> bool:
    """Check if a drug is a qualifying antimicrobial for IVAC/VAP.

    Args:
        drug_name: Drug name from medication list

    Returns:
        True if drug qualifies for IVAC criteria
    """
    if not drug_name:
        return False
    drug_lower = drug_name.lower().strip()

    # Direct match
    if drug_lower in QUALIFYING_ANTIMICROBIALS:
        return True

    # Partial match for variations
    for antimicrobial in QUALIFYING_ANTIMICROBIALS:
        if antimicrobial in drug_lower or drug_lower in antimicrobial:
            return True

    return False


# =============================================================================
# VAP (Ventilator-Associated Pneumonia) Criteria
# =============================================================================

# Quantitative culture thresholds for Probable VAP
# Different thresholds based on specimen type
VAP_CULTURE_THRESHOLDS = {
    "bal": 10000,           # Bronchoalveolar lavage: ≥10^4 CFU/mL
    "bronchoalveolar lavage": 10000,
    "mini-bal": 10000,
    "protected brush": 1000,  # Protected specimen brush: ≥10^3 CFU/mL
    "psb": 1000,
    "eta": 1000000,         # Endotracheal aspirate: ≥10^6 CFU/mL
    "endotracheal aspirate": 1000000,
    "tracheal aspirate": 1000000,
    "sputum": 1000000,      # Sputum treated same as ETA
    "lung tissue": 10000,   # Lung tissue: ≥10^4 CFU/g
}


def get_vap_culture_threshold(specimen_type: str) -> int | None:
    """Get the quantitative culture threshold for a specimen type.

    Args:
        specimen_type: Type of respiratory specimen

    Returns:
        CFU/mL threshold, or None if specimen type not recognized
    """
    if not specimen_type:
        return None
    specimen_lower = specimen_type.lower().strip()

    # Direct match
    if specimen_lower in VAP_CULTURE_THRESHOLDS:
        return VAP_CULTURE_THRESHOLDS[specimen_lower]

    # Partial match
    for spec_type, threshold in VAP_CULTURE_THRESHOLDS.items():
        if spec_type in specimen_lower or specimen_lower in spec_type:
            return threshold

    return None


def meets_vap_quantitative_threshold(specimen_type: str, colony_count: int) -> bool:
    """Check if a culture meets the quantitative threshold for Probable VAP.

    Args:
        specimen_type: Type of respiratory specimen
        colony_count: Colony count in CFU/mL

    Returns:
        True if culture meets threshold for specimen type
    """
    threshold = get_vap_culture_threshold(specimen_type)
    if threshold is None:
        return False
    return colony_count >= threshold


# Purulent secretions criteria for VAP
# "Secretions from lungs, bronchi, or trachea that contain ≥25 neutrophils
# and ≤10 squamous epithelial cells per low power field"
VAP_PURULENT_PMN_THRESHOLD = 25
VAP_PURULENT_EPITHELIAL_MAX = 10

# Positive respiratory culture organisms for Possible VAP
# Any organism counts for Possible VAP (qualitative positive)
# Quantitative threshold only matters for Probable VAP


# =============================================================================
# VAE LOINC Codes
# =============================================================================

# LOINC codes for ventilator parameters
VAE_LOINC_CODES = {
    "fio2": [
        "3150-0",     # Inhaled oxygen concentration
        "19994-3",    # Oxygen/Total gas setting Ventilator
    ],
    "peep": [
        "76530-5",    # PEEP Respiratory system by Ventilator
        "20077-4",    # Positive end expiratory pressure setting Ventilator
    ],
    "mechanical_ventilation": [
        "19835-8",    # Ventilator mode
        "60956-0",    # Mechanical ventilation status
    ],
}


# =============================================================================
# VAE Helper Functions
# =============================================================================

def calculate_ventilator_days(intubation_date: datetime, reference_date: datetime) -> int:
    """Calculate ventilator days at a reference date.

    Day 1 is the day of intubation.

    Args:
        intubation_date: Date/time of intubation
        reference_date: Date to calculate days at

    Returns:
        Number of ventilator days (1-based)
    """
    # Normalize to date for calendar day calculation
    intub_date = intubation_date.date() if hasattr(intubation_date, 'date') else intubation_date
    ref_date = reference_date.date() if hasattr(reference_date, 'date') else reference_date
    delta = ref_date - intub_date
    return delta.days + 1  # Day 1 is intubation day


def is_vae_eligible(ventilator_days: int) -> bool:
    """Check if patient meets minimum ventilator days for VAE eligibility.

    Args:
        ventilator_days: Number of days on mechanical ventilation

    Returns:
        True if patient meets minimum ventilator days requirement
    """
    return ventilator_days >= VAE_MIN_VENT_DAYS


# =============================================================================
# CAUTI (Catheter-Associated Urinary Tract Infection) Criteria
# =============================================================================

# Minimum days catheter must be in place for CAUTI eligibility
# "Indwelling urinary catheter in place for >2 calendar days"
CAUTI_MIN_CATHETER_DAYS = 2

# Days after catheter removal that UTI can still be attributed
# "on the day of or the day after the device is removed"
CAUTI_POST_REMOVAL_WINDOW_DAYS = 1

# Minimum CFU/mL threshold for CAUTI
# ">=10^5 CFU/mL with no more than 2 species of microorganisms"
CAUTI_MIN_CFU_ML = 100000  # 10^5

# Maximum number of organisms for a valid CAUTI culture
# More than 2 organisms is considered mixed flora
CAUTI_MAX_ORGANISMS = 2

# Fever threshold for CAUTI
CAUTI_FEVER_THRESHOLD_CELSIUS = 38.0

# Age threshold for fever rule
# Patients >65 years: fever alone requires catheter >2 days
# Patients <=65 years: fever can be used regardless of catheter duration
CAUTI_FEVER_AGE_THRESHOLD = 65


# Urinary catheter SNOMED codes
URINARY_CATHETER_CODES = {
    "20568009",    # Urinary catheter (general)
    "68135008",    # Foley catheter
    "286558007",   # Indwelling urinary catheter
    "448130004",   # Suprapubic catheter
    "61088005",    # Urethral catheter
}

# Urinary catheter insertion site SNOMED codes
URINARY_CATHETER_SITES = {
    "87953007",    # Urinary bladder
    "13648007",    # Urinary bladder structure
    "64033007",    # Urethra
}


# Organisms excluded from CAUTI (yeasts/fungi are excluded)
CAUTI_EXCLUDED_ORGANISMS = {
    "candida",
    "candida albicans",
    "candida glabrata",
    "candida krusei",
    "candida parapsilosis",
    "candida tropicalis",
    "candida auris",
    "yeast",
    "fungus",
    "fungi",
}


# Common uropathogens (for reference, not exclusive)
COMMON_UROPATHOGENS = {
    "escherichia coli",
    "e. coli",
    "klebsiella pneumoniae",
    "klebsiella oxytoca",
    "proteus mirabilis",
    "proteus vulgaris",
    "pseudomonas aeruginosa",
    "enterococcus faecalis",
    "enterococcus faecium",
    "enterobacter cloacae",
    "enterobacter aerogenes",
    "serratia marcescens",
    "citrobacter freundii",
    "morganella morganii",
    "providencia stuartii",
    "staphylococcus aureus",
    "staphylococcus saprophyticus",
    "streptococcus agalactiae",
    "group b streptococcus",
}


def is_cauti_excluded_organism(organism: str) -> bool:
    """Check if an organism is excluded from CAUTI criteria.

    Yeasts and fungi are excluded from CAUTI - they should not be
    reported as CAUTI even if catheter and symptoms are present.

    Args:
        organism: Organism name from culture result

    Returns:
        True if organism is excluded from CAUTI reporting
    """
    if not organism:
        return False
    organism_lower = organism.lower().strip()

    # Direct match
    if organism_lower in CAUTI_EXCLUDED_ORGANISMS:
        return True

    # Partial match for variations
    for excluded in CAUTI_EXCLUDED_ORGANISMS:
        if excluded in organism_lower or organism_lower in excluded:
            return True

    return False


def is_valid_cauti_culture(organism_count: int, cfu_ml: int) -> bool:
    """Check if a urine culture meets CAUTI criteria.

    Args:
        organism_count: Number of distinct organisms in culture
        cfu_ml: Colony forming units per mL

    Returns:
        True if culture meets CAUTI threshold (>=10^5 CFU/mL, <=2 organisms)
    """
    if organism_count > CAUTI_MAX_ORGANISMS:
        return False  # Mixed flora - not valid for CAUTI
    if cfu_ml < CAUTI_MIN_CFU_ML:
        return False  # Below threshold
    return True


def is_cauti_fever_eligible(patient_age: int | None, catheter_days: int) -> bool:
    """Check if fever can be used as the sole symptom criterion for CAUTI.

    NHSN Rule:
    - Patient <=65 years: Fever can always be used alone
    - Patient >65 years: Fever alone only valid if catheter >2 days

    For patients >65 with catheter <=2 days, a non-fever symptom is required.

    Args:
        patient_age: Patient age in years (None treated as eligible)
        catheter_days: Number of days catheter has been in place

    Returns:
        True if fever alone is sufficient for symptom criterion
    """
    if patient_age is None:
        return True  # Default to eligible if age unknown

    if patient_age <= CAUTI_FEVER_AGE_THRESHOLD:
        return True  # Younger patients can always use fever

    # Older patients need catheter >2 days for fever to count alone
    return catheter_days > CAUTI_MIN_CATHETER_DAYS


def is_cauti_eligible(catheter_days: int) -> bool:
    """Check if patient meets minimum catheter days for CAUTI eligibility.

    Args:
        catheter_days: Number of days catheter has been in place

    Returns:
        True if patient meets minimum catheter days requirement (>2 days)
    """
    return catheter_days > CAUTI_MIN_CATHETER_DAYS


# =============================================================================
# CDI (Clostridioides difficile Infection) Criteria
# =============================================================================

# Timing thresholds for onset classification
# Healthcare-facility onset: specimen collected >3 days after admission
CDI_HO_MIN_DAYS = 4  # Day 4+ = healthcare-facility onset (>3 days)
CDI_CO_MAX_DAYS = 3  # Days 1-3 = community onset (≤3 days)

# Recurrence window thresholds
CDI_DUPLICATE_WINDOW_DAYS = 14  # ≤14 days = duplicate, not reported
CDI_RECURRENCE_MIN_DAYS = 15   # 15-56 days = recurrent
CDI_RECURRENCE_MAX_DAYS = 56   # >56 days = new incident

# CO-HCFA (Community-Onset Healthcare Facility-Associated) window
CDI_CO_HCFA_DISCHARGE_WINDOW_DAYS = 28  # 4 weeks for CO-HCFA

# Valid test types for CDI LabID Event (not antigen-only)
CDI_POSITIVE_TEST_TYPES = {
    "toxin_a",
    "toxin_b",
    "toxin_ab",
    "toxin_a_b",
    "pcr",
    "naat",
    "culture_toxigenic",
    "toxin_gene",
}

# Test types that do NOT qualify alone (antigen/GDH only)
CDI_ANTIGEN_ONLY_TESTS = {
    "gdh",
    "antigen",
    "eia_gdh",
    "glutamate_dehydrogenase",
}

# C. difficile LOINC codes for toxin/PCR tests
CDI_LOINC_CODES = {
    # Toxin tests
    "34713-8": "C. difficile toxin A",
    "34714-6": "C. difficile toxin B",
    "34712-0": "C. difficile toxin A+B",
    "562-9": "C. difficile toxin A+B",
    "6359-4": "C. difficile toxin",

    # PCR/NAAT tests
    "82197-9": "C. difficile toxin B gene (PCR)",
    "80685-5": "C. difficile toxin genes (NAAT)",
    "63588-5": "C. difficile toxin B gene (NAA)",
    "54067-4": "C. difficile toxin A gene (NAA)",

    # Culture
    "625-4": "C. difficile culture",
}

# LOINC codes that are antigen-only (do not qualify)
CDI_ANTIGEN_LOINC_CODES = {
    "76580-0": "C. difficile Ag (GDH)",
    "31369-5": "C. difficile Ag",
}

# CDI treatment medications
CDI_TREATMENT_MEDICATIONS = {
    # Oral vancomycin (primary treatment)
    "vancomycin",
    "vancomycin oral",
    "vancomycin po",

    # Fidaxomicin (preferred for recurrence)
    "fidaxomicin",
    "dificid",

    # Metronidazole (less preferred)
    "metronidazole",
    "flagyl",

    # Bezlotoxumab (monoclonal antibody for recurrence prevention)
    "bezlotoxumab",
    "zinplava",
}


def is_valid_cdi_test(test_type: str, result: str = "positive") -> bool:
    """Check if test qualifies for CDI LabID event.

    CDI requires positive toxin A/B test or toxin-producing organism
    detection (PCR, NAAT, toxigenic culture). Antigen-only tests (GDH)
    do NOT qualify.

    Args:
        test_type: Type of C. diff test performed
        result: Test result (only 'positive' qualifies)

    Returns:
        True if test type and result qualify for CDI LabID event
    """
    if not test_type:
        return False

    if result.lower() != "positive":
        return False

    test_lower = test_type.lower().strip()

    # Check if it's a valid test type
    if test_lower in CDI_POSITIVE_TEST_TYPES:
        return True

    # Check partial matches
    for valid_type in CDI_POSITIVE_TEST_TYPES:
        if valid_type in test_lower or test_lower in valid_type:
            return True

    # Check if it's antigen-only (disqualifies)
    for antigen_type in CDI_ANTIGEN_ONLY_TESTS:
        if antigen_type in test_lower:
            return False

    # Check for toxin or pcr keywords
    if "toxin" in test_lower and "antigen" not in test_lower:
        return True
    if "pcr" in test_lower or "naat" in test_lower:
        return True

    return False


def is_cdi_loinc_qualifying(loinc_code: str) -> bool:
    """Check if a LOINC code is a qualifying CDI test.

    Args:
        loinc_code: LOINC code for the test

    Returns:
        True if LOINC code is for a qualifying CDI test
    """
    if not loinc_code:
        return False

    # Check against qualifying codes
    if loinc_code in CDI_LOINC_CODES:
        return True

    # Check against antigen codes (not qualifying)
    if loinc_code in CDI_ANTIGEN_LOINC_CODES:
        return False

    return False


def get_cdi_onset_type(specimen_day: int) -> str:
    """Return onset type based on timing.

    NHSN Criteria:
    - Day 1-3 = Community Onset (CO)
    - Day 4+ = Healthcare-Facility Onset (HO)

    Args:
        specimen_day: Days since admission (day 1 = admission day)

    Returns:
        "healthcare_facility" or "community"
    """
    if specimen_day >= CDI_HO_MIN_DAYS:
        return "healthcare_facility"
    return "community"


def is_cdi_duplicate(days_since_last: int | None) -> bool:
    """Check if within 14-day duplicate window.

    ≤14 days since last CDI LabID event = duplicate, not reported.

    Args:
        days_since_last: Days since last CDI event (None if no prior)

    Returns:
        True if this is a duplicate (within 14 days of prior)
    """
    if days_since_last is None:
        return False
    return days_since_last <= CDI_DUPLICATE_WINDOW_DAYS


def is_cdi_recurrent(days_since_last: int | None) -> bool:
    """Check if 15-56 days (recurrence window).

    15-56 days since last CDI LabID event = recurrent.

    Args:
        days_since_last: Days since last CDI event (None if no prior)

    Returns:
        True if this is a recurrent event
    """
    if days_since_last is None:
        return False
    return CDI_RECURRENCE_MIN_DAYS <= days_since_last <= CDI_RECURRENCE_MAX_DAYS


def is_cdi_incident(days_since_last: int | None) -> bool:
    """Check if this is an incident (new) CDI event.

    First event OR >56 days since last = new incident.

    Args:
        days_since_last: Days since last CDI event (None if no prior)

    Returns:
        True if this is an incident (new) event
    """
    if days_since_last is None:
        return True  # No prior = incident
    return days_since_last > CDI_RECURRENCE_MAX_DAYS


def is_cdi_co_hcfa(onset_type: str, days_since_discharge: int | None) -> bool:
    """Check if CO-CDI qualifies as CO-HCFA.

    Community-Onset Healthcare Facility-Associated:
    - Must be Community Onset (≤3 days)
    - Patient discharged from any inpatient facility within prior 4 weeks

    Args:
        onset_type: "community" or "healthcare_facility"
        days_since_discharge: Days since last inpatient discharge

    Returns:
        True if this is CO-HCFA
    """
    if onset_type != "community":
        return False

    if days_since_discharge is None:
        return False

    return days_since_discharge <= CDI_CO_HCFA_DISCHARGE_WINDOW_DAYS


def calculate_specimen_day(admission_date: datetime, test_date: datetime) -> int:
    """Calculate specimen day (days since admission).

    Day 1 = admission date.

    Args:
        admission_date: Date of admission
        test_date: Date specimen was collected

    Returns:
        Specimen day (1-based)
    """
    # Normalize to date for calendar day calculation
    admit_d = admission_date.date() if hasattr(admission_date, 'date') else admission_date
    test_d = test_date.date() if hasattr(test_date, 'date') else test_date
    delta = test_d - admit_d
    return delta.days + 1  # Day 1 is admission day


def get_cdi_recurrence_status(days_since_last: int | None) -> str:
    """Get the recurrence status string.

    Args:
        days_since_last: Days since last CDI event

    Returns:
        "incident", "recurrent", or "duplicate"
    """
    if is_cdi_duplicate(days_since_last):
        return "duplicate"
    if is_cdi_recurrent(days_since_last):
        return "recurrent"
    return "incident"


def is_cdi_treatment(medication_name: str) -> bool:
    """Check if a medication is a CDI treatment.

    Args:
        medication_name: Name of the medication

    Returns:
        True if medication is a CDI treatment
    """
    if not medication_name:
        return False

    med_lower = medication_name.lower().strip()

    # Direct match
    if med_lower in CDI_TREATMENT_MEDICATIONS:
        return True

    # Partial match
    for treatment in CDI_TREATMENT_MEDICATIONS:
        if treatment in med_lower:
            return True

    return False
