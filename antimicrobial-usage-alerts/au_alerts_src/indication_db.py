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
    EvidenceSource,
    IndicationCandidate,
    IndicationExtraction,
    Patient,
    MedicationOrder,
)
from .config import config

logger = logging.getLogger(__name__)


def _log_indication_activity(
    activity_type: str,
    entity_id: str,
    entity_type: str,
    action_taken: str,
    provider_id: str | None = None,
    provider_name: str | None = None,
    patient_mrn: str | None = None,
    location_code: str | None = None,
    service: str | None = None,
    outcome: str | None = None,
    details: dict | None = None,
) -> None:
    """Log activity to the unified metrics store.

    This is a fire-and-forget operation - failures are logged but don't
    interrupt the main operation.
    """
    try:
        from common.metrics_store import MetricsStore, ModuleSource

        store = MetricsStore()
        store.log_activity(
            activity_type=activity_type,
            module=ModuleSource.ABX_INDICATIONS,
            provider_id=provider_id,
            provider_name=provider_name,
            entity_id=entity_id,
            entity_type=entity_type,
            action_taken=action_taken,
            outcome=outcome,
            patient_mrn=patient_mrn,
            location_code=location_code,
            service=service,
            details=details,
        )
    except Exception as e:
        logger.debug(f"Failed to log activity to metrics store: {e}")


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

            # Run migrations for existing databases
            self._run_migrations(conn)

    def _run_migrations(self, conn) -> None:
        """Add new columns to existing databases."""
        cursor = conn.cursor()

        # Get existing columns for indication_candidates
        cursor.execute("PRAGMA table_info(indication_candidates)")
        candidates_cols = {row[1] for row in cursor.fetchall()}

        # Migrations for indication_candidates
        candidates_migrations = [
            ("rxnorm_code", "ALTER TABLE indication_candidates ADD COLUMN rxnorm_code TEXT"),
            ("location", "ALTER TABLE indication_candidates ADD COLUMN location TEXT"),
            ("service", "ALTER TABLE indication_candidates ADD COLUMN service TEXT"),
            ("cchmc_disease_matched", "ALTER TABLE indication_candidates ADD COLUMN cchmc_disease_matched TEXT"),
            ("cchmc_agent_category", "ALTER TABLE indication_candidates ADD COLUMN cchmc_agent_category TEXT"),
            ("cchmc_guideline_agents", "ALTER TABLE indication_candidates ADD COLUMN cchmc_guideline_agents TEXT"),
            ("cchmc_recommendation", "ALTER TABLE indication_candidates ADD COLUMN cchmc_recommendation TEXT"),
            # v2: JC-compliant clinical syndrome fields
            ("clinical_syndrome", "ALTER TABLE indication_candidates ADD COLUMN clinical_syndrome TEXT"),
            ("clinical_syndrome_display", "ALTER TABLE indication_candidates ADD COLUMN clinical_syndrome_display TEXT"),
            ("syndrome_category", "ALTER TABLE indication_candidates ADD COLUMN syndrome_category TEXT"),
            ("syndrome_confidence", "ALTER TABLE indication_candidates ADD COLUMN syndrome_confidence TEXT"),
            ("therapy_intent", "ALTER TABLE indication_candidates ADD COLUMN therapy_intent TEXT"),
            ("guideline_disease_ids", "ALTER TABLE indication_candidates ADD COLUMN guideline_disease_ids TEXT"),
            ("likely_viral", "ALTER TABLE indication_candidates ADD COLUMN likely_viral BOOLEAN DEFAULT 0"),
            ("asymptomatic_bacteriuria", "ALTER TABLE indication_candidates ADD COLUMN asymptomatic_bacteriuria BOOLEAN DEFAULT 0"),
            ("indication_not_documented", "ALTER TABLE indication_candidates ADD COLUMN indication_not_documented BOOLEAN DEFAULT 0"),
            ("never_appropriate", "ALTER TABLE indication_candidates ADD COLUMN never_appropriate BOOLEAN DEFAULT 0"),
        ]

        for col_name, sql in candidates_migrations:
            if col_name not in candidates_cols:
                try:
                    cursor.execute(sql)
                    logger.info(f"Migration: added column {col_name} to indication_candidates")
                except Exception as e:
                    logger.debug(f"Migration skipped for {col_name}: {e}")

        # Get existing columns for indication_extractions
        cursor.execute("PRAGMA table_info(indication_extractions)")
        extractions_cols = {row[1] for row in cursor.fetchall()}

        # Migrations for indication_extractions (evidence source attribution)
        extractions_migrations = [
            ("evidence_sources", "ALTER TABLE indication_extractions ADD COLUMN evidence_sources TEXT"),
            ("notes_filtered_count", "ALTER TABLE indication_extractions ADD COLUMN notes_filtered_count INTEGER"),
            ("notes_total_count", "ALTER TABLE indication_extractions ADD COLUMN notes_total_count INTEGER"),
        ]

        for col_name, sql in extractions_migrations:
            if col_name not in extractions_cols:
                try:
                    cursor.execute(sql)
                    logger.info(f"Migration: added column {col_name} to indication_extractions")
                except Exception as e:
                    logger.debug(f"Migration skipped for {col_name}: {e}")

        # Get existing columns for indication_reviews
        cursor.execute("PRAGMA table_info(indication_reviews)")
        reviews_cols = {row[1] for row in cursor.fetchall()}

        # v2: Syndrome and agent review fields
        reviews_migrations = [
            ("syndrome_decision", "ALTER TABLE indication_reviews ADD COLUMN syndrome_decision TEXT"),
            ("confirmed_syndrome", "ALTER TABLE indication_reviews ADD COLUMN confirmed_syndrome TEXT"),
            ("confirmed_syndrome_display", "ALTER TABLE indication_reviews ADD COLUMN confirmed_syndrome_display TEXT"),
            ("agent_decision", "ALTER TABLE indication_reviews ADD COLUMN agent_decision TEXT"),
            ("agent_notes", "ALTER TABLE indication_reviews ADD COLUMN agent_notes TEXT"),
        ]

        for col_name, sql in reviews_migrations:
            if col_name not in reviews_cols:
                try:
                    cursor.execute(sql)
                    logger.info(f"Migration: added column {col_name} to indication_reviews")
                except Exception as e:
                    logger.debug(f"Migration skipped for {col_name}: {e}")

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
                        rxnorm_code = ?,
                        location = ?,
                        service = ?,
                        icd10_codes = ?,
                        icd10_classification = ?,
                        icd10_primary_indication = ?,
                        llm_extracted_indication = ?,
                        llm_classification = ?,
                        final_classification = ?,
                        classification_source = ?,
                        status = ?,
                        alert_id = ?,
                        cchmc_disease_matched = ?,
                        cchmc_agent_category = ?,
                        cchmc_guideline_agents = ?,
                        cchmc_recommendation = ?,
                        updated_at = ?
                    WHERE medication_request_id = ?
                    """,
                    (
                        candidate.medication.rxnorm_code,
                        candidate.location,
                        candidate.service,
                        json.dumps(candidate.icd10_codes),
                        candidate.icd10_classification,
                        candidate.icd10_primary_indication,
                        candidate.llm_extracted_indication,
                        candidate.llm_classification,
                        candidate.final_classification,
                        candidate.classification_source,
                        candidate.status,
                        candidate.alert_id,
                        candidate.cchmc_disease_matched,
                        candidate.cchmc_agent_category,
                        candidate.cchmc_guideline_agents,
                        candidate.cchmc_recommendation,
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
                        medication_name, rxnorm_code, order_date, location, service,
                        icd10_codes, icd10_classification, icd10_primary_indication,
                        llm_extracted_indication, llm_classification,
                        final_classification, classification_source, status, alert_id,
                        cchmc_disease_matched, cchmc_agent_category,
                        cchmc_guideline_agents, cchmc_recommendation
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        candidate.patient.fhir_id,
                        candidate.patient.mrn,
                        candidate.medication.fhir_id,
                        candidate.medication.medication_name,
                        candidate.medication.rxnorm_code,
                        candidate.medication.start_date.isoformat()
                        if candidate.medication.start_date
                        else None,
                        candidate.location,
                        candidate.service,
                        json.dumps(candidate.icd10_codes),
                        candidate.icd10_classification,
                        candidate.icd10_primary_indication,
                        candidate.llm_extracted_indication,
                        candidate.llm_classification,
                        candidate.final_classification,
                        candidate.classification_source,
                        candidate.status,
                        candidate.alert_id,
                        candidate.cchmc_disease_matched,
                        candidate.cchmc_agent_category,
                        candidate.cchmc_guideline_agents,
                        candidate.cchmc_recommendation,
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

        # Get rxnorm_code safely (may not exist in older rows)
        rxnorm_code = row["rxnorm_code"] if "rxnorm_code" in row.keys() else None

        medication = MedicationOrder(
            fhir_id=row["medication_request_id"],
            patient_id=row["patient_id"],
            medication_name=row["medication_name"],
            rxnorm_code=rxnorm_code,
            start_date=order_date,
        )

        icd10_codes = []
        if row["icd10_codes"]:
            try:
                icd10_codes = json.loads(row["icd10_codes"])
            except json.JSONDecodeError:
                pass

        # Get location/service safely (may not exist in older rows)
        location = row["location"] if "location" in row.keys() else None
        service = row["service"] if "service" in row.keys() else None

        # Get CCHMC fields safely (may not exist in older rows)
        keys = row.keys()
        cchmc_disease_matched = row["cchmc_disease_matched"] if "cchmc_disease_matched" in keys else None
        cchmc_agent_category = row["cchmc_agent_category"] if "cchmc_agent_category" in keys else None
        cchmc_guideline_agents = row["cchmc_guideline_agents"] if "cchmc_guideline_agents" in keys else None
        cchmc_recommendation = row["cchmc_recommendation"] if "cchmc_recommendation" in keys else None

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
            location=location,
            service=service,
            cchmc_disease_matched=cchmc_disease_matched,
            cchmc_agent_category=cchmc_agent_category,
            cchmc_guideline_agents=cchmc_guideline_agents,
            cchmc_recommendation=cchmc_recommendation,
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
        # v2: Syndrome review fields (JC-compliant)
        syndrome_decision: str | None = None,
        confirmed_syndrome: str | None = None,
        confirmed_syndrome_display: str | None = None,
        # v2: Agent appropriateness review
        agent_decision: str | None = None,
        agent_notes: str | None = None,
    ) -> str:
        """Save an indication review.

        Args:
            candidate_id: The candidate being reviewed.
            reviewer: Who performed the review.
            decision: Legacy decision (confirmed_n, override_to_a, etc.).
                Use syndrome_decision for new JC-compliant workflow.
            is_override: Whether this disagrees with the system classification.
            override_reason: Reason for override if applicable.
            llm_decision: What the LLM said (for comparison).
            notes: Additional notes.
            syndrome_decision: Syndrome review decision (confirm_syndrome,
                correct_syndrome, no_indication, viral_illness).
            confirmed_syndrome: The confirmed/corrected syndrome ID.
            confirmed_syndrome_display: Human-readable syndrome name.
            agent_decision: Agent appropriateness decision (agent_appropriate,
                agent_acceptable, agent_inappropriate).
            agent_notes: Notes about agent appropriateness.

        Returns:
            The review ID.
        """
        review_id = str(uuid.uuid4())

        # Get candidate info for activity logging
        candidate = self.get_candidate(candidate_id)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO indication_reviews (
                    id, candidate_id, reviewer, reviewer_decision,
                    llm_decision, is_override, override_reason, notes,
                    syndrome_decision, confirmed_syndrome, confirmed_syndrome_display,
                    agent_decision, agent_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    syndrome_decision,
                    confirmed_syndrome,
                    confirmed_syndrome_display,
                    agent_decision,
                    agent_notes,
                ),
            )

            # Update candidate status
            cursor.execute(
                "UPDATE indication_candidates SET status = 'reviewed', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), candidate_id),
            )

            conn.commit()

        # Log to unified metrics store
        activity_type = "override" if is_override else "review"
        _log_indication_activity(
            activity_type=activity_type,
            entity_id=candidate_id,
            entity_type="indication_candidate",
            action_taken=syndrome_decision or decision,
            provider_name=reviewer,
            patient_mrn=candidate.patient.mrn if candidate else None,
            location_code=candidate.location if candidate else None,
            service=candidate.service if candidate else None,
            outcome=syndrome_decision or decision,
            details={
                "medication_name": candidate.medication.medication_name if candidate else None,
                "llm_decision": llm_decision,
                "final_classification": candidate.final_classification if candidate else None,
                "is_override": is_override,
                "override_reason": override_reason,
                "syndrome_decision": syndrome_decision,
                "confirmed_syndrome": confirmed_syndrome,
                "agent_decision": agent_decision,
            },
        )

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

        # Serialize evidence sources
        evidence_sources_json = None
        if extraction.evidence_sources:
            evidence_sources_json = json.dumps(
                [src.to_dict() for src in extraction.evidence_sources]
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO indication_extractions (
                    id, candidate_id, model_used, prompt_version,
                    extracted_indications, supporting_quotes, confidence,
                    evidence_sources, notes_filtered_count, notes_total_count,
                    tokens_used, response_time_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction_id,
                    candidate_id,
                    extraction.model_used,
                    extraction.prompt_version,
                    json.dumps(extraction.found_indications),
                    json.dumps(extraction.supporting_quotes),
                    confidence,
                    evidence_sources_json,
                    extraction.notes_filtered_count,
                    extraction.notes_total_count,
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

    # ========================
    # Analytics Methods
    # ========================

    def get_usage_by_antibiotic(self, days: int = 30) -> list[dict]:
        """Get antibiotic usage statistics grouped by medication.

        Includes top syndromes and agent appropriateness stats.

        Args:
            days: Number of days to include.

        Returns:
            List of dicts with medication stats including syndromes and appropriateness.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get basic counts per antibiotic
            cursor.execute(
                """
                SELECT
                    medication_name,
                    rxnorm_code,
                    COUNT(*) as total_orders
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                GROUP BY medication_name, rxnorm_code
                ORDER BY total_orders DESC
                """,
                (f"-{days} days",),
            )
            antibiotics = cursor.fetchall()

            results = []
            for abx in antibiotics:
                med_name = abx["medication_name"]

                # Get top 3 syndromes for this antibiotic
                cursor.execute(
                    """
                    SELECT clinical_syndrome_display, COUNT(*) as cnt
                    FROM indication_candidates
                    WHERE medication_name = ?
                    AND created_at >= datetime('now', ?)
                    AND clinical_syndrome IS NOT NULL
                    AND clinical_syndrome != ''
                    GROUP BY clinical_syndrome
                    ORDER BY cnt DESC
                    LIMIT 3
                    """,
                    (med_name, f"-{days} days"),
                )
                top_syndromes = [row["clinical_syndrome_display"] for row in cursor.fetchall()]

                # Get agent appropriateness for this antibiotic
                cursor.execute(
                    """
                    SELECT
                        SUM(CASE WHEN r.agent_decision = 'agent_appropriate' THEN 1 ELSE 0 END) as appropriate,
                        SUM(CASE WHEN r.agent_decision = 'agent_acceptable' THEN 1 ELSE 0 END) as acceptable,
                        SUM(CASE WHEN r.agent_decision = 'agent_inappropriate' THEN 1 ELSE 0 END) as inappropriate,
                        COUNT(CASE WHEN r.agent_decision IN ('agent_appropriate', 'agent_acceptable', 'agent_inappropriate') THEN 1 END) as assessed
                    FROM indication_candidates c
                    JOIN indication_reviews r ON c.id = r.candidate_id
                    WHERE c.medication_name = ?
                    AND c.created_at >= datetime('now', ?)
                    """,
                    (med_name, f"-{days} days"),
                )
                agent_row = cursor.fetchone()
                assessed = agent_row["assessed"] or 0
                agent_appropriate = (agent_row["appropriate"] or 0) + (agent_row["acceptable"] or 0)

                results.append({
                    "medication_name": med_name,
                    "rxnorm_code": abx["rxnorm_code"],
                    "total_orders": abx["total_orders"],
                    "top_syndromes": top_syndromes,
                    "agent_assessed": assessed,
                    "agent_appropriate": agent_appropriate,
                    "agent_inappropriate": agent_row["inappropriate"] or 0,
                    "agent_appropriate_rate": agent_appropriate / assessed if assessed > 0 else None,
                })
            return results

    def get_usage_by_location(self, days: int = 30) -> list[dict]:
        """Get antibiotic usage statistics grouped by location/unit.

        Includes top syndromes and agent appropriateness stats.

        Args:
            days: Number of days to include.

        Returns:
            List of dicts with location stats including syndromes and appropriateness.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get basic counts per location
            cursor.execute(
                """
                SELECT
                    COALESCE(location, 'Unknown') as location,
                    COUNT(*) as total_orders
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                GROUP BY location
                ORDER BY total_orders DESC
                """,
                (f"-{days} days",),
            )
            locations = cursor.fetchall()

            results = []
            for loc in locations:
                loc_name = loc["location"]

                # Get top 3 syndromes for this location
                cursor.execute(
                    """
                    SELECT clinical_syndrome_display, COUNT(*) as cnt
                    FROM indication_candidates
                    WHERE COALESCE(location, 'Unknown') = ?
                    AND created_at >= datetime('now', ?)
                    AND clinical_syndrome IS NOT NULL
                    AND clinical_syndrome != ''
                    GROUP BY clinical_syndrome
                    ORDER BY cnt DESC
                    LIMIT 3
                    """,
                    (loc_name, f"-{days} days"),
                )
                top_syndromes = [row["clinical_syndrome_display"] for row in cursor.fetchall()]

                # Get agent appropriateness for this location
                cursor.execute(
                    """
                    SELECT
                        SUM(CASE WHEN r.agent_decision = 'agent_appropriate' THEN 1 ELSE 0 END) as appropriate,
                        SUM(CASE WHEN r.agent_decision = 'agent_acceptable' THEN 1 ELSE 0 END) as acceptable,
                        SUM(CASE WHEN r.agent_decision = 'agent_inappropriate' THEN 1 ELSE 0 END) as inappropriate,
                        COUNT(CASE WHEN r.agent_decision IN ('agent_appropriate', 'agent_acceptable', 'agent_inappropriate') THEN 1 END) as assessed
                    FROM indication_candidates c
                    JOIN indication_reviews r ON c.id = r.candidate_id
                    WHERE COALESCE(c.location, 'Unknown') = ?
                    AND c.created_at >= datetime('now', ?)
                    """,
                    (loc_name, f"-{days} days"),
                )
                agent_row = cursor.fetchone()
                assessed = agent_row["assessed"] or 0
                agent_appropriate = (agent_row["appropriate"] or 0) + (agent_row["acceptable"] or 0)

                results.append({
                    "location": loc_name,
                    "total_orders": loc["total_orders"],
                    "top_syndromes": top_syndromes,
                    "agent_assessed": assessed,
                    "agent_appropriate": agent_appropriate,
                    "agent_inappropriate": agent_row["inappropriate"] or 0,
                    "agent_appropriate_rate": agent_appropriate / assessed if assessed > 0 else None,
                })
            return results

    def get_usage_by_service(self, days: int = 30) -> list[dict]:
        """Get antibiotic usage statistics grouped by ordering service.

        Includes top syndromes and agent appropriateness stats.

        Args:
            days: Number of days to include.

        Returns:
            List of dicts with service stats including syndromes and appropriateness.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get basic counts per service
            cursor.execute(
                """
                SELECT
                    COALESCE(service, 'Unknown') as service,
                    COUNT(*) as total_orders
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                GROUP BY service
                ORDER BY total_orders DESC
                """,
                (f"-{days} days",),
            )
            services = cursor.fetchall()

            results = []
            for svc in services:
                svc_name = svc["service"]

                # Get top 3 syndromes for this service
                cursor.execute(
                    """
                    SELECT clinical_syndrome_display, COUNT(*) as cnt
                    FROM indication_candidates
                    WHERE COALESCE(service, 'Unknown') = ?
                    AND created_at >= datetime('now', ?)
                    AND clinical_syndrome IS NOT NULL
                    AND clinical_syndrome != ''
                    GROUP BY clinical_syndrome
                    ORDER BY cnt DESC
                    LIMIT 3
                    """,
                    (svc_name, f"-{days} days"),
                )
                top_syndromes = [row["clinical_syndrome_display"] for row in cursor.fetchall()]

                # Get agent appropriateness for this service
                cursor.execute(
                    """
                    SELECT
                        SUM(CASE WHEN r.agent_decision = 'agent_appropriate' THEN 1 ELSE 0 END) as appropriate,
                        SUM(CASE WHEN r.agent_decision = 'agent_acceptable' THEN 1 ELSE 0 END) as acceptable,
                        SUM(CASE WHEN r.agent_decision = 'agent_inappropriate' THEN 1 ELSE 0 END) as inappropriate,
                        COUNT(CASE WHEN r.agent_decision IN ('agent_appropriate', 'agent_acceptable', 'agent_inappropriate') THEN 1 END) as assessed
                    FROM indication_candidates c
                    JOIN indication_reviews r ON c.id = r.candidate_id
                    WHERE COALESCE(c.service, 'Unknown') = ?
                    AND c.created_at >= datetime('now', ?)
                    """,
                    (svc_name, f"-{days} days"),
                )
                agent_row = cursor.fetchone()
                assessed = agent_row["assessed"] or 0
                agent_appropriate = (agent_row["appropriate"] or 0) + (agent_row["acceptable"] or 0)

                results.append({
                    "service": svc_name,
                    "total_orders": svc["total_orders"],
                    "top_syndromes": top_syndromes,
                    "agent_assessed": assessed,
                    "agent_appropriate": agent_appropriate,
                    "agent_inappropriate": agent_row["inappropriate"] or 0,
                    "agent_appropriate_rate": agent_appropriate / assessed if assessed > 0 else None,
                })
            return results

    def get_usage_by_location_and_antibiotic(self, days: int = 30) -> list[dict]:
        """Get cross-tabulated usage by location AND antibiotic.

        Args:
            days: Number of days to include.

        Returns:
            List of dicts with location/antibiotic combination stats.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COALESCE(location, 'Unknown') as location,
                    medication_name,
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN final_classification IN ('A', 'S', 'P') THEN 1 ELSE 0 END) as appropriate,
                    SUM(CASE WHEN final_classification = 'N' THEN 1 ELSE 0 END) as inappropriate
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                GROUP BY location, medication_name
                ORDER BY location, total_orders DESC
                """,
                (f"-{days} days",),
            )
            results = []
            for r in cursor.fetchall():
                total = r["total_orders"]
                results.append({
                    "location": r["location"],
                    "medication_name": r["medication_name"],
                    "total_orders": total,
                    "appropriate": r["appropriate"],
                    "inappropriate": r["inappropriate"],
                    "appropriate_rate": r["appropriate"] / total if total > 0 else 0,
                })
            return results

    def get_daily_usage_trend(self, days: int = 30) -> list[dict]:
        """Get daily antibiotic usage trend.

        Args:
            days: Number of days to include.

        Returns:
            List of dicts with daily stats.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    DATE(order_date) as date,
                    COUNT(*) as total_orders,
                    SUM(CASE WHEN final_classification IN ('A', 'S', 'P') THEN 1 ELSE 0 END) as appropriate,
                    SUM(CASE WHEN final_classification = 'N' THEN 1 ELSE 0 END) as inappropriate
                FROM indication_candidates
                WHERE order_date >= datetime('now', ?)
                GROUP BY DATE(order_date)
                ORDER BY date
                """,
                (f"-{days} days",),
            )
            results = []
            for r in cursor.fetchall():
                total = r["total_orders"]
                results.append({
                    "date": r["date"],
                    "total_orders": total,
                    "appropriate": r["appropriate"],
                    "inappropriate": r["inappropriate"],
                    "appropriate_rate": r["appropriate"] / total if total > 0 else 0,
                })
            return results

    def get_usage_summary(self, days: int = 30) -> dict:
        """Get overall usage summary statistics.

        Args:
            days: Number of days to include.

        Returns:
            Dict with summary statistics.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_orders,
                    COUNT(DISTINCT patient_id) as unique_patients,
                    COUNT(DISTINCT medication_name) as unique_antibiotics,
                    COUNT(DISTINCT location) as unique_locations,
                    COUNT(DISTINCT service) as unique_services,
                    SUM(CASE WHEN final_classification IN ('A', 'S', 'P') THEN 1 ELSE 0 END) as appropriate,
                    SUM(CASE WHEN final_classification = 'N' THEN 1 ELSE 0 END) as inappropriate,
                    SUM(CASE WHEN final_classification IN ('U', 'FN') THEN 1 ELSE 0 END) as unknown,
                    SUM(CASE WHEN classification_source = 'llm' THEN 1 ELSE 0 END) as llm_classified,
                    SUM(CASE WHEN classification_source = 'icd10' THEN 1 ELSE 0 END) as icd10_classified
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                """,
                (f"-{days} days",),
            )
            r = cursor.fetchone()
            total = r["total_orders"] or 0
            return {
                "days": days,
                "total_orders": total,
                "unique_patients": r["unique_patients"] or 0,
                "unique_antibiotics": r["unique_antibiotics"] or 0,
                "unique_locations": r["unique_locations"] or 0,
                "unique_services": r["unique_services"] or 0,
                "appropriate": r["appropriate"] or 0,
                "inappropriate": r["inappropriate"] or 0,
                "unknown": r["unknown"] or 0,
                "appropriate_rate": (r["appropriate"] or 0) / total if total > 0 else 0,
                "inappropriate_rate": (r["inappropriate"] or 0) / total if total > 0 else 0,
                "llm_classified": r["llm_classified"] or 0,
                "icd10_classified": r["icd10_classified"] or 0,
            }

    # ========================
    # Deletion Methods
    # ========================

    def delete_candidate(
        self,
        candidate_id: str,
        deleted_by: str,
        reason: str | None = None,
    ) -> bool:
        """Delete a single reviewed candidate.

        Only candidates with status='reviewed' can be deleted. This is a
        hard delete - the candidate and associated reviews/extractions
        are permanently removed.

        Args:
            candidate_id: The candidate to delete.
            deleted_by: Who is performing the deletion.
            reason: Optional reason for deletion.

        Returns:
            True if deleted, False if not found or not reviewed.
        """
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            logger.warning(f"Cannot delete candidate {candidate_id}: not found")
            return False

        if candidate.status != "reviewed":
            logger.warning(
                f"Cannot delete candidate {candidate_id}: status is '{candidate.status}', "
                "only 'reviewed' candidates can be deleted"
            )
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Delete associated extractions
            cursor.execute(
                "DELETE FROM indication_extractions WHERE candidate_id = ?",
                (candidate_id,),
            )
            extractions_deleted = cursor.rowcount

            # Delete associated reviews
            cursor.execute(
                "DELETE FROM indication_reviews WHERE candidate_id = ?",
                (candidate_id,),
            )
            reviews_deleted = cursor.rowcount

            # Delete the candidate
            cursor.execute(
                "DELETE FROM indication_candidates WHERE id = ?",
                (candidate_id,),
            )

            conn.commit()

        # Log the deletion
        _log_indication_activity(
            activity_type="deletion",
            entity_id=candidate_id,
            entity_type="indication_candidate",
            action_taken="deleted",
            provider_name=deleted_by,
            patient_mrn=candidate.patient.mrn,
            location_code=candidate.location,
            service=candidate.service,
            outcome="deleted",
            details={
                "medication_name": candidate.medication.medication_name,
                "final_classification": candidate.final_classification,
                "reason": reason,
                "extractions_deleted": extractions_deleted,
                "reviews_deleted": reviews_deleted,
            },
        )

        logger.info(
            f"Deleted candidate {candidate_id} ({candidate.medication.medication_name}) "
            f"by {deleted_by}: {extractions_deleted} extractions, {reviews_deleted} reviews"
        )
        return True

    def delete_reviewed_candidates(
        self,
        deleted_by: str,
        older_than_days: int | None = None,
        reason: str | None = None,
    ) -> int:
        """Delete all reviewed candidates, optionally filtered by age.

        This permanently removes reviewed candidates and their associated
        reviews and extractions. Use with caution.

        Args:
            deleted_by: Who is performing the deletion.
            older_than_days: Only delete candidates reviewed more than this
                many days ago. If None, deletes all reviewed candidates.
            reason: Optional reason for bulk deletion.

        Returns:
            Number of candidates deleted.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Build the WHERE clause
            if older_than_days is not None:
                age_clause = f"AND updated_at < datetime('now', '-{older_than_days} days')"
            else:
                age_clause = ""

            # Get candidates to delete (for logging)
            cursor.execute(
                f"""
                SELECT id, patient_mrn, medication_name, final_classification
                FROM indication_candidates
                WHERE status = 'reviewed' {age_clause}
                """,
            )
            candidates_to_delete = cursor.fetchall()

            if not candidates_to_delete:
                logger.info("No reviewed candidates to delete")
                return 0

            candidate_ids = [c["id"] for c in candidates_to_delete]
            placeholders = ",".join("?" * len(candidate_ids))

            # Delete extractions for these candidates
            cursor.execute(
                f"DELETE FROM indication_extractions WHERE candidate_id IN ({placeholders})",
                candidate_ids,
            )
            extractions_deleted = cursor.rowcount

            # Delete reviews for these candidates
            cursor.execute(
                f"DELETE FROM indication_reviews WHERE candidate_id IN ({placeholders})",
                candidate_ids,
            )
            reviews_deleted = cursor.rowcount

            # Delete the candidates
            cursor.execute(
                f"DELETE FROM indication_candidates WHERE id IN ({placeholders})",
                candidate_ids,
            )
            candidates_deleted = cursor.rowcount

            conn.commit()

        # Log the bulk deletion
        _log_indication_activity(
            activity_type="bulk_deletion",
            entity_id="bulk",
            entity_type="indication_candidates",
            action_taken="bulk_deleted",
            provider_name=deleted_by,
            outcome=f"deleted {candidates_deleted} candidates",
            details={
                "candidates_deleted": candidates_deleted,
                "extractions_deleted": extractions_deleted,
                "reviews_deleted": reviews_deleted,
                "older_than_days": older_than_days,
                "reason": reason,
            },
        )

        logger.info(
            f"Bulk deleted {candidates_deleted} reviewed candidates by {deleted_by}: "
            f"{extractions_deleted} extractions, {reviews_deleted} reviews"
        )
        return candidates_deleted

    def get_reviewed_candidates_count(self, older_than_days: int | None = None) -> int:
        """Get count of reviewed candidates, optionally filtered by age.

        Args:
            older_than_days: Only count candidates reviewed more than this
                many days ago. If None, counts all reviewed candidates.

        Returns:
            Number of reviewed candidates matching criteria.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if older_than_days is not None:
                cursor.execute(
                    """
                    SELECT COUNT(*) as count FROM indication_candidates
                    WHERE status = 'reviewed'
                    AND updated_at < datetime('now', ?)
                    """,
                    (f"-{older_than_days} days",),
                )
            else:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM indication_candidates WHERE status = 'reviewed'"
                )

            return cursor.fetchone()["count"]

    def auto_accept_old_candidates(self, hours: int = 48) -> int:
        """Auto-accept candidates older than specified hours without human review.

        This prevents the review queue from growing indefinitely. Candidates
        that haven't been reviewed within the time limit are auto-accepted
        with the LLM's classification.

        Args:
            hours: Hours after which to auto-accept. Default 48.

        Returns:
            Number of candidates auto-accepted.
        """
        auto_accepted = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Find candidates that:
            # 1. Are not yet reviewed (status != 'reviewed')
            # 2. Were created more than `hours` ago
            # 3. Don't already have a review
            cursor.execute(
                """
                SELECT c.id, c.clinical_syndrome, c.clinical_syndrome_display
                FROM indication_candidates c
                LEFT JOIN indication_reviews r ON c.id = r.candidate_id
                WHERE c.status != 'reviewed'
                AND c.created_at < datetime('now', ?)
                AND r.id IS NULL
                """,
                (f"-{hours} hours",),
            )

            candidates = cursor.fetchall()

            for row in candidates:
                candidate_id = row["id"]
                clinical_syndrome = row["clinical_syndrome"]
                clinical_syndrome_display = row["clinical_syndrome_display"]

                # Create auto-accept review
                review_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO indication_reviews (
                        id, candidate_id, reviewer, reviewer_decision,
                        is_override, notes,
                        syndrome_decision, confirmed_syndrome, confirmed_syndrome_display,
                        agent_decision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        candidate_id,
                        "Auto accepted",
                        "confirm_appropriate",
                        0,  # Not an override
                        f"Auto-accepted after {hours} hours without human review",
                        "confirm_syndrome",
                        clinical_syndrome,
                        clinical_syndrome_display,
                        "agent_skip",
                    ),
                )

                # Update candidate status
                cursor.execute(
                    "UPDATE indication_candidates SET status = 'reviewed', updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), candidate_id),
                )

                auto_accepted += 1

            conn.commit()

        if auto_accepted > 0:
            logger.info(f"Auto-accepted {auto_accepted} candidates older than {hours} hours")

        return auto_accepted

    def get_top_clinical_syndromes(self, days: int = 7, limit: int = 5) -> list[dict]:
        """Get the top clinical syndromes by count.

        Args:
            days: Number of days to look back.
            limit: Maximum number of syndromes to return.

        Returns:
            List of dicts with syndrome info and counts.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    clinical_syndrome,
                    clinical_syndrome_display,
                    syndrome_category,
                    COUNT(*) as count
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                AND clinical_syndrome IS NOT NULL
                AND clinical_syndrome != ''
                GROUP BY clinical_syndrome
                ORDER BY count DESC
                LIMIT ?
                """,
                (f"-{days} days", limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append({
                    "syndrome": row["clinical_syndrome"],
                    "display": row["clinical_syndrome_display"] or row["clinical_syndrome"],
                    "category": row["syndrome_category"],
                    "count": row["count"],
                })

            return results

    def get_syndrome_stats(self, days: int = 7) -> dict:
        """Get statistics about clinical syndromes.

        Args:
            days: Number of days to look back.

        Returns:
            Dict with syndrome statistics.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total candidates with syndromes
            cursor.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN clinical_syndrome IS NOT NULL AND clinical_syndrome != '' THEN 1 ELSE 0 END) as with_syndrome,
                       SUM(CASE WHEN likely_viral = 1 THEN 1 ELSE 0 END) as viral_flags,
                       SUM(CASE WHEN asymptomatic_bacteriuria = 1 THEN 1 ELSE 0 END) as asb_flags,
                       SUM(CASE WHEN indication_not_documented = 1 THEN 1 ELSE 0 END) as no_indication_flags
                FROM indication_candidates
                WHERE created_at >= datetime('now', ?)
                """,
                (f"-{days} days",),
            )
            row = cursor.fetchone()

            return {
                "total": row["total"] or 0,
                "with_syndrome": row["with_syndrome"] or 0,
                "viral_flags": row["viral_flags"] or 0,
                "asb_flags": row["asb_flags"] or 0,
                "no_indication_flags": row["no_indication_flags"] or 0,
                "days": days,
            }

    def get_agent_appropriateness_stats(self, days: int = 30) -> dict:
        """Get agent appropriateness statistics from reviews.

        Only includes reviews where agent_decision was actually assessed
        (not skipped or null).

        Args:
            days: Number of days to look back.

        Returns:
            Dict with appropriateness stats, or empty dict if no data.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    agent_decision,
                    COUNT(*) as count
                FROM indication_reviews
                WHERE reviewed_at >= datetime('now', ?)
                AND agent_decision IS NOT NULL
                AND agent_decision != ''
                AND agent_decision != 'agent_skip'
                GROUP BY agent_decision
                ORDER BY count DESC
                """,
                (f"-{days} days",),
            )

            results = {}
            total = 0
            for row in cursor.fetchall():
                decision = row["agent_decision"]
                count = row["count"]
                results[decision] = count
                total += count

            if total == 0:
                return {}

            return {
                "total_assessed": total,
                "appropriate": results.get("agent_appropriate", 0),
                "acceptable": results.get("agent_acceptable", 0),
                "inappropriate": results.get("agent_inappropriate", 0),
                "appropriate_rate": (results.get("agent_appropriate", 0) + results.get("agent_acceptable", 0)) / total if total > 0 else 0,
                "days": days,
            }
