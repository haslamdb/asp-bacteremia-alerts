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
