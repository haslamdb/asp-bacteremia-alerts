"""
Configuration for surgical prophylaxis module.
"""

import json
import os
from pathlib import Path
from typing import Optional

from .models import DosingInfo, ProcedureCategory, ProcedureRequirement


# Paths
MODULE_DIR = Path(__file__).parent.parent
DATA_DIR = MODULE_DIR / "data"
GUIDELINES_FILE = DATA_DIR / "cchmc_surgical_prophylaxis_guidelines.json"

# Environment configuration
FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "http://localhost:8081/fhir")
ALERT_DB_PATH = os.getenv("ALERT_DB_PATH", os.path.expanduser("~/.aegis/alerts.db"))

# Timing thresholds
STANDARD_TIMING_WINDOW_MINUTES = 60
EXTENDED_TIMING_WINDOW_MINUTES = 120  # For vancomycin, fluoroquinolones

# Duration thresholds
STANDARD_DURATION_HOURS = 24
CARDIAC_DURATION_HOURS = 48

# Extended window antibiotics
EXTENDED_WINDOW_ANTIBIOTICS = [
    "vancomycin",
    "ciprofloxacin",
    "levofloxacin",
    "moxifloxacin",
]

# Antibiotics not requiring redosing
NO_REDOSE_ANTIBIOTICS = [
    "vancomycin",
    "metronidazole",
]

# Default dosing information (fallback if not in JSON)
# Updated per CCHMC Surg PPX Guidelines 9-6-2024
DEFAULT_DOSING: dict[str, DosingInfo] = {
    "cefazolin": DosingInfo(
        medication_name="cefazolin",
        pediatric_mg_per_kg=40.0,
        pediatric_max_mg=2000.0,
        adult_standard_mg=2000.0,
        adult_high_weight_threshold_kg=100.0,
        adult_high_weight_mg=3000.0,
        redose_interval_hours=3.0,
    ),
    "cefoxitin": DosingInfo(
        medication_name="cefoxitin",
        pediatric_mg_per_kg=40.0,
        pediatric_max_mg=2000.0,
        adult_standard_mg=2000.0,
        redose_interval_hours=3.0,
    ),
    "ceftriaxone": DosingInfo(
        medication_name="ceftriaxone",
        pediatric_mg_per_kg=50.0,
        pediatric_max_mg=2000.0,
        adult_standard_mg=2000.0,
        redose_interval_hours=12.0,
    ),
    "cefuroxime": DosingInfo(
        medication_name="cefuroxime",
        pediatric_mg_per_kg=50.0,
        pediatric_max_mg=2000.0,
        adult_standard_mg=2000.0,
        redose_interval_hours=3.0,
    ),
    "vancomycin": DosingInfo(
        medication_name="vancomycin",
        pediatric_mg_per_kg=15.0,
        pediatric_max_mg=2000.0,
        adult_standard_mg=2000.0,
        redose_interval_hours=8.0,
        infusion_time_minutes=60,
    ),
    "metronidazole": DosingInfo(
        medication_name="metronidazole",
        pediatric_mg_per_kg=15.0,
        pediatric_max_mg=1000.0,
        adult_standard_mg=1000.0,
        redose_interval_hours=12.0,
    ),
    "clindamycin": DosingInfo(
        medication_name="clindamycin",
        pediatric_mg_per_kg=10.0,
        pediatric_max_mg=900.0,
        adult_standard_mg=900.0,
        redose_interval_hours=6.0,
    ),
    "gentamicin": DosingInfo(
        medication_name="gentamicin",
        pediatric_mg_per_kg=4.5,
        pediatric_max_mg=160.0,
        adult_standard_mg=360.0,
        redose_interval_hours=12.0,
    ),
    "ampicillin": DosingInfo(
        medication_name="ampicillin",
        pediatric_mg_per_kg=50.0,
        pediatric_max_mg=2000.0,
        adult_standard_mg=2000.0,
        redose_interval_hours=2.0,
    ),
    "ampicillin-sulbactam": DosingInfo(
        medication_name="ampicillin-sulbactam",
        pediatric_mg_per_kg=75.0,  # amp+sul components
        pediatric_max_mg=3000.0,
        adult_standard_mg=3000.0,
        redose_interval_hours=2.0,
    ),
    "piperacillin-tazobactam": DosingInfo(
        medication_name="piperacillin-tazobactam",
        pediatric_mg_per_kg=100.0,  # pip+tazo components
        pediatric_max_mg=3375.0,
        adult_standard_mg=3375.0,
        redose_interval_hours=2.0,
    ),
    "aztreonam": DosingInfo(
        medication_name="aztreonam",
        pediatric_mg_per_kg=30.0,
        pediatric_max_mg=2000.0,
        adult_standard_mg=2000.0,
        redose_interval_hours=4.0,
    ),
    "ciprofloxacin": DosingInfo(
        medication_name="ciprofloxacin",
        pediatric_mg_per_kg=10.0,
        pediatric_max_mg=400.0,
        adult_standard_mg=400.0,
        redose_interval_hours=8.0,
    ),
}

