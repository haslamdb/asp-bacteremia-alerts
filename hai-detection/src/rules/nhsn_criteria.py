"""NHSN criteria reference data and constants.

This module contains the authoritative lists and criteria from the NHSN
Patient Safety Component Manual. These should be updated annually when
NHSN publishes new guidelines.

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 4
https://www.cdc.gov/nhsn/pdfs/pscmanual/pcsmanual_current.pdf
"""

from datetime import timedelta

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
