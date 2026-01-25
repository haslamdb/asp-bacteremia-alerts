"""Configuration for guideline adherence monitoring."""

import os
from pathlib import Path


class Config:
    """Configuration settings for guideline adherence monitoring."""

    # FHIR settings
    FHIR_BASE_URL = os.environ.get("FHIR_BASE_URL", "http://localhost:8081/fhir")
    EPIC_FHIR_BASE_URL = os.environ.get("EPIC_FHIR_BASE_URL", "")
    EPIC_CLIENT_ID = os.environ.get("EPIC_CLIENT_ID", "")
    EPIC_PRIVATE_KEY_PATH = os.environ.get("EPIC_PRIVATE_KEY_PATH", "")

    # Database paths
    BASE_DIR = Path(__file__).parent.parent
    ADHERENCE_DB_PATH = os.environ.get(
        "GUIDELINE_ADHERENCE_DB_PATH",
        str(BASE_DIR / "data" / "guideline_adherence.db"),
    )
    ALERT_DB_PATH = os.environ.get(
        "ALERT_DB_PATH",
        str(BASE_DIR.parent / "common" / "alert_store" / "alerts.db"),
    )

    # Monitoring intervals (minutes)
    CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "15"))

    # Bundle configuration
    ENABLED_BUNDLES = os.environ.get(
        "ENABLED_BUNDLES",
        "sepsis_peds_2024",  # Start with sepsis bundle
    ).split(",")

    # Alert thresholds
    ALERT_ON_FIRST_DEVIATION = os.environ.get("ALERT_ON_FIRST_DEVIATION", "true").lower() == "true"

    # LOINC codes for common observations
    LOINC_LACTATE = "2524-7"
    LOINC_BLOOD_CULTURE = "600-7"
    LOINC_TEMPERATURE = "8310-5"
    LOINC_HEART_RATE = "8867-4"
    LOINC_RESP_RATE = "9279-1"
    LOINC_SPO2 = "2708-6"
    LOINC_SYSTOLIC_BP = "8480-6"
    LOINC_DIASTOLIC_BP = "8462-4"

    # Febrile infant lab LOINC codes
    LOINC_PROCALCITONIN = "33959-8"       # Procalcitonin
    LOINC_CRP = "1988-5"                  # C-reactive protein
    LOINC_ANC = "751-8"                   # Absolute neutrophil count
    LOINC_WBC = "6690-2"                  # White blood cell count
    LOINC_UA = "5767-9"                   # Urinalysis
    LOINC_UA_WBC = "5821-4"               # Urine WBC
    LOINC_UA_LE = "5799-2"                # Urine leukocyte esterase
    LOINC_URINE_CULTURE = "630-4"         # Urine culture
    LOINC_CSF_WBC = "806-0"               # CSF WBC
    LOINC_CSF_RBC = "804-5"               # CSF RBC
    LOINC_CSF_CULTURE = "600-7"           # CSF culture (same as blood culture order)

    # Febrile infant inflammatory marker thresholds (AAP 2021)
    FI_PCT_ABNORMAL = 0.5                 # ng/mL
    FI_ANC_ABNORMAL = 4000                # cells/μL
    FI_CRP_ABNORMAL = 2.0                 # mg/dL
    FI_CSF_WBC_PLEOCYTOSIS = 15           # cells/μL
    FI_UA_WBC_ABNORMAL = 5                # per HPF

    # Febrile infant ICD-10 codes
    FEBRILE_INFANT_ICD10_PREFIXES = [
        "R50",    # Fever
        "P81.9",  # Temperature regulation disturbance of newborn
    ]

    # Sepsis ICD-10 code prefixes
    SEPSIS_ICD10_PREFIXES = [
        "A41",   # Other sepsis
        "A40",   # Streptococcal sepsis
        "R65.2", # Severe sepsis
        "P36",   # Neonatal sepsis
    ]

    def is_epic_configured(self) -> bool:
        """Check if Epic FHIR is configured."""
        return bool(self.EPIC_FHIR_BASE_URL and self.EPIC_CLIENT_ID)


config = Config()