# Procedure category mapping from CPT code prefixes
CPT_CATEGORY_HINTS: dict[str, ProcedureCategory] = {
    "336": ProcedureCategory.CARDIAC,  # Cardiac surgery
    "337": ProcedureCategory.CARDIAC,
    "338": ProcedureCategory.CARDIAC,
    "339": ProcedureCategory.CARDIAC,
    "324": ProcedureCategory.THORACIC,  # Lung surgery
    "326": ProcedureCategory.THORACIC,
    "432": ProcedureCategory.GASTROINTESTINAL_UPPER,
    "433": ProcedureCategory.GASTROINTESTINAL_UPPER,
    "434": ProcedureCategory.GASTROINTESTINAL_UPPER,
    "441": ProcedureCategory.GASTROINTESTINAL_COLORECTAL,
    "449": ProcedureCategory.GASTROINTESTINAL_COLORECTAL,
    "451": ProcedureCategory.GASTROINTESTINAL_COLORECTAL,
    "471": ProcedureCategory.HEPATOBILIARY,
    "475": ProcedureCategory.HEPATOBILIARY,
    "476": ProcedureCategory.HEPATOBILIARY,
    "225": ProcedureCategory.ORTHOPEDIC,
    "226": ProcedureCategory.ORTHOPEDIC,
    "227": ProcedureCategory.ORTHOPEDIC,
    "228": ProcedureCategory.ORTHOPEDIC,
    "613": ProcedureCategory.NEUROSURGERY,
    "622": ProcedureCategory.NEUROSURGERY,
    "503": ProcedureCategory.UROLOGY,
    "504": ProcedureCategory.UROLOGY,
    "507": ProcedureCategory.UROLOGY,
    "543": ProcedureCategory.UROLOGY,
    "546": ProcedureCategory.UROLOGY,
    "428": ProcedureCategory.ENT,
    "693": ProcedureCategory.ENT,
    "694": ProcedureCategory.ENT,
    "695": ProcedureCategory.ENT,
    "495": ProcedureCategory.HERNIA,
    "496": ProcedureCategory.HERNIA,
    "407": ProcedureCategory.PLASTICS,
    "422": ProcedureCategory.PLASTICS,
    "615": ProcedureCategory.PLASTICS,
    "368": ProcedureCategory.VASCULAR,
}


