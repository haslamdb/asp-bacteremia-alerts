#!/usr/bin/env python3
"""Demo script for SSI (Surgical Site Infection) detection and classification.

This script demonstrates the SSI monitoring pipeline:
1. Candidate detection from surgical procedures
2. LLM extraction of SSI-relevant clinical information
3. Rules engine classification

Usage:
    python scripts/demo_ssi.py --scenario all
    python scripts/demo_ssi.py --scenario superficial
    python scripts/demo_ssi.py --scenario deep
    python scripts/demo_ssi.py --scenario organ_space
    python scripts/demo_ssi.py --list
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rules.ssi_engine import SSIRulesEngine
from rules.ssi_schemas import (
    SSIExtraction,
    SSIStructuredData,
    SSIClassification,
    SSIType,
    WoundAssessmentExtraction,
    SuperficialSSIFindings,
    DeepSSIFindings,
    OrganSpaceSSIFindings,
    ReoperationFindings,
)
from rules.schemas import ConfidenceLevel
from rules.nhsn_criteria import NHSN_OPERATIVE_CATEGORIES, get_wound_class_name

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Demo Scenarios
# =============================================================================

SCENARIOS = {
    "superficial_purulent": {
        "name": "Superficial SSI - Purulent Drainage",
        "description": "Post-colectomy patient with purulent drainage from incision",
        "structured_data": SSIStructuredData(
            procedure_code="44140",
            procedure_name="Sigmoid colectomy",
            procedure_date=datetime.now() - timedelta(days=8),
            nhsn_category="COLO",
            wound_class=2,
            duration_minutes=180,
            asa_score=2,
            days_post_op=8,
            surveillance_window_days=30,
        ),
        "extraction": SSIExtraction(
            wound_assessments=[
                WoundAssessmentExtraction(
                    drainage_present=ConfidenceLevel.DEFINITE,
                    drainage_type="purulent",
                    drainage_amount="moderate",
                    erythema_present=ConfidenceLevel.DEFINITE,
                    erythema_extent="2cm from incision",
                    assessment_date=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                )
            ],
            superficial_findings=SuperficialSSIFindings(
                purulent_drainage_superficial=ConfidenceLevel.DEFINITE,
                purulent_drainage_quote="Yellow-green purulent discharge from midline incision",
                erythema=ConfidenceLevel.DEFINITE,
                pain_or_tenderness=ConfidenceLevel.DEFINITE,
            ),
            fever_documented=ConfidenceLevel.DEFINITE,
            fever_max_celsius=38.5,
            documentation_quality="detailed",
            notes_reviewed_count=5,
            clinical_team_impression="Superficial wound infection at surgical site",
        ),
        "expected": SSIClassification.SUPERFICIAL_SSI,
    },
    "superficial_culture": {
        "name": "Superficial SSI - Positive Culture",
        "description": "Post-cholecystectomy with positive wound culture",
        "structured_data": SSIStructuredData(
            procedure_code="47562",
            procedure_name="Laparoscopic cholecystectomy",
            procedure_date=datetime.now() - timedelta(days=5),
            nhsn_category="CHOL",
            wound_class=2,
            duration_minutes=60,
            asa_score=2,
            wound_culture_positive=True,
            wound_culture_organism="Staphylococcus aureus",
            wound_culture_date=datetime.now() - timedelta(days=1),
            days_post_op=5,
            surveillance_window_days=30,
        ),
        "extraction": SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                organisms_from_superficial_culture=ConfidenceLevel.DEFINITE,
                organism_identified="Staphylococcus aureus",
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        ),
        "expected": SSIClassification.SUPERFICIAL_SSI,
    },
    "deep_dehiscence_fever": {
        "name": "Deep SSI - Fascial Dehiscence with Fever",
        "description": "Post-colectomy patient with fascial dehiscence and fever",
        "structured_data": SSIStructuredData(
            procedure_code="44140",
            procedure_name="Right hemicolectomy",
            procedure_date=datetime.now() - timedelta(days=12),
            nhsn_category="COLO",
            wound_class=3,  # Contaminated
            duration_minutes=240,
            asa_score=3,
            days_post_op=12,
            surveillance_window_days=30,
        ),
        "extraction": SSIExtraction(
            wound_assessments=[
                WoundAssessmentExtraction(
                    wound_dehisced=ConfidenceLevel.DEFINITE,
                    dehiscence_type="fascial",
                    drainage_present=ConfidenceLevel.DEFINITE,
                    drainage_type="serosanguinous",
                )
            ],
            deep_findings=DeepSSIFindings(
                deep_incision_dehisces=ConfidenceLevel.DEFINITE,
                fever_greater_38=ConfidenceLevel.DEFINITE,
                fever_value_celsius=39.2,
                localized_pain_deep=ConfidenceLevel.DEFINITE,
            ),
            fever_documented=ConfidenceLevel.DEFINITE,
            fever_max_celsius=39.2,
            documentation_quality="detailed",
            notes_reviewed_count=6,
            clinical_team_impression="Deep wound infection, fascial dehiscence",
        ),
        "expected": SSIClassification.DEEP_SSI,
    },
    "deep_abscess_imaging": {
        "name": "Deep SSI - Abscess on CT",
        "description": "Post-appendectomy patient with wound collection on CT",
        "structured_data": SSIStructuredData(
            procedure_code="44950",
            procedure_name="Appendectomy, laparoscopic",
            procedure_date=datetime.now() - timedelta(days=10),
            nhsn_category="APPY",
            wound_class=3,
            duration_minutes=90,
            asa_score=2,
            days_post_op=10,
            surveillance_window_days=30,
        ),
        "extraction": SSIExtraction(
            deep_findings=DeepSSIFindings(
                abscess_on_imaging=ConfidenceLevel.DEFINITE,
                imaging_type="CT",
            ),
            documentation_quality="adequate",
            notes_reviewed_count=4,
            clinical_team_impression="Abscess at operative site, will proceed with drainage",
        ),
        "expected": SSIClassification.DEEP_SSI,
    },
    "organ_space_intraabdominal": {
        "name": "Organ/Space SSI - Intra-abdominal Abscess",
        "description": "Post-colectomy patient with intra-abdominal abscess on CT",
        "structured_data": SSIStructuredData(
            procedure_code="44140",
            procedure_name="Low anterior resection",
            procedure_date=datetime.now() - timedelta(days=14),
            nhsn_category="REC",
            wound_class=2,
            duration_minutes=280,
            asa_score=3,
            days_post_op=14,
            surveillance_window_days=30,
        ),
        "extraction": SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                abscess_on_imaging=ConfidenceLevel.DEFINITE,
                imaging_type="CT",
                imaging_findings="5cm pelvic abscess adjacent to anastomosis",
                organ_space_involved="pelvis",
                organ_space_nhsn_code="IAB",
            ),
            fever_documented=ConfidenceLevel.DEFINITE,
            fever_max_celsius=38.8,
            leukocytosis_documented=ConfidenceLevel.DEFINITE,
            wbc_value=15.2,
            documentation_quality="detailed",
            notes_reviewed_count=6,
            clinical_team_impression="Pelvic abscess, likely anastomotic leak",
        ),
        "expected": SSIClassification.ORGAN_SPACE_SSI,
    },
    "organ_space_drain": {
        "name": "Organ/Space SSI - Purulent Drain Output",
        "description": "Post-colectomy with purulent output from JP drain",
        "structured_data": SSIStructuredData(
            procedure_code="44140",
            procedure_name="Sigmoid colectomy with diverting ileostomy",
            procedure_date=datetime.now() - timedelta(days=7),
            nhsn_category="COLO",
            wound_class=3,
            duration_minutes=200,
            asa_score=3,
            days_post_op=7,
            surveillance_window_days=30,
        ),
        "extraction": SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                purulent_drainage_drain=ConfidenceLevel.DEFINITE,
                drain_location="JP drain in pelvis",
                organisms_from_organ_space=ConfidenceLevel.DEFINITE,
                organism_identified="Escherichia coli",
                specimen_type="drain fluid",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        ),
        "expected": SSIClassification.ORGAN_SPACE_SSI,
    },
    "organ_space_mediastinitis": {
        "name": "Organ/Space SSI - Mediastinitis post-CABG",
        "description": "Post-CABG patient with mediastinitis",
        "structured_data": SSIStructuredData(
            procedure_code="33533",
            procedure_name="CABG x3 with LIMA",
            procedure_date=datetime.now() - timedelta(days=21),
            nhsn_category="CABG",
            wound_class=1,
            duration_minutes=320,
            asa_score=4,
            implant_used=True,
            implant_type="Sternal wires",
            days_post_op=21,
            surveillance_window_days=90,  # 90 days for CABG with implant
        ),
        "extraction": SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                physician_diagnosis_organ_space_ssi=ConfidenceLevel.DEFINITE,
                diagnosis_quote="Mediastinitis requiring surgical debridement",
                organ_space_involved="mediastinum",
                organ_space_nhsn_code="MED",
            ),
            reoperation=ReoperationFindings(
                reoperation_performed=ConfidenceLevel.DEFINITE,
                reoperation_indication="Sternal wound infection, mediastinitis",
                reoperation_findings="Purulent fluid in mediastinum, sternal instability",
            ),
            fever_documented=ConfidenceLevel.DEFINITE,
            fever_max_celsius=39.5,
            documentation_quality="detailed",
            notes_reviewed_count=8,
        ),
        "expected": SSIClassification.ORGAN_SPACE_SSI,
    },
    "not_ssi_healing_well": {
        "name": "Not SSI - Wound Healing Well",
        "description": "Post-operative patient with wound healing normally",
        "structured_data": SSIStructuredData(
            procedure_code="27447",
            procedure_name="Total knee arthroplasty",
            procedure_date=datetime.now() - timedelta(days=14),
            nhsn_category="KPRO",
            wound_class=1,
            duration_minutes=120,
            asa_score=2,
            implant_used=True,
            days_post_op=14,
            surveillance_window_days=90,
        ),
        "extraction": SSIExtraction(
            wound_assessments=[
                WoundAssessmentExtraction(
                    drainage_present=ConfidenceLevel.NOT_FOUND,
                    erythema_present=ConfidenceLevel.NOT_FOUND,
                    warmth_present=ConfidenceLevel.NOT_FOUND,
                    tenderness_present=ConfidenceLevel.NOT_FOUND,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
            clinical_team_impression="Wound healing well, no signs of infection",
        ),
        "expected": SSIClassification.NOT_SSI,
    },
    "not_eligible_outside_window": {
        "name": "Not Eligible - Outside Surveillance Window",
        "description": "Wound issue 45 days after non-implant procedure",
        "structured_data": SSIStructuredData(
            procedure_code="47562",
            procedure_name="Laparoscopic cholecystectomy",
            procedure_date=datetime.now() - timedelta(days=45),
            nhsn_category="CHOL",
            wound_class=2,
            days_post_op=45,  # Outside 30-day window
            surveillance_window_days=30,
        ),
        "extraction": SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                purulent_drainage_superficial=ConfidenceLevel.DEFINITE,
            ),
            documentation_quality="adequate",
            notes_reviewed_count=2,
        ),
        "expected": SSIClassification.NOT_ELIGIBLE,
    },
}


def run_scenario(scenario_key: str) -> dict:
    """Run a single SSI classification scenario."""
    scenario = SCENARIOS[scenario_key]
    engine = SSIRulesEngine(strict_mode=True)

    logger.info(f"\n{'='*70}")
    logger.info(f"SCENARIO: {scenario['name']}")
    logger.info(f"{'='*70}")
    logger.info(f"Description: {scenario['description']}")

    data = scenario["structured_data"]
    logger.info(f"\nProcedure: {data.procedure_name} ({data.nhsn_category})")
    logger.info(f"Wound Class: {data.wound_class} ({get_wound_class_name(data.wound_class) if data.wound_class else 'N/A'})")
    logger.info(f"Days Post-Op: {data.days_post_op}")
    logger.info(f"Surveillance Window: {data.surveillance_window_days} days")
    if data.implant_used:
        logger.info(f"Implant: Yes ({data.implant_type})")

    # Run classification
    extraction = scenario["extraction"]
    result = engine.classify(extraction, data)

    logger.info(f"\n--- CLASSIFICATION RESULT ---")
    logger.info(f"Classification: {result.classification.value}")
    if result.ssi_type:
        logger.info(f"SSI Type: {result.ssi_type.value}")
    logger.info(f"Confidence: {result.confidence:.2f}")
    logger.info(f"Requires Review: {result.requires_review}")

    if result.review_reasons:
        logger.info(f"\nReview Reasons:")
        for reason in result.review_reasons:
            logger.info(f"  - {reason}")

    logger.info(f"\nReasoning Chain:")
    for step in result.reasoning:
        logger.info(f"  {step}")

    # Check expected vs actual
    expected = scenario["expected"]
    passed = result.classification == expected

    if passed:
        logger.info(f"\n[PASS] Expected: {expected.value}, Got: {result.classification.value}")
    else:
        logger.info(f"\n[FAIL] Expected: {expected.value}, Got: {result.classification.value}")

    return {
        "scenario": scenario_key,
        "name": scenario["name"],
        "passed": passed,
        "expected": expected.value,
        "actual": result.classification.value,
        "confidence": result.confidence,
    }


def run_all_scenarios() -> list[dict]:
    """Run all demo scenarios."""
    results = []
    for key in SCENARIOS:
        results.append(run_scenario(key))

    # Summary
    logger.info(f"\n{'='*70}")
    logger.info("SUMMARY")
    logger.info(f"{'='*70}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)

    logger.info(f"Passed: {passed}/{total}")

    for result in results:
        status = "[PASS]" if result["passed"] else "[FAIL]"
        logger.info(f"  {status} {result['name']}")

    return results


def list_scenarios():
    """List available scenarios."""
    logger.info("Available SSI Demo Scenarios:")
    logger.info("-" * 50)
    for key, scenario in SCENARIOS.items():
        logger.info(f"  {key}: {scenario['name']}")
        logger.info(f"    {scenario['description']}")
        logger.info(f"    Expected: {scenario['expected'].value}")
        logger.info("")


def main():
    parser = argparse.ArgumentParser(
        description="Demo SSI detection and classification scenarios"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        help="Scenario to run (or 'all' for all scenarios)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios",
    )

    args = parser.parse_args()

    if args.list:
        list_scenarios()
        return

    if args.scenario == "all":
        results = run_all_scenarios()
        # Exit with error if any failures
        if not all(r["passed"] for r in results):
            sys.exit(1)
    elif args.scenario in SCENARIOS:
        result = run_scenario(args.scenario)
        if not result["passed"]:
            sys.exit(1)
    else:
        logger.error(f"Unknown scenario: {args.scenario}")
        logger.info("Available scenarios:")
        list_scenarios()
        sys.exit(1)


if __name__ == "__main__":
    main()
