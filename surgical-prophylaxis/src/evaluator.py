"""
Surgical prophylaxis compliance evaluator.

Evaluates surgical cases against prophylaxis guidelines to determine
bundle compliance for each element:
1. Indication appropriateness
2. Agent selection
3. Timing (within 60/120 min of incision)
4. Weight-based dosing
5. Intraoperative redosing
6. Timely discontinuation
"""

from datetime import datetime, timedelta
from typing import Optional

from .config import (
    EXTENDED_WINDOW_ANTIBIOTICS,
    NO_REDOSE_ANTIBIOTICS,
    GuidelinesConfig,
    get_config,
)
from .models import (
    ComplianceStatus,
    ElementResult,
    MedicationAdministration,
    ProcedureCategory,
    ProphylaxisEvaluation,
    SurgicalCase,
)


class ProphylaxisEvaluator:
    """
    Evaluates surgical cases for prophylaxis compliance.

    Checks each bundle element against evidence-based guidelines
    (ASHP/IDSA/SHEA/SIS 2013) and local CCHMC protocols.
    """

    def __init__(self, config: Optional[GuidelinesConfig] = None):
        self.config = config or get_config()

    def evaluate_case(self, case: SurgicalCase) -> ProphylaxisEvaluation:
        """
        Evaluate a surgical case for prophylaxis compliance.

        Args:
            case: SurgicalCase with procedure and medication data

        Returns:
            ProphylaxisEvaluation with element-level and bundle-level results
        """
        # Check for exclusions first
        exclusion = self._check_exclusions(case)
        if exclusion:
            return self._create_excluded_evaluation(case, exclusion)

        # Evaluate each element
        indication = self._evaluate_indication(case)
        agent = self._evaluate_agent_selection(case)
        timing = self._evaluate_timing(case)
        dosing = self._evaluate_dosing(case)
        redosing = self._evaluate_redosing(case)
        discontinuation = self._evaluate_discontinuation(case)

        # Calculate summary
        elements = [indication, agent, timing, dosing, redosing, discontinuation]
        applicable = [e for e in elements if e.status not in
                     (ComplianceStatus.NOT_APPLICABLE, ComplianceStatus.UNABLE_TO_ASSESS)]
        met = [e for e in applicable if e.status == ComplianceStatus.MET]

        elements_met = len(met)
        elements_total = len(applicable)
        compliance_score = (elements_met / elements_total * 100) if elements_total > 0 else 0
        bundle_compliant = elements_met == elements_total and elements_total > 0

        # Collect recommendations from non-met elements
        recommendations = []
        flags = []
        for elem in elements:
            if elem.status == ComplianceStatus.NOT_MET and elem.recommendation:
                recommendations.append(elem.recommendation)
            if elem.status == ComplianceStatus.NOT_MET:
                flags.append(f"{elem.element_name}: {elem.status.value}")

        return ProphylaxisEvaluation(
            case_id=case.case_id,
            patient_mrn=case.patient_mrn,
            encounter_id=case.encounter_id,
            evaluation_time=datetime.now(),
            indication=indication,
            agent_selection=agent,
            timing=timing,
            dosing=dosing,
            redosing=redosing,
            discontinuation=discontinuation,
            bundle_compliant=bundle_compliant,
            compliance_score=compliance_score,
            elements_met=elements_met,
            elements_total=elements_total,
            flags=flags,
            recommendations=recommendations,
        )

    def _check_exclusions(self, case: SurgicalCase) -> Optional[str]:
        """Check if case should be excluded from compliance measurement."""
        if case.is_emergency:
            return "Emergency surgery - timing may not be achievable"
        if case.already_on_therapeutic_antibiotics:
            return "Patient already on therapeutic antibiotics"
        if case.documented_infection:
            return "Documented infection - prophylaxis not applicable"
        return None

    def _create_excluded_evaluation(
        self, case: SurgicalCase, reason: str
    ) -> ProphylaxisEvaluation:
        """Create an evaluation result for excluded cases."""
        na_result = ElementResult(
            element_name="",
            status=ComplianceStatus.NOT_APPLICABLE,
            details=f"Excluded: {reason}",
        )
        return ProphylaxisEvaluation(
            case_id=case.case_id,
            patient_mrn=case.patient_mrn,
            encounter_id=case.encounter_id,
            evaluation_time=datetime.now(),
            indication=ElementResult("Indication", ComplianceStatus.NOT_APPLICABLE, reason),
            agent_selection=ElementResult("Agent Selection", ComplianceStatus.NOT_APPLICABLE, reason),
            timing=ElementResult("Timing", ComplianceStatus.NOT_APPLICABLE, reason),
            dosing=ElementResult("Dosing", ComplianceStatus.NOT_APPLICABLE, reason),
            redosing=ElementResult("Redosing", ComplianceStatus.NOT_APPLICABLE, reason),
            discontinuation=ElementResult("Discontinuation", ComplianceStatus.NOT_APPLICABLE, reason),
            bundle_compliant=True,  # Excluded cases are not failures
            compliance_score=100.0,
            elements_met=0,
            elements_total=0,
            excluded=True,
            exclusion_reason=reason,
        )

    def _evaluate_indication(self, case: SurgicalCase) -> ElementResult:
        """
        Evaluate if prophylaxis indication was appropriate.

        Prophylaxis should be given for procedures that require it,
        AND withheld for procedures that don't.
        """
        # Find procedure requirements from CPT codes
        requirements = None
        for cpt in case.cpt_codes:
            req = self.config.get_procedure_requirements(cpt)
            if req:
                requirements = req
                break

        if requirements is None:
            return ElementResult(
                element_name="Indication",
                status=ComplianceStatus.UNABLE_TO_ASSESS,
                details=f"CPT codes not in guidelines: {case.cpt_codes}",
                recommendation="Review procedure requirements manually",
            )

        prophylaxis_given = len(case.prophylaxis_administrations) > 0 or len(case.prophylaxis_orders) > 0
        prophylaxis_indicated = requirements.prophylaxis_indicated

        if prophylaxis_indicated and prophylaxis_given:
            return ElementResult(
                element_name="Indication",
                status=ComplianceStatus.MET,
                details=f"Prophylaxis given for {requirements.procedure_name} (indicated)",
            )
        elif not prophylaxis_indicated and not prophylaxis_given:
            return ElementResult(
                element_name="Indication",
                status=ComplianceStatus.MET,
                details=f"Prophylaxis appropriately withheld for {requirements.procedure_name}",
            )
        elif prophylaxis_indicated and not prophylaxis_given:
            return ElementResult(
                element_name="Indication",
                status=ComplianceStatus.NOT_MET,
                details=f"No prophylaxis given for {requirements.procedure_name} (prophylaxis indicated)",
                recommendation=f"Prophylaxis recommended: {requirements.first_line_agents}",
            )
        else:  # not indicated but given
            return ElementResult(
                element_name="Indication",
                status=ComplianceStatus.NOT_MET,
                details=f"Prophylaxis given for {requirements.procedure_name} (not indicated per guidelines)",
                recommendation="Consider discontinuing - prophylaxis not routinely indicated for this procedure",
            )

    def _evaluate_agent_selection(self, case: SurgicalCase) -> ElementResult:
        """
        Evaluate if the antibiotic selection matches guidelines.
        """
        if not case.prophylaxis_administrations:
            # No prophylaxis given - check if it was indicated
            requirements = None
            for cpt in case.cpt_codes:
                req = self.config.get_procedure_requirements(cpt)
                if req:
                    requirements = req
                    break

            if requirements and not requirements.prophylaxis_indicated:
                return ElementResult(
                    element_name="Agent Selection",
                    status=ComplianceStatus.NOT_APPLICABLE,
                    details="Prophylaxis not indicated for this procedure",
                )
            else:
                return ElementResult(
                    element_name="Agent Selection",
                    status=ComplianceStatus.NOT_MET,
                    details="No prophylaxis administered",
                    recommendation="Administer recommended prophylaxis",
                )

        # Get procedure requirements
        requirements = None
        for cpt in case.cpt_codes:
            req = self.config.get_procedure_requirements(cpt)
            if req:
                requirements = req
                break

        if requirements is None:
            return ElementResult(
                element_name="Agent Selection",
                status=ComplianceStatus.UNABLE_TO_ASSESS,
                details=f"CPT codes not in guidelines: {case.cpt_codes}",
            )

        # Get list of acceptable agents
        if case.has_beta_lactam_allergy:
            acceptable_agents = requirements.alternative_agents
        else:
            acceptable_agents = requirements.first_line_agents
            # Add MRSA coverage if indicated
            if requirements.mrsa_high_risk_add and case.mrsa_colonized:
                acceptable_agents = acceptable_agents + [requirements.mrsa_high_risk_add]

        # Check agents given
        agents_given = [admin.medication_name.lower() for admin in case.prophylaxis_administrations]
        acceptable_lower = [a.lower() for a in acceptable_agents]

        # Check if all acceptable agents are covered
        matched = any(agent in acceptable_lower for agent in agents_given)

        if matched:
            return ElementResult(
                element_name="Agent Selection",
                status=ComplianceStatus.MET,
                details=f"Appropriate agent(s) given: {', '.join(agents_given)}",
                data={"agents_given": agents_given, "acceptable": acceptable_agents},
            )
        else:
            return ElementResult(
                element_name="Agent Selection",
                status=ComplianceStatus.NOT_MET,
                details=f"Agent mismatch: given {agents_given}, expected {acceptable_agents}",
                recommendation=f"Recommended agents: {', '.join(acceptable_agents)}",
                data={"agents_given": agents_given, "acceptable": acceptable_agents},
            )

    def _evaluate_timing(self, case: SurgicalCase) -> ElementResult:
        """
        Evaluate if prophylaxis was given within the appropriate window.

        Standard: 60 minutes before incision
        Extended: 120 minutes for vancomycin/fluoroquinolones
        """
        if not case.prophylaxis_administrations:
            # Check if indicated
            requirements = None
            for cpt in case.cpt_codes:
                req = self.config.get_procedure_requirements(cpt)
                if req:
                    requirements = req
                    break

            if requirements and not requirements.prophylaxis_indicated:
                return ElementResult(
                    element_name="Timing",
                    status=ComplianceStatus.NOT_APPLICABLE,
                    details="Prophylaxis not indicated",
                )
            return ElementResult(
                element_name="Timing",
                status=ComplianceStatus.NOT_MET,
                details="No prophylaxis administered",
            )

        if not case.actual_incision_time:
            return ElementResult(
                element_name="Timing",
                status=ComplianceStatus.PENDING,
                details="Surgery not yet started - incision time not recorded",
            )

        # Check timing for each administered antibiotic
        timing_results = []
        all_met = True

        for admin in case.prophylaxis_administrations:
            # Calculate minutes before incision
            delta = case.actual_incision_time - admin.admin_time
            minutes_before = delta.total_seconds() / 60

            # Determine window based on antibiotic
            med_lower = admin.medication_name.lower()
            if any(ext in med_lower for ext in EXTENDED_WINDOW_ANTIBIOTICS):
                max_window = 120
            else:
                max_window = 60

            # Check compliance
            if 0 < minutes_before <= max_window:
                timing_results.append(
                    f"{admin.medication_name}: {minutes_before:.0f} min before incision (compliant)"
                )
            elif minutes_before <= 0:
                timing_results.append(
                    f"{admin.medication_name}: given {abs(minutes_before):.0f} min AFTER incision"
                )
                all_met = False
            else:
                timing_results.append(
                    f"{admin.medication_name}: {minutes_before:.0f} min before incision (>window)"
                )
                all_met = False

        if all_met:
            return ElementResult(
                element_name="Timing",
                status=ComplianceStatus.MET,
                details="; ".join(timing_results),
            )
        else:
            return ElementResult(
                element_name="Timing",
                status=ComplianceStatus.NOT_MET,
                details="; ".join(timing_results),
                recommendation="Antibiotics should be given within 60 min (120 min for vancomycin) before incision",
            )

    def _evaluate_dosing(self, case: SurgicalCase) -> ElementResult:
        """
        Evaluate if doses were appropriate for patient weight.
        """
        if not case.prophylaxis_administrations:
            requirements = None
            for cpt in case.cpt_codes:
                req = self.config.get_procedure_requirements(cpt)
                if req:
                    requirements = req
                    break

            if requirements and not requirements.prophylaxis_indicated:
                return ElementResult(
                    element_name="Dosing",
                    status=ComplianceStatus.NOT_APPLICABLE,
                    details="Prophylaxis not indicated",
                )
            return ElementResult(
                element_name="Dosing",
                status=ComplianceStatus.NOT_MET,
                details="No prophylaxis administered",
            )

        if not case.patient_weight_kg:
            return ElementResult(
                element_name="Dosing",
                status=ComplianceStatus.UNABLE_TO_ASSESS,
                details="Patient weight not documented",
                recommendation="Document patient weight for dosing assessment",
            )

        dosing_results = []
        all_met = True
        is_pediatric = case.patient_age_years is not None and case.patient_age_years < 18

        for admin in case.prophylaxis_administrations:
            dosing_info = self.config.get_dosing_info(admin.medication_name)
            if not dosing_info:
                dosing_results.append(f"{admin.medication_name}: no dosing data available")
                continue

            # Calculate expected dose
            if is_pediatric:
                expected = min(
                    case.patient_weight_kg * dosing_info.pediatric_mg_per_kg,
                    dosing_info.pediatric_max_mg,
                )
            else:
                if (
                    dosing_info.adult_high_weight_mg
                    and case.patient_weight_kg > dosing_info.adult_high_weight_threshold_kg
                ):
                    expected = dosing_info.adult_high_weight_mg
                else:
                    expected = dosing_info.adult_standard_mg

            # Allow 10% variance
            dose_given = admin.dose_mg
            if 0.9 * expected <= dose_given <= 1.1 * expected:
                dosing_results.append(
                    f"{admin.medication_name}: {dose_given}mg appropriate for {case.patient_weight_kg}kg"
                )
            else:
                dosing_results.append(
                    f"{admin.medication_name}: {dose_given}mg given, expected ~{expected:.0f}mg"
                )
                all_met = False

        if all_met:
            return ElementResult(
                element_name="Dosing",
                status=ComplianceStatus.MET,
                details="; ".join(dosing_results),
            )
        else:
            return ElementResult(
                element_name="Dosing",
                status=ComplianceStatus.NOT_MET,
                details="; ".join(dosing_results),
                recommendation="Adjust dose based on patient weight",
            )

    def _evaluate_redosing(self, case: SurgicalCase) -> ElementResult:
        """
        Evaluate if intraoperative redosing was given for prolonged surgery.
        """
        if not case.prophylaxis_administrations:
            requirements = None
            for cpt in case.cpt_codes:
                req = self.config.get_procedure_requirements(cpt)
                if req:
                    requirements = req
                    break

            if requirements and not requirements.prophylaxis_indicated:
                return ElementResult(
                    element_name="Redosing",
                    status=ComplianceStatus.NOT_APPLICABLE,
                    details="Prophylaxis not indicated",
                )
            return ElementResult(
                element_name="Redosing",
                status=ComplianceStatus.NOT_MET,
                details="No prophylaxis administered",
            )

        if not case.surgery_end_time or not case.actual_incision_time:
            return ElementResult(
                element_name="Redosing",
                status=ComplianceStatus.PENDING,
                details="Surgery still in progress or end time not recorded",
            )

        duration_hours = case.surgery_duration_hours
        if duration_hours is None:
            return ElementResult(
                element_name="Redosing",
                status=ComplianceStatus.UNABLE_TO_ASSESS,
                details="Unable to calculate surgery duration",
            )

        # Check each antibiotic's redosing requirement
        redose_results = []
        all_met = True

        # Group administrations by medication
        med_admins: dict[str, list[MedicationAdministration]] = {}
        for admin in case.prophylaxis_administrations:
            med_name = admin.medication_name.lower()
            if med_name not in med_admins:
                med_admins[med_name] = []
            med_admins[med_name].append(admin)

        for med_name, admins in med_admins.items():
            # Check if this antibiotic needs redosing
            if any(no_redose in med_name for no_redose in NO_REDOSE_ANTIBIOTICS):
                redose_results.append(f"{med_name}: redosing not required")
                continue

            interval = self.config.get_redose_interval(med_name)
            if interval is None:
                redose_results.append(f"{med_name}: no redosing data")
                continue

            # Calculate expected doses
            expected_doses = 1 + int(duration_hours / interval)
            actual_doses = len(admins)

            if actual_doses >= expected_doses:
                redose_results.append(
                    f"{med_name}: {actual_doses} doses for {duration_hours:.1f}h surgery (compliant)"
                )
            else:
                redose_results.append(
                    f"{med_name}: {actual_doses} doses, expected {expected_doses} for {duration_hours:.1f}h"
                )
                all_met = False

        if not redose_results:
            return ElementResult(
                element_name="Redosing",
                status=ComplianceStatus.NOT_APPLICABLE,
                details="No antibiotics requiring redosing",
            )

        if all_met:
            return ElementResult(
                element_name="Redosing",
                status=ComplianceStatus.MET,
                details="; ".join(redose_results),
            )
        else:
            return ElementResult(
                element_name="Redosing",
                status=ComplianceStatus.NOT_MET,
                details="; ".join(redose_results),
                recommendation="Redose antibiotics per interval for prolonged surgery",
            )

    def _evaluate_discontinuation(self, case: SurgicalCase) -> ElementResult:
        """
        Evaluate if prophylaxis was discontinued within guideline timeframe.

        Standard: 24 hours after surgery end
        Cardiac: 48 hours after surgery end
        """
        if not case.prophylaxis_administrations:
            requirements = None
            for cpt in case.cpt_codes:
                req = self.config.get_procedure_requirements(cpt)
                if req:
                    requirements = req
                    break

            if requirements and not requirements.prophylaxis_indicated:
                return ElementResult(
                    element_name="Discontinuation",
                    status=ComplianceStatus.NOT_APPLICABLE,
                    details="Prophylaxis not indicated",
                )
            return ElementResult(
                element_name="Discontinuation",
                status=ComplianceStatus.NOT_MET,
                details="No prophylaxis administered",
            )

        if not case.surgery_end_time:
            return ElementResult(
                element_name="Discontinuation",
                status=ComplianceStatus.PENDING,
                details="Surgery not yet complete",
            )

        # Determine duration limit based on procedure category
        duration_limit = self.config.get_duration_limit(case.procedure_category)

        # Find the last dose time
        last_dose_time = max(admin.admin_time for admin in case.prophylaxis_administrations)
        hours_since_surgery = (last_dose_time - case.surgery_end_time).total_seconds() / 3600

        # If last dose was before or within window after surgery end, compliant
        if hours_since_surgery <= duration_limit:
            return ElementResult(
                element_name="Discontinuation",
                status=ComplianceStatus.MET,
                details=f"Last dose {hours_since_surgery:.1f}h after surgery end (limit: {duration_limit}h)",
            )
        else:
            return ElementResult(
                element_name="Discontinuation",
                status=ComplianceStatus.NOT_MET,
                details=f"Prophylaxis continued {hours_since_surgery:.1f}h after surgery (limit: {duration_limit}h)",
                recommendation=f"Discontinue prophylaxis - exceeded {duration_limit}h limit",
            )

    def evaluate_batch(self, cases: list[SurgicalCase]) -> list[ProphylaxisEvaluation]:
        """Evaluate multiple cases."""
        return [self.evaluate_case(case) for case in cases]