class GuidelinesConfig:
    """Load and provide access to surgical prophylaxis guidelines."""

    def __init__(self, guidelines_path: Optional[Path] = None):
        self.guidelines_path = guidelines_path or GUIDELINES_FILE
        self._guidelines: dict = {}
        self._procedure_requirements: dict[str, ProcedureRequirement] = {}
        self._dosing_info: dict[str, DosingInfo] = {}
        self._load_guidelines()

    def _load_guidelines(self):
        """Load guidelines from JSON file."""
        if self.guidelines_path.exists():
            with open(self.guidelines_path) as f:
                self._guidelines = json.load(f)
            self._build_procedure_index()
            self._build_dosing_index()
        else:
            # Use defaults
            self._dosing_info = DEFAULT_DOSING.copy()

    def _build_procedure_index(self):
        """Build an index of CPT codes to procedure requirements."""
        procedures = self._guidelines.get("procedures", {})

        for category_key, category_data in procedures.items():
            category_name = category_data.get("category_name", category_key)
            default_indicated = category_data.get("prophylaxis_indicated", True)
            default_duration = category_data.get("duration_limit_hours", 24)
            requires_anaerobic = category_data.get("requires_anaerobic_coverage", False)
            default_postop_allowed = category_data.get("postop_continuation_allowed", False)

            for proc in category_data.get("procedures", []):
                # Get procedure-level overrides
                proc_indicated = proc.get("prophylaxis_indicated", default_indicated)
                proc_anaerobic = proc.get("requires_anaerobic_coverage", requires_anaerobic)
                proc_postop_allowed = proc.get("postop_continuation_allowed", default_postop_allowed)

                req = ProcedureRequirement(
                    procedure_name=proc.get("name", "Unknown"),
                    cpt_codes=proc.get("cpt_codes", []),
                    prophylaxis_indicated=proc_indicated,
                    first_line_agents=proc.get("first_line_agents", []),
                    alternative_agents=proc.get("alternative_agents", []),
                    duration_limit_hours=default_duration,
                    requires_anaerobic_coverage=proc_anaerobic,
                    mrsa_high_risk_add=proc.get("mrsa_high_risk_add"),
                    notes=proc.get("notes"),
                    # Post-op continuation fields
                    requires_postop_continuation=proc.get("requires_postop_continuation", False),
                    postop_continuation_allowed=proc_postop_allowed,
                    postop_duration_hours=proc.get("postop_duration_hours"),
                    postop_interval_hours=proc.get("postop_interval_hours"),
                )

                # Index by each CPT code
                for cpt in req.cpt_codes:
                    self._procedure_requirements[cpt] = req

    def _build_dosing_index(self):
        """Build dosing information index."""
        # Start with defaults
        self._dosing_info = DEFAULT_DOSING.copy()

        # Override with JSON data if available (check both old and new locations)
        dosing_data = self._guidelines.get("dosing", {})
        if not dosing_data:
            # Fall back to old location for backwards compatibility
            dosing_data = self._guidelines.get("general_principles", {}).get("dosing", {})

        for med_name, info in dosing_data.items():
            # Normalize medication name (replace underscores with hyphens)
            normalized_name = med_name.replace("_", "-")
            self._dosing_info[normalized_name] = DosingInfo(
                medication_name=normalized_name,
                pediatric_mg_per_kg=info.get("dose_mg_per_kg", info.get("pediatric_mg_per_kg", info.get("mg_per_kg", 0))),
                pediatric_max_mg=info.get("max_per_dose_mg", info.get("pediatric_max_mg", info.get("max_mg", 0))) or 0,
                adult_standard_mg=info.get("max_per_dose_mg", info.get("adult_standard_mg", info.get("max_mg", 0))) or 0,
                adult_high_weight_threshold_kg=info.get("high_weight_threshold_kg", info.get("adult_high_weight_threshold_kg", 120)),
                adult_high_weight_mg=info.get("high_weight_max_mg", info.get("adult_high_weight_mg")),
                redose_interval_hours=info.get("redose_interval_hours"),
                infusion_time_minutes=info.get("infusion_time_minutes"),
            )

    def get_procedure_requirements(self, cpt_code: str) -> Optional[ProcedureRequirement]:
        """Get prophylaxis requirements for a CPT code."""
        return self._procedure_requirements.get(cpt_code)

    def get_dosing_info(self, medication_name: str) -> Optional[DosingInfo]:
        """Get dosing information for a medication."""
        # Normalize name
        med_lower = medication_name.lower().replace(" ", "-")
        return self._dosing_info.get(med_lower)

    def get_redose_interval(self, medication_name: str) -> Optional[float]:
        """Get redosing interval in hours for a medication."""
        # Check redosing_intervals section first
        intervals = self._guidelines.get("redosing_intervals", {})
        med_lower = medication_name.lower().replace(" ", "-").replace("_", "-")

        if med_lower in intervals:
            return intervals[med_lower].get("interval_hours")

        # Fall back to dosing info
        dosing = self.get_dosing_info(medication_name)
        if dosing:
            return dosing.redose_interval_hours

        return None

    def get_duration_limit(self, procedure_category: ProcedureCategory) -> int:
        """Get duration limit in hours for a procedure category."""
        if procedure_category == ProcedureCategory.CARDIAC:
            return CARDIAC_DURATION_HOURS
        return STANDARD_DURATION_HOURS

    def get_timing_window(self, medication_name: str) -> int:
        """Get timing window in minutes for a medication."""
        med_lower = medication_name.lower()
        if any(ext in med_lower for ext in EXTENDED_WINDOW_ANTIBIOTICS):
            return EXTENDED_TIMING_WINDOW_MINUTES
        return STANDARD_TIMING_WINDOW_MINUTES

    @property
    def metadata(self) -> dict:
        """Return guidelines metadata."""
        return self._guidelines.get("metadata", {})


# Global instance
_config: Optional[GuidelinesConfig] = None


def get_config() -> GuidelinesConfig:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = GuidelinesConfig()
    return _config


# Real-time monitoring configuration

# HL7 Listener settings
HL7_ENABLED = os.getenv("HL7_ENABLED", "true").lower() == "true"
HL7_LISTENER_HOST = os.getenv("HL7_LISTENER_HOST", "0.0.0.0")
HL7_LISTENER_PORT = int(os.getenv("HL7_LISTENER_PORT", "2575"))

