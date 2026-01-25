"""Susceptibility matching logic for Drug-Bug Mismatch Detection.

Determines if a patient's current antibiotic therapy provides adequate
coverage based on susceptibility testing results.
"""

from .config import ANTIBIOTIC_SUSCEPTIBILITY_MAP
from .models import (
    Antibiotic,
    AlertSeverity,
    CultureWithSusceptibilities,
    DrugBugMismatch,
    MismatchAssessment,
    MismatchType,
    Patient,
    Susceptibility,
)


def normalize_antibiotic_name(name: str) -> str:
    """Normalize antibiotic name for matching."""
    return name.lower().strip().replace("-", " ").replace("/", " ")


def get_susceptibility_names_for_antibiotic(antibiotic: Antibiotic) -> list[str]:
    """Get susceptibility test names that correspond to an antibiotic order."""
    names = []

    # First try RxNorm code lookup
    if antibiotic.rxnorm_code:
        mapped_names = ANTIBIOTIC_SUSCEPTIBILITY_MAP.get(antibiotic.rxnorm_code, [])
        names.extend(mapped_names)

    # Fall back to medication name matching
    if not names:
        med_name = normalize_antibiotic_name(antibiotic.medication_name)
        # Add the medication name itself as a potential match
        names.append(med_name)

    return names


def find_matching_susceptibility(
    antibiotic: Antibiotic,
    susceptibilities: list[Susceptibility],
) -> Susceptibility | None:
    """Find a susceptibility result that matches the given antibiotic."""
    susc_names = get_susceptibility_names_for_antibiotic(antibiotic)

    for susc in susceptibilities:
        susc_name = normalize_antibiotic_name(susc.antibiotic)
        for name in susc_names:
            if name in susc_name or susc_name in name:
                return susc

    return None


def check_coverage(
    culture: CultureWithSusceptibilities,
    antibiotics: list[Antibiotic],
) -> list[DrugBugMismatch]:
    """
    Check if current antibiotics cover the culture organism.

    Returns a list of detected mismatches (resistant or intermediate antibiotics).
    """
    mismatches = []

    if not culture.susceptibilities:
        # No susceptibility data - can't assess
        return mismatches

    if not antibiotics:
        # No antibiotics - check if any susceptible options exist
        susceptible = culture.get_susceptible_antibiotics()
        if susceptible:
            # Patient needs treatment but isn't on anything
            # Create a "no coverage" mismatch with a placeholder antibiotic
            mismatch = DrugBugMismatch(
                culture=culture,
                antibiotic=Antibiotic(
                    fhir_id="",
                    medication_name="No active antibiotics",
                    rxnorm_code=None,
                ),
                susceptibility=None,
                mismatch_type=MismatchType.NO_COVERAGE,
            )
            mismatches.append(mismatch)
        return mismatches

    # Check each antibiotic the patient is on
    for antibiotic in antibiotics:
        susc = find_matching_susceptibility(antibiotic, culture.susceptibilities)

        if susc:
            # We have susceptibility data for this antibiotic
            if susc.is_resistant():
                mismatch = DrugBugMismatch(
                    culture=culture,
                    antibiotic=antibiotic,
                    susceptibility=susc,
                    mismatch_type=MismatchType.RESISTANT,
                )
                mismatches.append(mismatch)
            elif susc.is_intermediate():
                mismatch = DrugBugMismatch(
                    culture=culture,
                    antibiotic=antibiotic,
                    susceptibility=susc,
                    mismatch_type=MismatchType.INTERMEDIATE,
                )
                mismatches.append(mismatch)
            # If susceptible, no mismatch

    return mismatches


def has_any_effective_coverage(
    culture: CultureWithSusceptibilities,
    antibiotics: list[Antibiotic],
) -> bool:
    """Check if at least one antibiotic provides effective coverage."""
    for antibiotic in antibiotics:
        susc = find_matching_susceptibility(antibiotic, culture.susceptibilities)
        if susc and susc.is_susceptible():
            return True
    return False


def get_recommendation(
    culture: CultureWithSusceptibilities,
    mismatches: list[DrugBugMismatch],
) -> str:
    """Generate therapy recommendation based on susceptibilities and mismatches."""
    if not mismatches:
        return "Current therapy appears adequate based on susceptibility testing."

    # Get susceptible options
    susceptible = culture.get_susceptible_antibiotics()
    susceptible_names = [s.antibiotic for s in susceptible[:5]]  # Top 5

    # Build recommendation based on mismatch type
    mismatch_types = set(m.mismatch_type for m in mismatches)

    if MismatchType.RESISTANT in mismatch_types:
        resistant_abx = [
            m.antibiotic.medication_name
            for m in mismatches
            if m.mismatch_type == MismatchType.RESISTANT
        ]
        if susceptible_names:
            return (
                f"Organism resistant to {', '.join(resistant_abx)}. "
                f"Consider: {', '.join(susceptible_names)}."
            )
        else:
            return (
                f"Organism resistant to {', '.join(resistant_abx)}. "
                f"No susceptible options identified - ID consult recommended."
            )

    if MismatchType.INTERMEDIATE in mismatch_types:
        intermediate_abx = [
            m.antibiotic.medication_name
            for m in mismatches
            if m.mismatch_type == MismatchType.INTERMEDIATE
        ]
        if susceptible_names:
            return (
                f"Intermediate susceptibility to {', '.join(intermediate_abx)}. "
                f"Consider dose optimization or switch to: {', '.join(susceptible_names)}."
            )
        else:
            return (
                f"Intermediate susceptibility to {', '.join(intermediate_abx)}. "
                f"Consider dose optimization or ID consult."
            )

    if MismatchType.NO_COVERAGE in mismatch_types:
        if susceptible_names:
            return (
                f"Patient not on active antibiotics. "
                f"Susceptible options: {', '.join(susceptible_names)}."
            )
        else:
            return "Patient not on active antibiotics - review culture and consider treatment."

    return "Review susceptibility results and consider therapy adjustment."


def assess_mismatch(
    patient: Patient,
    culture: CultureWithSusceptibilities,
    antibiotics: list[Antibiotic],
) -> MismatchAssessment:
    """
    Complete assessment of drug-bug mismatch for a patient/culture.

    Returns MismatchAssessment with detected mismatches and recommendations.
    """
    mismatches = check_coverage(culture, antibiotics)
    recommendation = get_recommendation(culture, mismatches)

    assessment = MismatchAssessment(
        patient=patient,
        culture=culture,
        current_antibiotics=antibiotics,
        mismatches=mismatches,
        recommendation=recommendation,
    )

    # Set severity based on mismatches
    assessment.severity = assessment.get_highest_severity()

    return assessment


def should_alert(assessment: MismatchAssessment) -> bool:
    """Determine if an alert should be generated for this assessment."""
    return assessment.has_mismatches()
