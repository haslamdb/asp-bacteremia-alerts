"""Configuration management for Drug-Bug Mismatch Detection."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent  # drug-bug-mismatch/
AEGIS_ROOT = PROJECT_ROOT.parent  # aegis/

# Add common module to path
if str(AEGIS_ROOT) not in sys.path:
    sys.path.insert(0, str(AEGIS_ROOT))

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Fall back to template for defaults
    template_path = Path(__file__).parent.parent / ".env.template"
    if template_path.exists():
        load_dotenv(template_path)


class Config:
    """Application configuration."""

    # FHIR Server settings
    FHIR_BASE_URL: str = os.getenv("FHIR_BASE_URL", "http://localhost:8081/fhir")

    # Epic FHIR settings (for production)
    EPIC_FHIR_BASE_URL: str | None = os.getenv("EPIC_FHIR_BASE_URL")
    EPIC_CLIENT_ID: str | None = os.getenv("EPIC_CLIENT_ID")
    EPIC_PRIVATE_KEY_PATH: str | None = os.getenv("EPIC_PRIVATE_KEY_PATH")

    # Email settings
    SMTP_SERVER: str | None = os.getenv("SMTP_SERVER")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str | None = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD: str | None = os.getenv("SMTP_PASSWORD")
    ALERT_EMAIL_FROM: str | None = os.getenv("ALERT_EMAIL_FROM")
    ALERT_EMAIL_TO: list[str] = [
        e.strip() for e in os.getenv("ALERT_EMAIL_TO", "").split(",") if e.strip()
    ]

    # Teams webhook settings
    TEAMS_WEBHOOK_URL: str | None = os.getenv("TEAMS_WEBHOOK_URL")

    # Dashboard/Alert Store settings
    DASHBOARD_BASE_URL: str = os.getenv("DASHBOARD_BASE_URL", "http://localhost:5000")
    ALERT_DB_PATH: str | None = os.getenv("ALERT_DB_PATH")

    # Monitoring settings
    LOOKBACK_HOURS: int = int(os.getenv("LOOKBACK_HOURS", "24"))
    POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

    @classmethod
    def is_epic_configured(cls) -> bool:
        """Check if Epic FHIR credentials are configured."""
        return bool(cls.EPIC_FHIR_BASE_URL and cls.EPIC_CLIENT_ID)

    @classmethod
    def get_fhir_base_url(cls) -> str:
        """Get the appropriate FHIR base URL."""
        if cls.is_epic_configured():
            return cls.EPIC_FHIR_BASE_URL
        return cls.FHIR_BASE_URL


# Mapping from RxNorm codes to susceptibility test antibiotic names
# This maps medication orders to the corresponding susceptibility panel test names
ANTIBIOTIC_SUSCEPTIBILITY_MAP: dict[str, list[str]] = {
    # Glycopeptides
    "11124": ["vancomycin"],                    # Vancomycin

    # Carbapenems
    "29561": ["meropenem"],                     # Meropenem
    "1668240": ["ertapenem"],                   # Ertapenem
    "190376": ["imipenem"],                     # Imipenem

    # Cephalosporins
    "2193": ["ceftriaxone", "cefotaxime"],      # Ceftriaxone
    "2180": ["cefepime"],                       # Cefepime
    "4053": ["cefazolin"],                      # Cefazolin
    "2231": ["ceftazidime"],                    # Ceftazidime
    "1009148": ["ceftaroline"],                 # Ceftaroline

    # Penicillins
    "733": ["ampicillin"],                      # Ampicillin
    "7233": ["nafcillin", "oxacillin"],         # Nafcillin
    "7980": ["oxacillin", "nafcillin"],         # Oxacillin
    "152834": ["piperacillin-tazobactam", "piperacillin/tazobactam"],  # Pip-Tazo
    "57962": ["ampicillin-sulbactam", "ampicillin/sulbactam"],  # Unasyn

    # Aminoglycosides
    "4413": ["gentamicin"],                     # Gentamicin
    "10627": ["tobramycin"],                    # Tobramycin
    "641": ["amikacin"],                        # Amikacin

    # Fluoroquinolones
    "2551": ["ciprofloxacin"],                  # Ciprofloxacin
    "82122": ["levofloxacin"],                  # Levofloxacin
    "139462": ["moxifloxacin"],                 # Moxifloxacin

    # Oxazolidinones
    "190521": ["linezolid"],                    # Linezolid

    # Lipopeptides
    "203563": ["daptomycin"],                   # Daptomycin

    # Tetracyclines
    "10395": ["tetracycline"],                  # Tetracycline
    "1665088": ["doxycycline"],                 # Doxycycline

    # Sulfonamides
    "10831": ["trimethoprim-sulfamethoxazole", "trimethoprim/sulfamethoxazole", "tmp-smx"],

    # Macrolides
    "3640": ["erythromycin"],                   # Erythromycin
    "18631": ["azithromycin"],                  # Azithromycin
    "372684": ["clarithromycin"],               # Clarithromycin

    # Clindamycin
    "2582": ["clindamycin"],                    # Clindamycin

    # Metronidazole
    "6922": ["metronidazole"],                  # Metronidazole

    # Antifungals (for completeness)
    "4450": ["fluconazole"],                    # Fluconazole
    "327361": ["micafungin"],                   # Micafungin
    "285661": ["caspofungin"],                  # Caspofungin
    "732": ["amphotericin b", "amphotericin"],  # Amphotericin B
    "121243": ["voriconazole"],                 # Voriconazole
}

# Reverse lookup: susceptibility name -> RxNorm codes
SUSCEPTIBILITY_TO_RXNORM: dict[str, list[str]] = {}
for rxnorm, names in ANTIBIOTIC_SUSCEPTIBILITY_MAP.items():
    for name in names:
        name_lower = name.lower()
        if name_lower not in SUSCEPTIBILITY_TO_RXNORM:
            SUSCEPTIBILITY_TO_RXNORM[name_lower] = []
        SUSCEPTIBILITY_TO_RXNORM[name_lower].append(rxnorm)


config = Config()
