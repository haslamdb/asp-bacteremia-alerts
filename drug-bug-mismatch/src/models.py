"""Data models for Drug-Bug Mismatch Detection."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class MismatchType(Enum):
    """Type of drug-bug mismatch detected."""
    RESISTANT = "resistant"       # Organism is resistant (R) to current therapy
    INTERMEDIATE = "intermediate" # Organism has intermediate susceptibility (I)
    NO_COVERAGE = "no_coverage"   # Patient not on any effective antibiotics


class AlertSeverity(Enum):
    """Severity level for routing alerts."""
    CRITICAL = "critical"  # Resistant organism + inadequate coverage
    WARNING = "warning"    # Intermediate or no coverage
    INFO = "info"          # For informational purposes


@dataclass
class Patient:
    """Patient information."""
    fhir_id: str
    mrn: str
    name: str
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    location: Optional[str] = None


@dataclass
class Antibiotic:
    """Active antibiotic order."""
    fhir_id: str
    medication_name: str
    rxnorm_code: Optional[str] = None
    route: Optional[str] = None
    status: str = "active"
    ordered_date: Optional[datetime] = None


@dataclass
class Susceptibility:
    """Susceptibility test result for an organism-antibiotic pair."""
    organism: str
    antibiotic: str
    interpretation: str  # S, I, R (Susceptible, Intermediate, Resistant)
    mic: Optional[float] = None
    mic_units: Optional[str] = None
    mic_text: Optional[str] = None  # Raw MIC text (e.g., ">256", "<=0.5")

    def is_susceptible(self) -> bool:
        """Check if organism is susceptible."""
        return self.interpretation.upper() == "S"

    def is_intermediate(self) -> bool:
        """Check if organism has intermediate susceptibility."""
        return self.interpretation.upper() == "I"

    def is_resistant(self) -> bool:
        """Check if organism is resistant."""
        return self.interpretation.upper() == "R"


@dataclass
class CultureWithSusceptibilities:
    """Culture result with associated susceptibility testing."""
    fhir_id: str
    patient_id: str
    organism: str
    collection_date: Optional[datetime] = None
    resulted_date: Optional[datetime] = None
    specimen_type: Optional[str] = None  # blood, urine, wound, etc.
    susceptibilities: list[Susceptibility] = field(default_factory=list)

    def get_susceptibility_for(self, antibiotic_name: str) -> Optional[Susceptibility]:
        """Find susceptibility result for a specific antibiotic."""
        antibiotic_lower = antibiotic_name.lower()
        for susc in self.susceptibilities:
            if antibiotic_lower in susc.antibiotic.lower():
                return susc
        return None

    def get_susceptible_antibiotics(self) -> list[Susceptibility]:
        """Get all susceptible antibiotic options."""
        return [s for s in self.susceptibilities if s.is_susceptible()]

    def get_resistant_antibiotics(self) -> list[Susceptibility]:
        """Get all antibiotics the organism is resistant to."""
        return [s for s in self.susceptibilities if s.is_resistant()]


@dataclass
class DrugBugMismatch:
    """A detected drug-bug mismatch."""
    culture: CultureWithSusceptibilities
    antibiotic: Antibiotic  # The antibiotic the patient is currently on
    susceptibility: Optional[Susceptibility]  # The susceptibility result (if available)
    mismatch_type: MismatchType

    def get_severity(self) -> AlertSeverity:
        """Determine alert severity based on mismatch type."""
        if self.mismatch_type == MismatchType.RESISTANT:
            return AlertSeverity.CRITICAL
        return AlertSeverity.WARNING


@dataclass
class MismatchAssessment:
    """Complete assessment of drug-bug mismatches for a patient/culture."""
    patient: Patient
    culture: CultureWithSusceptibilities
    current_antibiotics: list[Antibiotic] = field(default_factory=list)
    mismatches: list[DrugBugMismatch] = field(default_factory=list)
    severity: AlertSeverity = AlertSeverity.INFO
    recommendation: str = ""
    assessed_at: datetime = field(default_factory=datetime.now)

    def has_mismatches(self) -> bool:
        """Check if any mismatches were detected."""
        return len(self.mismatches) > 0

    def get_highest_severity(self) -> AlertSeverity:
        """Get the highest severity among all mismatches."""
        if not self.mismatches:
            return AlertSeverity.INFO
        if any(m.get_severity() == AlertSeverity.CRITICAL for m in self.mismatches):
            return AlertSeverity.CRITICAL
        if any(m.get_severity() == AlertSeverity.WARNING for m in self.mismatches):
            return AlertSeverity.WARNING
        return AlertSeverity.INFO

    def to_alert_content(self) -> dict:
        """Convert assessment to alert content dictionary."""
        susceptibility_panel = []
        for susc in self.culture.susceptibilities:
            panel_entry = {
                "antibiotic": susc.antibiotic,
                "result": susc.interpretation,
            }
            if susc.mic_text:
                panel_entry["mic"] = susc.mic_text
            elif susc.mic is not None:
                panel_entry["mic"] = f"{susc.mic} {susc.mic_units or ''}"
            susceptibility_panel.append(panel_entry)

        # Get susceptible options for recommendations
        susceptible_options = [
            s.antibiotic for s in self.culture.get_susceptible_antibiotics()
        ]

        # Build current antibiotics info from mismatches
        current_abx_info = []
        for mismatch in self.mismatches:
            entry = {
                "name": mismatch.antibiotic.medication_name,
                "rxnorm": mismatch.antibiotic.rxnorm_code,
                "mismatch_type": mismatch.mismatch_type.value,
            }
            if mismatch.susceptibility:
                entry["susceptibility"] = mismatch.susceptibility.interpretation
            current_abx_info.append(entry)

        # Also include all current antibiotics (even those not in mismatches)
        # to show the complete picture of what patient is on
        all_abx_names = {e["name"] for e in current_abx_info}
        for abx in self.current_antibiotics:
            if abx.medication_name not in all_abx_names:
                # Find if there's a matching susceptibility
                susc_result = None
                for susc in self.culture.susceptibilities:
                    if abx.medication_name.lower() in susc.antibiotic.lower():
                        susc_result = susc.interpretation
                        break
                current_abx_info.append({
                    "name": abx.medication_name,
                    "rxnorm": abx.rxnorm_code,
                    "mismatch_type": "susceptible" if susc_result == "S" else None,
                    "susceptibility": susc_result,
                })

        return {
            "culture_id": self.culture.fhir_id,
            "organism": self.culture.organism,
            "specimen_type": self.culture.specimen_type,
            "collection_date": (
                self.culture.collection_date.isoformat()
                if self.culture.collection_date
                else None
            ),
            "mismatch_type": (
                self.mismatches[0].mismatch_type.value
                if self.mismatches
                else None
            ),
            "current_antibiotics": current_abx_info,
            "susceptible_options": susceptible_options[:5],  # Top 5 options
            "recommendation": self.recommendation,
            "susceptibility_panel": susceptibility_panel,
        }