# FHIR polling intervals (minutes)
FHIR_SCHEDULE_POLL_INTERVAL = int(os.getenv("FHIR_SCHEDULE_POLL_INTERVAL", "15"))
FHIR_PROPHYLAXIS_POLL_INTERVAL = int(os.getenv("FHIR_PROPHYLAXIS_POLL_INTERVAL", "5"))
FHIR_LOOKAHEAD_HOURS = int(os.getenv("FHIR_LOOKAHEAD_HOURS", "48"))

# Epic Secure Chat settings
EPIC_CHAT_ENABLED = os.getenv("EPIC_CHAT_ENABLED", "false").lower() == "true"
EPIC_CHAT_CLIENT_ID = os.getenv("EPIC_CHAT_CLIENT_ID", "")
EPIC_CHAT_PRIVATE_KEY_PATH = os.getenv("EPIC_CHAT_PRIVATE_KEY_PATH", "")
EPIC_FHIR_BASE_URL = os.getenv("EPIC_FHIR_BASE_URL", "")
EPIC_TOKEN_ENDPOINT = os.getenv("EPIC_TOKEN_ENDPOINT", "")

# Teams fallback settings
TEAMS_FALLBACK_ENABLED = os.getenv("TEAMS_FALLBACK_ENABLED", "true").lower() == "true"
TEAMS_SURGICAL_PROPHYLAXIS_WEBHOOK = os.getenv("TEAMS_SURGICAL_PROPHYLAXIS_WEBHOOK", "")

# Location pattern matching (comma-separated lists)
LOCATION_PREOP_PATTERNS = os.getenv(
    "LOCATION_PREOP_PATTERNS",
    "PREOP,PHOLD,PRE-OP,SURG PREP,SDS,ASC"
).split(",")
LOCATION_OR_PATTERNS = os.getenv(
    "LOCATION_OR_PATTERNS",
    "OR,OPER,SURG SUITE,THEATER,CATH LAB"
).split(",")
LOCATION_PACU_PATTERNS = os.getenv(
    "LOCATION_PACU_PATTERNS",
    "PACU,RECOVERY,POST ANES"
).split(",")

# Alert trigger thresholds (enable/disable each trigger)
ALERT_T24_ENABLED = os.getenv("ALERT_T24_ENABLED", "true").lower() == "true"
ALERT_T2_ENABLED = os.getenv("ALERT_T2_ENABLED", "true").lower() == "true"
ALERT_T60_ENABLED = os.getenv("ALERT_T60_ENABLED", "true").lower() == "true"
ALERT_T0_ENABLED = os.getenv("ALERT_T0_ENABLED", "true").lower() == "true"

# Escalation timing (minutes)
ESCALATION_PREOP_DELAY = int(os.getenv("ESCALATION_PREOP_DELAY", "30"))
ESCALATION_T60_DELAY = int(os.getenv("ESCALATION_T60_DELAY", "15"))
ESCALATION_T0_DELAY = int(os.getenv("ESCALATION_T0_DELAY", "5"))


class RealtimeConfig:
    """Configuration for real-time monitoring features."""

    def __init__(self):
        self.hl7_enabled = HL7_ENABLED
        self.hl7_host = HL7_LISTENER_HOST
        self.hl7_port = HL7_LISTENER_PORT

        self.fhir_schedule_poll_interval = FHIR_SCHEDULE_POLL_INTERVAL
        self.fhir_prophylaxis_poll_interval = FHIR_PROPHYLAXIS_POLL_INTERVAL
        self.fhir_lookahead_hours = FHIR_LOOKAHEAD_HOURS

        self.epic_chat_enabled = EPIC_CHAT_ENABLED
        self.teams_enabled = TEAMS_FALLBACK_ENABLED
        self.teams_webhook = TEAMS_SURGICAL_PROPHYLAXIS_WEBHOOK

        self.location_preop_patterns = LOCATION_PREOP_PATTERNS
        self.location_or_patterns = LOCATION_OR_PATTERNS
        self.location_pacu_patterns = LOCATION_PACU_PATTERNS

        self.alert_t24_enabled = ALERT_T24_ENABLED
        self.alert_t2_enabled = ALERT_T2_ENABLED
        self.alert_t60_enabled = ALERT_T60_ENABLED
        self.alert_t0_enabled = ALERT_T0_ENABLED

        self.escalation_preop_delay = ESCALATION_PREOP_DELAY
        self.escalation_t60_delay = ESCALATION_T60_DELAY
        self.escalation_t0_delay = ESCALATION_T0_DELAY


# Global realtime config instance
_realtime_config: Optional[RealtimeConfig] = None


def get_realtime_config() -> RealtimeConfig:
    """Get or create the global realtime configuration instance."""
    global _realtime_config
    if _realtime_config is None:
        _realtime_config = RealtimeConfig()
    return _realtime_config
