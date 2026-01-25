"""
Surgical Prophylaxis Monitor.

Monitors surgical cases for prophylaxis compliance and generates alerts
for non-compliant cases.
"""

import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from typing import Optional

# Add parent paths for imports
sys.path.insert(0, str(__file__).rsplit("/", 3)[0])

from common.alert_store.models import AlertType, AlertStatus
from common.alert_store.store import AlertStore

from .config import ALERT_DB_PATH, get_config
from .database import ProphylaxisDatabase
from .evaluator import ProphylaxisEvaluator
from .fhir_client import FHIRClient
from .models import ComplianceStatus, ProphylaxisEvaluation, SurgicalCase


logger = logging.getLogger(__name__)


class SurgicalProphylaxisMonitor:
    """
    Monitors surgical cases for prophylaxis compliance.

    Evaluates cases against guidelines and creates alerts for:
    - Missing prophylaxis when indicated
    - Wrong agent selection
    - Timing outside window
    - Incorrect dosing
    - Missing redosing
    - Prolonged duration
    """

    def __init__(
        self,
        fhir_client: Optional[FHIRClient] = None,
        alert_store: Optional[AlertStore] = None,
        db: Optional[ProphylaxisDatabase] = None,
    ):
        self.fhir_client = fhir_client or FHIRClient()
        self.alert_store = alert_store or AlertStore(ALERT_DB_PATH)
        self.db = db or ProphylaxisDatabase()
        self.config = get_config()
        self.evaluator = ProphylaxisEvaluator(self.config)

    def run_once(
        self,
        hours_back: int = 24,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[ProphylaxisEvaluation]:
        """
        Run one monitoring cycle.

        Args:
            hours_back: How many hours back to look for procedures
            dry_run: If True, don't create alerts
            verbose: If True, print detailed output

        Returns:
            List of evaluations performed
        """
        if verbose:
            logging.basicConfig(level=logging.INFO)

        logger.info(f"Starting surgical prophylaxis monitor (looking back {hours_back}h)")

        # Get recent surgical procedures
        date_from = datetime.now() - timedelta(hours=hours_back)
        date_to = datetime.now()

        procedures = self.fhir_client.get_surgical_procedures(
            date_from=date_from,
            date_to=date_to,
        )

        logger.info(f"Found {len(procedures)} procedures to evaluate")

        evaluations = []
        alerts_created = 0

        for procedure in procedures:
            try:
                # Build surgical case from FHIR data
                case = self.fhir_client.build_surgical_case(procedure)

                if verbose:
                    logger.info(f"Evaluating case {case.case_id}: {case.procedure_description}")

                # Save case to database
                self.db.save_case(case)

                # Evaluate compliance
                evaluation = self.evaluator.evaluate_case(case)
                evaluations.append(evaluation)

                # Save evaluation
                eval_id = self.db.save_evaluation(evaluation)

                if verbose:
                    self._print_evaluation_summary(evaluation)

                # Create alerts for non-compliant elements
                if not evaluation.bundle_compliant and not evaluation.excluded:
                    if not dry_run:
                        alert_id = self._create_alert(case, evaluation, eval_id)
                        if alert_id:
                            alerts_created += 1
                            if verbose:
                                logger.info(f"  Created alert {alert_id}")
                    else:
                        if verbose:
                            logger.info("  [DRY RUN] Would create alert")

            except Exception as e:
                logger.error(f"Error evaluating procedure {procedure.get('id')}: {e}")
                continue

        logger.info(
            f"Completed: {len(evaluations)} evaluations, "
            f"{alerts_created} alerts created"
        )

        return evaluations

    def _create_alert(
        self,
        case: SurgicalCase,
        evaluation: ProphylaxisEvaluation,
        eval_id: int,
    ) -> Optional[str]:
        """
        Create an alert in the common alert store for non-compliant case.

        Returns alert ID if created, None otherwise.
        """
        # Check for existing active alert for this case
        existing = self._get_existing_alert(case.case_id)
        if existing:
            logger.info(f"Alert already exists for case {case.case_id}")
            return None

        # Determine severity based on what's not met
        severity = self._determine_severity(evaluation)

        # Build alert content
        not_met_elements = [
            e for e in evaluation.elements
            if e.status == ComplianceStatus.NOT_MET
        ]

        content = {
            "case_id": case.case_id,
            "encounter_id": case.encounter_id,
            "procedure": case.procedure_description,
            "procedure_category": case.procedure_category.value if case.procedure_category else None,
            "cpt_codes": case.cpt_codes,
            "scheduled_time": case.scheduled_or_time.isoformat() if case.scheduled_or_time else None,
            "incision_time": case.actual_incision_time.isoformat() if case.actual_incision_time else None,
            "surgery_end_time": case.surgery_end_time.isoformat() if case.surgery_end_time else None,
            "compliance_score": evaluation.compliance_score,
            "elements_met": evaluation.elements_met,
            "elements_total": evaluation.elements_total,
            "not_met_elements": [
                {
                    "name": e.element_name,
                    "details": e.details,
                    "recommendation": e.recommendation,
                }
                for e in not_met_elements
            ],
            "recommendations": evaluation.recommendations,
            "evaluation_id": eval_id,
        }

        # Build title and summary
        element_names = [e.element_name for e in not_met_elements]
        title = f"Surgical Prophylaxis: {', '.join(element_names)}"
        summary = (
            f"{case.procedure_description} - "
            f"{evaluation.elements_met}/{evaluation.elements_total} elements met. "
            f"Issues: {', '.join(element_names)}"
        )

        # Create alert
        alert_id = str(uuid.uuid4())

        self.alert_store.create_alert(
            alert_id=alert_id,
            alert_type=AlertType.SURGICAL_PROPHYLAXIS,
            source_id=case.case_id,
            severity=severity,
            patient_id=case.patient_mrn,
            patient_mrn=case.patient_mrn,
            title=title,
            summary=summary,
            content=content,
        )

        # Also save to local prophylaxis database
        self.db.save_alert(
            case_id=case.case_id,
            alert_type="surgical_prophylaxis",
            severity=severity,
            message=summary,
            element_name=element_names[0] if element_names else None,
            evaluation_id=eval_id,
            external_alert_id=alert_id,
        )

        return alert_id

    def _determine_severity(self, evaluation: ProphylaxisEvaluation) -> str:
        """Determine alert severity based on non-compliant elements."""
        # Critical: Missing prophylaxis entirely or given after incision
        if evaluation.indication.status == ComplianceStatus.NOT_MET:
            return "critical"

        # Check timing - after incision is critical
        if evaluation.timing.status == ComplianceStatus.NOT_MET:
            details = evaluation.timing.details.lower()
            if "after incision" in details:
                return "critical"
            return "warning"

        # Warning for agent/dosing issues
        if (evaluation.agent_selection.status == ComplianceStatus.NOT_MET or
                evaluation.dosing.status == ComplianceStatus.NOT_MET):
            return "warning"

        # Info for duration/redosing
        return "info"

    def _get_existing_alert(self, case_id: str) -> bool:
        """Check if an active alert exists for this case."""
        alerts = self.alert_store.get_alerts_by_status(
            status=AlertStatus.PENDING,
            alert_type=AlertType.SURGICAL_PROPHYLAXIS,
        )
        for alert in alerts:
            if alert.source_id == case_id:
                return True

        alerts = self.alert_store.get_alerts_by_status(
            status=AlertStatus.ACKNOWLEDGED,
            alert_type=AlertType.SURGICAL_PROPHYLAXIS,
        )
        for alert in alerts:
            if alert.source_id == case_id:
                return True

        return False

    def _print_evaluation_summary(self, evaluation: ProphylaxisEvaluation):
        """Print a summary of an evaluation."""
        status = "COMPLIANT" if evaluation.bundle_compliant else "NON-COMPLIANT"
        if evaluation.excluded:
            status = f"EXCLUDED ({evaluation.exclusion_reason})"

        print(f"\n  Case: {evaluation.case_id}")
        print(f"  Status: {status}")
        print(f"  Score: {evaluation.compliance_score:.1f}% ({evaluation.elements_met}/{evaluation.elements_total})")

        for elem in evaluation.elements:
            icon = "✓" if elem.status == ComplianceStatus.MET else "✗"
            if elem.status in (ComplianceStatus.NOT_APPLICABLE, ComplianceStatus.PENDING):
                icon = "-"
            print(f"    {icon} {elem.element_name}: {elem.details}")

    def check_prolonged_duration(self, hours_threshold: int = 24) -> list[dict]:
        """
        Check for cases with prophylaxis continuing beyond threshold.

        This is typically run as a separate check for ongoing cases.

        Args:
            hours_threshold: Hours after surgery to flag

        Returns:
            List of cases with prolonged prophylaxis
        """
        # Query database for cases where:
        # - Surgery completed > threshold hours ago
        # - Has active prophylaxis orders
        cutoff = datetime.now() - timedelta(hours=hours_threshold)

        # This would typically query the FHIR server for active orders
        # For now, return from local database
        return self.db.get_non_compliant_cases(
            start_date=cutoff - timedelta(days=7),
            end_date=datetime.now(),
            element="discontinuation",
        )


def main():
    """CLI entry point for the monitor."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Surgical Prophylaxis Compliance Monitor"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours to look back for procedures (default: 24)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create alerts, just evaluate",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed output",
    )

    args = parser.parse_args()

    monitor = SurgicalProphylaxisMonitor()

    if args.once:
        evaluations = monitor.run_once(
            hours_back=args.hours,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

        # Print summary
        compliant = sum(1 for e in evaluations if e.bundle_compliant)
        excluded = sum(1 for e in evaluations if e.excluded)
        non_compliant = len(evaluations) - compliant - excluded

        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Total cases evaluated: {len(evaluations)}")
        print(f"  Compliant: {compliant}")
        print(f"  Non-compliant: {non_compliant}")
        print(f"  Excluded: {excluded}")

        if evaluations:
            avg_score = sum(e.compliance_score for e in evaluations) / len(evaluations)
            print(f"Average compliance score: {avg_score:.1f}%")
    else:
        print("Use --once to run a single monitoring cycle")


if __name__ == "__main__":
    main()
