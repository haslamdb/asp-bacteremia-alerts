"""
Data models for surgical prophylaxis monitoring.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ComplianceStatus(Enum):
    """Status of individual bundle elements."""
    MET = "met"
    NOT_MET = "not_met"
    PENDING = "pending"          # Not yet evaluable (surgery in progress)
    NOT_APPLICABLE = "n/a"       # Element doesn't apply to this case
    UNABLE_TO_ASSESS = "unable"  # Missing data


class ProcedureCategory(Enum):
    """Categories of surgical procedures."""
    CARDIAC = "cardiac"
    THORACIC = "thoracic"
    GASTROINTESTINAL_UPPER = "gastrointestinal_upper"
    GASTROINTESTINAL_COLORECTAL = "gastrointestinal_colorectal"
    HEPATOBILIARY = "hepatobiliary"
    ORTHOPEDIC = "orthopedic"
    NEUROSURGERY = "neurosurgery"
    UROLOGY = "urology"
    ENT = "ent"
    HERNIA = "hernia"
    PLASTICS = "plastics"
    VASCULAR = "vascular"
    OTHER = "other"


@dataclass
class MedicationOrder:
    """Represents a prophylaxis medication order."""
    order_id: str
    medication_name: str
    dose_mg: float
    route: str
    ordered_time: datetime
    frequency: Optional[str] = None
    duration_hours: Optional[float] = None


@dataclass
class MedicationAdministration:
    """Represents an actual medication administration."""
    admin_id: str
    medication_name: str
    dose_mg: float
    route: str
    admin_time: datetime
    infusion_end_time: Optional[datetime] = None
    order_id: Optional[str] = None


@dataclass
class SurgicalCase:
    """Represents a surgical case for prophylaxis evaluation."""
    case_id: str
    patient_mrn: str
    encounter_id: str

    # Procedure info
    cpt_codes: list[str]
    procedure_description: str
    procedure_category: ProcedureCategory
    surgeon_id: Optional[str] = None
    surgeon_name: Optional[str] = None
    location: Optional[str] = None

    # Timing
    scheduled_or_time: Optional[datetime] = None
    actual_incision_time: Optional[datetime] = None
    surgery_end_time: Optional[datetime] = None

    # Patient factors
    patient_weight_kg: Optional[float] = None
    patient_age_years: Optional[float] = None
    allergies: list[str] = field(default_factory=list)
    has_beta_lactam_allergy: bool = False
    mrsa_colonized: bool = False

    # Prophylaxis data
    prophylaxis_orders: list[MedicationOrder] = field(default_factory=list)
    prophylaxis_administrations: list[MedicationAdministration] = field(default_factory=list)

    # Calculated fields
    is_emergency: bool = False
    already_on_therapeutic_antibiotics: bool = False
    documented_infection: bool = False

    @property
    def surgery_duration_hours(self) -> Optional[float]:
        """Calculate surgery duration in hours."""
        if self.actual_incision_time and self.surgery_end_time:
            delta = self.surgery_end_time - self.actual_incision_time
            return delta.total_seconds() / 3600
        return None


@dataclass
class ElementResult:
    """Result for a single bundle element."""
    element_name: str
    status: ComplianceStatus
    details: str
    recommendation: Optional[str] = None
    data: Optional[dict] = None


@dataclass
class ProphylaxisEvaluation:
    """Result of prophylaxis bundle evaluation."""
    case_id: str
    patient_mrn: str
    encounter_id: str
    evaluation_time: datetime

    # Element results
    indication: ElementResult
    agent_selection: ElementResult
    timing: ElementResult
    dosing: ElementResult
    redosing: ElementResult
    postop_continuation: ElementResult
    discontinuation: ElementResult

    # Summary
    bundle_compliant: bool
    compliance_score: float  # Percentage 0-100
    elements_met: int
    elements_total: int

    # Flags and recommendations
    flags: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # Exclusions
    excluded: bool = False
    exclusion_reason: Optional[str] = None

    @property
    def elements(self) -> list[ElementResult]:
        """Return all element results as a list."""
        return [
            self.indication,
            self.agent_selection,
            self.timing,
            self.dosing,
            self.redosing,
            self.postop_continuation,
            self.discontinuation
        ]


@dataclass
class ProcedureRequirement:
    """Requirements for a specific procedure type."""
    procedure_name: str
    cpt_codes: list[str]
    prophylaxis_indicated: bool
    first_line_agents: list[str]
    alternative_agents: list[str]
    duration_limit_hours: int = 24
    requires_anaerobic_coverage: bool = False
    mrsa_high_risk_add: Optional[str] = None
    notes: Optional[str] = None
    # Post-operative continuation requirements
    requires_postop_continuation: bool = False  # MUST have post-op doses
    postop_continuation_allowed: bool = False   # OK to have post-op doses (optional)
    postop_duration_hours: Optional[int] = None  # How long to continue post-op
    postop_interval_hours: Optional[float] = None  # Dosing interval for post-op


@dataclass
class DosingInfo:
    """Dosing information for an antibiotic."""
    medication_name: str
    pediatric_mg_per_kg: float
    pediatric_max_mg: float
    adult_standard_mg: float
    adult_high_weight_threshold_kg: float = 120.0
    adult_high_weight_mg: Optional[float] = None
    redose_interval_hours: Optional[float] = None
    infusion_time_minutes: Optional[int] = None


@dataclass
class TimingResult:
    """Detailed timing analysis result."""
    prophylaxis_given: bool
    minutes_before_incision: Optional[float] = None
    within_standard_window: bool = False
    within_extended_window: bool = False  # For vanco/fluoroquinolones
    details: str = ""
