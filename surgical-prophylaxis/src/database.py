"""
Database operations for surgical prophylaxis module.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    ComplianceStatus,
    MedicationAdministration,
    MedicationOrder,
    ProcedureCategory,
    ProphylaxisEvaluation,
    SurgicalCase,
)


class ProphylaxisDatabase:
    """SQLite database for surgical prophylaxis tracking."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Default to ~/.aegis/surgical_prophylaxis.db
            aegis_dir = Path.home() / ".aegis"
            aegis_dir.mkdir(exist_ok=True)
            db_path = str(aegis_dir / "surgical_prophylaxis.db")

        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        schema_path = Path(__file__).parent.parent / "schema.sql"
        if schema_path.exists():
            with open(schema_path) as f:
                schema = f.read()
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(schema)

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- Surgical Cases ---

    def save_case(self, case: SurgicalCase) -> None:
        """Save or update a surgical case."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO surgical_cases (
                    case_id, patient_mrn, encounter_id,
                    primary_cpt, all_cpt_codes, procedure_description,
                    procedure_category, surgeon_id, surgeon_name, location,
                    scheduled_or_time, actual_incision_time, surgery_end_time,
                    patient_weight_kg, patient_age_years,
                    has_beta_lactam_allergy, mrsa_colonized, allergies,
                    is_emergency, already_on_therapeutic_antibiotics,
                    documented_infection, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.patient_mrn,
                    case.encounter_id,
                    case.cpt_codes[0] if case.cpt_codes else None,
                    json.dumps(case.cpt_codes),
                    case.procedure_description,
                    case.procedure_category.value if case.procedure_category else None,
                    case.surgeon_id,
                    case.surgeon_name,
                    case.location,
                    case.scheduled_or_time.isoformat() if case.scheduled_or_time else None,
                    case.actual_incision_time.isoformat() if case.actual_incision_time else None,
                    case.surgery_end_time.isoformat() if case.surgery_end_time else None,
                    case.patient_weight_kg,
                    case.patient_age_years,
                    case.has_beta_lactam_allergy,
                    case.mrsa_colonized,
                    json.dumps(case.allergies),
                    case.is_emergency,
                    case.already_on_therapeutic_antibiotics,
                    case.documented_infection,
                    datetime.now().isoformat(),
                ),
            )

    def get_case(self, case_id: str) -> Optional[SurgicalCase]:
        """Retrieve a surgical case by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM surgical_cases WHERE case_id = ?", (case_id,)
            ).fetchone()

        if not row:
            return None

        return self._row_to_case(row)

    def get_cases_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[SurgicalCase]:
        """Get cases scheduled within a date range."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM surgical_cases
                WHERE scheduled_or_time >= ? AND scheduled_or_time <= ?
                ORDER BY scheduled_or_time
                """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()

        return [self._row_to_case(row) for row in rows]

    def _row_to_case(self, row: sqlite3.Row) -> SurgicalCase:
        """Convert database row to SurgicalCase."""
        return SurgicalCase(
            case_id=row["case_id"],
            patient_mrn=row["patient_mrn"],
            encounter_id=row["encounter_id"],
            cpt_codes=json.loads(row["all_cpt_codes"]) if row["all_cpt_codes"] else [],
            procedure_description=row["procedure_description"] or "",
            procedure_category=(
                ProcedureCategory(row["procedure_category"])
                if row["procedure_category"]
                else ProcedureCategory.OTHER
            ),
            surgeon_id=row["surgeon_id"],
            surgeon_name=row["surgeon_name"],
            location=row["location"],
            scheduled_or_time=(
                datetime.fromisoformat(row["scheduled_or_time"])
                if row["scheduled_or_time"]
                else None
            ),
            actual_incision_time=(
                datetime.fromisoformat(row["actual_incision_time"])
                if row["actual_incision_time"]
                else None
            ),
            surgery_end_time=(
                datetime.fromisoformat(row["surgery_end_time"])
                if row["surgery_end_time"]
                else None
            ),
            patient_weight_kg=row["patient_weight_kg"],
            patient_age_years=row["patient_age_years"],
            allergies=json.loads(row["allergies"]) if row["allergies"] else [],
            has_beta_lactam_allergy=bool(row["has_beta_lactam_allergy"]),
            mrsa_colonized=bool(row["mrsa_colonized"]),
            is_emergency=bool(row["is_emergency"]),
            already_on_therapeutic_antibiotics=bool(
                row["already_on_therapeutic_antibiotics"]
            ),
            documented_infection=bool(row["documented_infection"]),
        )

    # --- Evaluations ---

    def save_evaluation(self, evaluation: ProphylaxisEvaluation) -> int:
        """Save an evaluation result. Returns evaluation_id."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO prophylaxis_evaluations (
                    case_id, evaluation_time,
                    indication_status, indication_details,
                    agent_status, agent_details,
                    timing_status, timing_details,
                    dosing_status, dosing_details,
                    redosing_status, redosing_details,
                    discontinuation_status, discontinuation_details,
                    bundle_compliant, compliance_score,
                    elements_met, elements_total,
                    flags, recommendations,
                    excluded, exclusion_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.case_id,
                    evaluation.evaluation_time.isoformat(),
                    evaluation.indication.status.value,
                    evaluation.indication.details,
                    evaluation.agent_selection.status.value,
                    evaluation.agent_selection.details,
                    evaluation.timing.status.value,
                    evaluation.timing.details,
                    evaluation.dosing.status.value,
                    evaluation.dosing.details,
                    evaluation.redosing.status.value,
                    evaluation.redosing.details,
                    evaluation.discontinuation.status.value,
                    evaluation.discontinuation.details,
                    evaluation.bundle_compliant,
                    evaluation.compliance_score,
                    evaluation.elements_met,
                    evaluation.elements_total,
                    json.dumps(evaluation.flags),
                    json.dumps(evaluation.recommendations),
                    evaluation.excluded,
                    evaluation.exclusion_reason,
                ),
            )
            return cursor.lastrowid

    def get_evaluations_for_case(self, case_id: str) -> list[dict]:
        """Get all evaluations for a case."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM prophylaxis_evaluations
                WHERE case_id = ?
                ORDER BY evaluation_time DESC
                """,
                (case_id,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_latest_evaluation(self, case_id: str) -> Optional[dict]:
        """Get the most recent evaluation for a case."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM prophylaxis_evaluations
                WHERE case_id = ?
                ORDER BY evaluation_time DESC
                LIMIT 1
                """,
                (case_id,),
            ).fetchone()

        return dict(row) if row else None

    # --- Compliance Metrics ---

    def get_compliance_summary(
        self,
        start_date: datetime,
        end_date: datetime,
        procedure_category: Optional[str] = None,
    ) -> dict:
        """
        Get compliance summary for a date range.

        Returns aggregated metrics for bundle and element-level compliance.
        """
        with self._get_conn() as conn:
            # Base query
            query = """
                SELECT
                    COUNT(*) as total_cases,
                    SUM(CASE WHEN excluded = 1 THEN 1 ELSE 0 END) as excluded_cases,
                    SUM(CASE WHEN bundle_compliant = 1 AND excluded = 0 THEN 1 ELSE 0 END) as compliant_cases,
                    AVG(CASE WHEN excluded = 0 THEN compliance_score END) as avg_score,
                    SUM(CASE WHEN indication_status = 'met' THEN 1 ELSE 0 END) as indication_met,
                    SUM(CASE WHEN agent_status = 'met' THEN 1 ELSE 0 END) as agent_met,
                    SUM(CASE WHEN timing_status = 'met' THEN 1 ELSE 0 END) as timing_met,
                    SUM(CASE WHEN dosing_status = 'met' THEN 1 ELSE 0 END) as dosing_met,
                    SUM(CASE WHEN redosing_status = 'met' THEN 1 ELSE 0 END) as redosing_met,
                    SUM(CASE WHEN discontinuation_status = 'met' THEN 1 ELSE 0 END) as discontinuation_met
                FROM prophylaxis_evaluations pe
                JOIN surgical_cases sc ON pe.case_id = sc.case_id
                WHERE pe.evaluation_time >= ? AND pe.evaluation_time <= ?
            """
            params = [start_date.isoformat(), end_date.isoformat()]

            if procedure_category:
                query += " AND sc.procedure_category = ?"
                params.append(procedure_category)

            row = conn.execute(query, params).fetchone()

        if not row or row["total_cases"] == 0:
            return {
                "total_cases": 0,
                "excluded_cases": 0,
                "evaluated_cases": 0,
                "bundle_compliance_rate": 0.0,
                "avg_compliance_score": 0.0,
                "element_rates": {},
            }

        total = row["total_cases"]
        excluded = row["excluded_cases"] or 0
        evaluated = total - excluded

        return {
            "total_cases": total,
            "excluded_cases": excluded,
            "evaluated_cases": evaluated,
            "compliant_cases": row["compliant_cases"] or 0,
            "bundle_compliance_rate": (
                (row["compliant_cases"] / evaluated * 100) if evaluated > 0 else 0.0
            ),
            "avg_compliance_score": row["avg_score"] or 0.0,
            "element_rates": {
                "indication": (row["indication_met"] / evaluated * 100) if evaluated > 0 else 0.0,
                "agent_selection": (row["agent_met"] / evaluated * 100) if evaluated > 0 else 0.0,
                "timing": (row["timing_met"] / evaluated * 100) if evaluated > 0 else 0.0,
                "dosing": (row["dosing_met"] / evaluated * 100) if evaluated > 0 else 0.0,
                "redosing": (row["redosing_met"] / evaluated * 100) if evaluated > 0 else 0.0,
                "discontinuation": (
                    (row["discontinuation_met"] / evaluated * 100) if evaluated > 0 else 0.0
                ),
            },
        }

    def get_non_compliant_cases(
        self,
        start_date: datetime,
        end_date: datetime,
        element: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get non-compliant cases for review.

        Args:
            start_date: Start of date range
            end_date: End of date range
            element: Optional specific element to filter on
            limit: Maximum number of results

        Returns:
            List of case details with non-compliant elements
        """
        with self._get_conn() as conn:
            query = """
                SELECT
                    sc.case_id,
                    sc.patient_mrn,
                    sc.procedure_description,
                    sc.procedure_category,
                    sc.scheduled_or_time,
                    pe.evaluation_time,
                    pe.bundle_compliant,
                    pe.compliance_score,
                    pe.indication_status,
                    pe.indication_details,
                    pe.agent_status,
                    pe.agent_details,
                    pe.timing_status,
                    pe.timing_details,
                    pe.dosing_status,
                    pe.dosing_details,
                    pe.redosing_status,
                    pe.redosing_details,
                    pe.discontinuation_status,
                    pe.discontinuation_details,
                    pe.recommendations
                FROM prophylaxis_evaluations pe
                JOIN surgical_cases sc ON pe.case_id = sc.case_id
                WHERE pe.evaluation_time >= ? AND pe.evaluation_time <= ?
                AND pe.excluded = 0
                AND pe.bundle_compliant = 0
            """
            params = [start_date.isoformat(), end_date.isoformat()]

            if element:
                query += f" AND pe.{element}_status = 'not_met'"

            query += " ORDER BY pe.evaluation_time DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]

    # --- Alerts ---

    def save_alert(
        self,
        case_id: str,
        alert_type: str,
        severity: str,
        message: str,
        element_name: Optional[str] = None,
        evaluation_id: Optional[int] = None,
        external_alert_id: Optional[str] = None,
    ) -> int:
        """Save a prophylaxis alert. Returns alert_id."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO prophylaxis_alerts (
                    case_id, evaluation_id, alert_type, alert_severity,
                    alert_message, element_name, alert_time, external_alert_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    evaluation_id,
                    alert_type,
                    severity,
                    message,
                    element_name,
                    datetime.now().isoformat(),
                    external_alert_id,
                ),
            )
            return cursor.lastrowid

    def update_alert_response(
        self,
        alert_id: int,
        action: str,
        responder_id: Optional[str] = None,
        responder_name: Optional[str] = None,
        override_reason: Optional[str] = None,
    ) -> None:
        """Update an alert with response information."""
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE prophylaxis_alerts
                SET response_time = ?, response_action = ?,
                    responder_id = ?, responder_name = ?, override_reason = ?
                WHERE alert_id = ?
                """,
                (
                    datetime.now().isoformat(),
                    action,
                    responder_id,
                    responder_name,
                    override_reason,
                    alert_id,
                ),
            )

    def get_pending_alerts(self, case_id: Optional[str] = None) -> list[dict]:
        """Get alerts that haven't been responded to."""
        with self._get_conn() as conn:
            query = """
                SELECT pa.*, sc.patient_mrn, sc.procedure_description
                FROM prophylaxis_alerts pa
                JOIN surgical_cases sc ON pa.case_id = sc.case_id
                WHERE pa.response_action IS NULL
            """
            params = []

            if case_id:
                query += " AND pa.case_id = ?"
                params.append(case_id)

            query += " ORDER BY pa.alert_time DESC"
            rows = conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]
