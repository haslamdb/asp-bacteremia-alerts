"""Database operations for indication monitoring.

Provides SQLite persistence for indication candidates, reviews, and
LLM extraction audit trail.
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .models import (
    IndicationCandidate,
    IndicationExtraction,
    Patient,
    MedicationOrder,
)
from .config import config

logger = logging.getLogger(__name__)


class IndicationDatabase:
    """SQLite database for indication tracking."""

    def __init__(self, db_path: str | None = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database. Uses config default if None.
        """
        self.db_path = db_path or config.INDICATION_DB_PATH
        self._ensure_db_exists()

    def _ensure_db_exists(self) -> None:
        """Create database and tables if they don't exist."""
        db_path = Path(self.db_path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Read schema from file
        schema_path = Path(__file__).parent.parent / "schema.sql"
        if schema_path.exists():
            schema = schema_path.read_text()
        else:
            logger.warning(f"Schema file not found: {schema_path}")
            return

        with self._get_connection() as conn:
            conn.executescript(schema)
            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Get database connection with context manager."""
        db_path = Path(self.db_path).expanduser()
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save_candidate(self, candidate: IndicationCandidate) -> str:
        """Save an indication candidate to the database.

        Args:
            candidate: The candidate to save.

        Returns:
            The candidate ID.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Check if exists (by medication_request_id)
            cursor.execute(
                "SELECT id FROM indication_candidates WHERE medication_request_id = ?",
                (candidate.medication.fhir_id,),
            )
            existing = cursor.fetchone()

            if existing:
                # Update existing
                cursor.execute(
                    """
                    UPDATE indication_candidates SET
                        icd10_codes = ?,
                        icd10_classification = ?,
                        icd10_primary_indication = ?,
                        llm_extracted_indication = ?,
                        llm_classification = ?,
                        final_classification = ?,
                        classification_source = ?,
                        status = ?,
                        alert_id = ?,
                        updated_at = ?
                    WHERE medication_request_id = ?
                    """,
                    (
                        json.dumps(candidate.icd10_codes),
                        candidate.icd10_classification,
                        candidate.icd10_primary_indication,
                        candidate.llm_extracted_indication,
                        candidate.llm_classification,
                        candidate.final_classification,
                        candidate.classification_source,
                        candidate.status,
                        candidate.alert_id,
                        datetime.now().isoformat(),
                        candidate.medication.fhir_id,
                    ),
                )
                conn.commit()
                return existing[0]
            else:
                # Insert new
                candidate_id = candidate.id or str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO indication_candidates (
                        id, patient_id, patient_mrn, medication_request_id,
                        medication_name, order_date, icd10_codes, icd10_classification,
                        icd10_primary_indication, llm_extracted_indication,
                        llm_classification, final_classification, classification_source,
                        status, alert_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        candidate.patient.fhir_id,
                        candidate.patient.mrn,
                        candidate.medication.fhir_id,
                        candidate.medication.medication_name,
                        candidate.medication.start_date.isoformat()
                        if candidate.medication.start_date
                        else None,
                        json.dumps(candidate.icd10_codes),
                        candidate.icd10_classification,
                        candidate.icd10_primary_indication,
                        candidate.llm_extracted_indication,
                        candidate.llm_classification,
                        candidate.final_classification,
                        candidate.classification_source,
                        candidate.status,
                        candidate.alert_id,
                    ),
                )
                conn.commit()
                return candidate_id

    def get_candidate(self, candidate_id: str) -> IndicationCandidate | None:
        """Get an indication candidate by ID.

        Args:
            candidate_id: The candidate ID.

        Returns:
            The candidate if found, None otherwise.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM indication_candidates WHERE id = ?",
                (candidate_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_candidate(row)

    def get_candidate_by_medication_id(
        self, medication_request_id: str
    ) -> IndicationCandidate | None:
        """Get an indication candidate by medication request ID.

        Args:
            medication_request_id: The FHIR MedicationRequest ID.

        Returns:
            The candidate if found, None otherwise.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM indication_candidates WHERE medication_request_id = ?",
                (medication_request_id,),
            )
            row = cursor.fetchone()

            if not row:
                return None

            return self._row_to_candidate(row)

    def list_candidates(
        self,
        status: str | None = None,
        classification: str | None = None,
        limit: int = 100,
    ) -> list[IndicationCandidate]:
        """List indication candidates with optional filters.

        Args:
            status: Filter by status (pending, alerted, reviewed).
            classification: Filter by final classification (A, S, N, etc.).
            limit: Maximum number of results.

        Returns:
            List of matching candidates.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM indication_candidates WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)

            if classification:
                query += " AND final_classification = ?"
                params.append(classification)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [self._row_to_candidate(row) for row in rows]

    def _row_to_candidate(self, row: sqlite3.Row) -> IndicationCandidate:
        """Convert a database row to an IndicationCandidate."""
        # Create minimal Patient and MedicationOrder from stored data
        patient = Patient(
            fhir_id=row["patient_id"],
            mrn=row["patient_mrn"],
            name="",  # Not stored in candidates table
        )

        order_date = None
        if row["order_date"]:
            try:
                order_date = datetime.fromisoformat(row["order_date"])
            except ValueError:
                pass

        medication = MedicationOrder(
            fhir_id=row["medication_request_id"],
            patient_id=row["patient_id"],
            medication_name=row["medication_name"],
            start_date=order_date,
        )

        icd10_codes = []
        if row["icd10_codes"]:
            try:
                icd10_codes = json.loads(row["icd10_codes"])
            except json.JSONDecodeError:
                pass

        return IndicationCandidate(
            id=row["id"],
            patient=patient,
            medication=medication,
            icd10_codes=icd10_codes,
            icd10_classification=row["icd10_classification"],
            icd10_primary_indication=row["icd10_primary_indication"],
            llm_extracted_indication=row["llm_extracted_indication"],
            llm_classification=row["llm_classification"],
            final_classification=row["final_classification"],
            classification_source=row["classification_source"],
            status=row["status"],
            alert_id=row["alert_id"],
        )

    def save_review(
        self,
        candidate_id: str,
        reviewer: str,
        decision: str,
        is_override: bool = False,
        override_reason: str | None = None,
        llm_decision: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Save an indication review.

        Args:
            candidate_id: The candidate being reviewed.
            reviewer: Who performed the review.
            decision: The review decision (confirmed_n, override_to_a, etc.).
            is_override: Whether this disagrees with the system classification.
            override_reason: Reason for override if applicable.
            llm_decision: What the LLM said (for comparison).
            notes: Additional notes.

        Returns:
            The review ID.
        """
        review_id = str(uuid.uuid4())

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO indication_reviews (
                    id, candidate_id, reviewer, reviewer_decision,
                    llm_decision, is_override, override_reason, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    candidate_id,
                    reviewer,
                    decision,
                    llm_decision,
                    1 if is_override else 0,
                    override_reason,
                    notes,
                ),
            )

            # Update candidate status
            cursor.execute(
                "UPDATE indication_candidates SET status = 'reviewed', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), candidate_id),
            )

            conn.commit()

        return review_id

    def save_extraction(
        self,
        candidate_id: str,
        extraction: IndicationExtraction,
        response_time_ms: int | None = None,
    ) -> str:
        """Save an LLM extraction result.

        Args:
            candidate_id: The candidate this extraction is for.
            extraction: The extraction result.
            response_time_ms: LLM response time in milliseconds.

        Returns:
            The extraction ID.
        """
        extraction_id = str(uuid.uuid4())

        # Convert confidence string to float
        confidence_map = {"HIGH": 0.9, "MEDIUM": 0.7, "LOW": 0.5}
        confidence = confidence_map.get(extraction.confidence.upper(), 0.5)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO indication_extractions (
                    id, candidate_id, model_used, prompt_version,
                    extracted_indications, supporting_quotes, confidence,
                    tokens_used, response_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction_id,
                    candidate_id,
                    extraction.model_used,
                    extraction.prompt_version,
                    json.dumps(extraction.found_indications),
                    json.dumps(extraction.supporting_quotes),
                    confidence,
                    extraction.tokens_used,
                    response_time_ms,
                ),
            )
            conn.commit()

        return extraction_id

    def get_override_stats(self, days: int = 30) -> dict:
        """Get statistics on review overrides.

        Args:
            days: Number of days to include.

        Returns:
            Dict with override statistics.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total reviews
            cursor.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) as overrides
                FROM indication_reviews
                WHERE reviewed_at >= datetime('now', ?)
                """,
                (f"-{days} days",),
            )
            row = cursor.fetchone()
            total = row["total"] or 0
            overrides = row["overrides"] or 0

            # Override breakdown by decision
            cursor.execute(
                """
                SELECT reviewer_decision, COUNT(*) as count
                FROM indication_reviews
                WHERE is_override = 1 AND reviewed_at >= datetime('now', ?)
                GROUP BY reviewer_decision
                """,
                (f"-{days} days",),
            )
            override_breakdown = {r["reviewer_decision"]: r["count"] for r in cursor.fetchall()}

            return {
                "total_reviews": total,
                "total_overrides": overrides,
                "override_rate": overrides / total if total > 0 else 0,
                "override_breakdown": override_breakdown,
                "days": days,
            }

    def get_candidate_count_by_classification(self, days: int = 7) -> dict:
        """Get candidate counts by classification.

        Args:
            days: Number of days to include.

        Returns:
            Dict mapping classification to count.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT final_classification, COUNT(*) as count
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                GROUP BY final_classification
                """,
                (f"-{days} days",),
            )
            return {r["final_classification"]: r["count"] for r in cursor.fetchall()}
