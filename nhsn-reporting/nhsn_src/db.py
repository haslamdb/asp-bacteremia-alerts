"""Database operations for NHSN reporting module."""

import json
import logging
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from .models import (
    HAICandidate,
    HAIType,
    CandidateStatus,
    Classification,
    ClassificationDecision,
    Review,
    ReviewQueueType,
    ReviewerDecision,
    NHSNEvent,
    Patient,
    CultureResult,
    DeviceInfo,
    SupportingEvidence,
    LLMAuditEntry,
)

logger = logging.getLogger(__name__)


class NHSNDatabase:
    """SQLite database for NHSN candidate and classification storage."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        schema_path = Path(__file__).parent.parent / "schema.sql"
        with open(schema_path) as f:
            schema = f.read()

        with self._get_connection() as conn:
            conn.executescript(schema)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- Candidate Operations ---

    def save_candidate(self, candidate: HAICandidate) -> None:
        """Save or update an HAI candidate."""
        row = candidate.to_db_row()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO hai_candidates (
                    id, hai_type, patient_id, patient_mrn, patient_name,
                    culture_id, culture_date, organism, device_info,
                    device_days_at_culture, meets_initial_criteria,
                    exclusion_reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["hai_type"],
                    row["patient_id"],
                    row["patient_mrn"],
                    row["patient_name"],
                    row["culture_id"],
                    row["culture_date"],
                    row["organism"],
                    row["device_info"],
                    row["device_days_at_culture"],
                    row["meets_initial_criteria"],
                    row["exclusion_reason"],
                    row["status"],
                    row["created_at"],
                ),
            )
            conn.commit()

    def get_candidate(self, candidate_id: str) -> HAICandidate | None:
        """Get a candidate by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM hai_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            if row:
                return self._row_to_candidate(row)
            return None

    def get_candidates_by_status(
        self, status: CandidateStatus, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get candidates by status."""
        with self._get_connection() as conn:
            if hai_type:
                rows = conn.execute(
                    "SELECT * FROM hai_candidates WHERE status = ? AND hai_type = ? ORDER BY created_at DESC",
                    (status.value, hai_type.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM hai_candidates WHERE status = ? ORDER BY created_at DESC",
                    (status.value,),
                ).fetchall()
            return [self._row_to_candidate(row) for row in rows]

    def get_recent_candidates(
        self, limit: int = 100, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get recent candidates."""
        with self._get_connection() as conn:
            if hai_type:
                rows = conn.execute(
                    "SELECT * FROM hai_candidates WHERE hai_type = ? ORDER BY created_at DESC LIMIT ?",
                    (hai_type.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM hai_candidates ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._row_to_candidate(row) for row in rows]

    def get_active_candidates(
        self, limit: int = 100, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get active candidates (pending, classified, pending_review)."""
        active_statuses = (
            CandidateStatus.PENDING.value,
            CandidateStatus.CLASSIFIED.value,
            CandidateStatus.PENDING_REVIEW.value,
        )
        with self._get_connection() as conn:
            if hai_type:
                rows = conn.execute(
                    f"SELECT * FROM hai_candidates WHERE status IN (?, ?, ?) AND hai_type = ? ORDER BY created_at DESC LIMIT ?",
                    (*active_statuses, hai_type.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM hai_candidates WHERE status IN (?, ?, ?) ORDER BY created_at DESC LIMIT ?",
                    (*active_statuses, limit),
                ).fetchall()
            return [self._row_to_candidate(row) for row in rows]

    def get_resolved_candidates(
        self, limit: int = 100, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get resolved candidates (confirmed or rejected) for history."""
        resolved_statuses = (
            CandidateStatus.CONFIRMED.value,
            CandidateStatus.REJECTED.value,
        )
        with self._get_connection() as conn:
            if hai_type:
                rows = conn.execute(
                    f"SELECT * FROM hai_candidates WHERE status IN (?, ?) AND hai_type = ? ORDER BY created_at DESC LIMIT ?",
                    (*resolved_statuses, hai_type.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM hai_candidates WHERE status IN (?, ?) ORDER BY created_at DESC LIMIT ?",
                    (*resolved_statuses, limit),
                ).fetchall()
            return [self._row_to_candidate(row) for row in rows]

    def check_candidate_exists(self, hai_type: HAIType, culture_id: str) -> bool:
        """Check if a candidate already exists for this culture."""
        with self._get_connection() as conn:
            result = conn.execute(
                "SELECT 1 FROM hai_candidates WHERE hai_type = ? AND culture_id = ?",
                (hai_type.value, culture_id),
            ).fetchone()
            return result is not None

    def update_candidate_status(
        self, candidate_id: str, status: CandidateStatus
    ) -> None:
        """Update candidate status."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE hai_candidates SET status = ? WHERE id = ?",
                (status.value, candidate_id),
            )
            conn.commit()

    def _row_to_candidate(self, row: sqlite3.Row) -> HAICandidate:
        """Convert database row to HAICandidate."""
        device_info = None
        if row["device_info"]:
            di = json.loads(row["device_info"])
            device_info = DeviceInfo(
                device_type=di["device_type"],
                insertion_date=datetime.fromisoformat(di["insertion_date"])
                if di.get("insertion_date")
                else None,
                removal_date=datetime.fromisoformat(di["removal_date"])
                if di.get("removal_date")
                else None,
                site=di.get("site"),
                fhir_id=di.get("fhir_id"),
            )

        # Check for nhsn_reported column (may not exist in older databases)
        nhsn_reported = False
        try:
            nhsn_reported = bool(row["nhsn_reported"]) if row["nhsn_reported"] else False
        except (IndexError, KeyError):
            pass

        candidate = HAICandidate(
            id=row["id"],
            hai_type=HAIType(row["hai_type"]),
            patient=Patient(
                fhir_id=row["patient_id"],
                mrn=row["patient_mrn"],
                name=row["patient_name"] or "",
            ),
            culture=CultureResult(
                fhir_id=row["culture_id"],
                collection_date=datetime.fromisoformat(row["culture_date"]),
                organism=row["organism"],
            ),
            device_info=device_info,
            device_days_at_culture=row["device_days_at_culture"],
            meets_initial_criteria=bool(row["meets_initial_criteria"]),
            exclusion_reason=row["exclusion_reason"],
            status=CandidateStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
        candidate.nhsn_reported = nhsn_reported
        return candidate

    # --- Classification Operations ---

    def save_classification(self, classification: Classification) -> None:
        """Save an LLM classification."""
        row = classification.to_db_row()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO nhsn_classifications (
                    id, candidate_id, decision, confidence, alternative_source,
                    is_mbi_lcbi, supporting_evidence, contradicting_evidence,
                    reasoning, model_used, prompt_version, tokens_used,
                    processing_time_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["candidate_id"],
                    row["decision"],
                    row["confidence"],
                    row["alternative_source"],
                    row["is_mbi_lcbi"],
                    row["supporting_evidence"],
                    row["contradicting_evidence"],
                    row["reasoning"],
                    row["model_used"],
                    row["prompt_version"],
                    row["tokens_used"],
                    row["processing_time_ms"],
                    row["created_at"],
                ),
            )
            conn.commit()

    def get_classification(self, classification_id: str) -> Classification | None:
        """Get a classification by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM nhsn_classifications WHERE id = ?", (classification_id,)
            ).fetchone()
            if row:
                return self._row_to_classification(row)
            return None

    def get_classifications_for_candidate(
        self, candidate_id: str
    ) -> list[Classification]:
        """Get all classifications for a candidate."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM nhsn_classifications WHERE candidate_id = ? ORDER BY created_at DESC",
                (candidate_id,),
            ).fetchall()
            return [self._row_to_classification(row) for row in rows]

    def _row_to_classification(self, row: sqlite3.Row) -> Classification:
        """Convert database row to Classification."""
        supporting = []
        if row["supporting_evidence"]:
            for e in json.loads(row["supporting_evidence"]):
                supporting.append(
                    SupportingEvidence(
                        text=e["text"],
                        source=e["source"],
                        date=datetime.fromisoformat(e["date"]) if e.get("date") else None,
                        relevance=e.get("relevance"),
                    )
                )

        contradicting = []
        if row["contradicting_evidence"]:
            for e in json.loads(row["contradicting_evidence"]):
                contradicting.append(
                    SupportingEvidence(
                        text=e["text"],
                        source=e["source"],
                        date=datetime.fromisoformat(e["date"]) if e.get("date") else None,
                        relevance=e.get("relevance"),
                    )
                )

        return Classification(
            id=row["id"],
            candidate_id=row["candidate_id"],
            decision=ClassificationDecision(row["decision"]),
            confidence=row["confidence"],
            alternative_source=row["alternative_source"],
            is_mbi_lcbi=bool(row["is_mbi_lcbi"]),
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            reasoning=row["reasoning"],
            model_used=row["model_used"],
            prompt_version=row["prompt_version"],
            tokens_used=row["tokens_used"] or 0,
            processing_time_ms=row["processing_time_ms"] or 0,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # --- Review Operations ---

    def save_review(self, review: Review) -> None:
        """Save a review queue entry."""
        row = review.to_db_row()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO nhsn_reviews (
                    id, candidate_id, classification_id, queue_type, reviewed,
                    reviewer, reviewer_decision, reviewer_notes, created_at, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["candidate_id"],
                    row["classification_id"],
                    row["queue_type"],
                    row["reviewed"],
                    row["reviewer"],
                    row["reviewer_decision"],
                    row["reviewer_notes"],
                    row["created_at"],
                    row["reviewed_at"],
                ),
            )
            conn.commit()

    def get_pending_reviews(
        self, queue_type: ReviewQueueType | None = None
    ) -> list[dict[str, Any]]:
        """Get pending reviews with candidate and classification info."""
        with self._get_connection() as conn:
            if queue_type:
                rows = conn.execute(
                    "SELECT * FROM nhsn_pending_reviews WHERE queue_type = ?",
                    (queue_type.value,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM nhsn_pending_reviews").fetchall()
            return [dict(row) for row in rows]

    def save_review(
        self,
        candidate_id: str,
        reviewer: str,
        decision: ReviewerDecision,
        notes: str | None = None,
        classification_id: str | None = None,
        is_completed: bool = True,
        llm_decision: str | None = None,
        is_override: bool = False,
        override_reason: str | None = None,
    ) -> str:
        """Save a new review entry with individual parameters.

        Args:
            candidate_id: The candidate being reviewed
            reviewer: Name of the reviewer
            decision: The review decision
            notes: Optional notes about the decision
            classification_id: Optional linked classification
            is_completed: Whether this is a final decision (False for "needs more info")
            llm_decision: Original LLM classification decision
            is_override: Whether reviewer disagreed with LLM
            override_reason: Reason for override if applicable
        """
        import uuid
        review_id = str(uuid.uuid4())
        now = datetime.now()

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO nhsn_reviews (
                    id, candidate_id, classification_id, queue_type, reviewed,
                    reviewer, reviewer_decision, reviewer_notes,
                    llm_decision, is_override, override_reason,
                    created_at, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    candidate_id,
                    classification_id,
                    ReviewQueueType.IP_REVIEW.value,
                    is_completed,
                    reviewer,
                    decision.value,
                    notes,
                    llm_decision,
                    is_override,
                    override_reason,
                    now.isoformat(),
                    now.isoformat() if is_completed else None,
                ),
            )
            conn.commit()
        return review_id

    def save_review_object(self, review: Review) -> None:
        """Save a Review object to the database."""
        row = review.to_db_row()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO nhsn_reviews (
                    id, candidate_id, classification_id, queue_type, reviewed,
                    reviewer, reviewer_decision, reviewer_notes,
                    llm_decision, is_override, override_reason,
                    created_at, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["candidate_id"],
                    row["classification_id"],
                    row["queue_type"],
                    row["reviewed"],
                    row["reviewer"],
                    row["reviewer_decision"],
                    row["reviewer_notes"],
                    row["llm_decision"],
                    row["is_override"],
                    row["override_reason"],
                    row["created_at"],
                    row["reviewed_at"],
                ),
            )
            conn.commit()

    def complete_review(
        self,
        review_id: str,
        reviewer: str,
        decision: ReviewerDecision,
        notes: str | None = None,
    ) -> None:
        """Mark a review as complete."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE nhsn_reviews
                SET reviewed = 1, reviewer = ?, reviewer_decision = ?,
                    reviewer_notes = ?, reviewed_at = ?
                WHERE id = ?
                """,
                (
                    reviewer,
                    decision.value,
                    notes,
                    datetime.now().isoformat(),
                    review_id,
                ),
            )
            conn.commit()

    def supersede_old_reviews(self, candidate_id: str, superseding_review_id: str) -> int:
        """Mark any prior incomplete reviews for a candidate as superseded.

        When a final decision is submitted, any previous "needs_more_info" reviews
        should be marked as reviewed=1 so they don't appear in the pending queue.

        Args:
            candidate_id: The candidate whose old reviews to supersede
            superseding_review_id: The ID of the new final review (to exclude from update)

        Returns:
            Number of reviews that were superseded
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE nhsn_reviews
                SET reviewed = 1,
                    reviewer_notes = COALESCE(reviewer_notes || ' ', '') || '[Superseded by later review]',
                    reviewed_at = ?
                WHERE candidate_id = ?
                  AND reviewed = 0
                  AND id != ?
                """,
                (
                    datetime.now().isoformat(),
                    candidate_id,
                    superseding_review_id,
                ),
            )
            conn.commit()
            return cursor.rowcount

    # --- NHSN Event Operations ---

    def save_event(self, event: NHSNEvent) -> None:
        """Save a confirmed NHSN event."""
        row = event.to_db_row()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO nhsn_events (
                    id, candidate_id, event_date, hai_type, location_code,
                    pathogen_code, reported, reported_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["candidate_id"],
                    row["event_date"],
                    row["hai_type"],
                    row["location_code"],
                    row["pathogen_code"],
                    row["reported"],
                    row["reported_at"],
                    row["created_at"],
                ),
            )
            conn.commit()

    def get_unreported_events(self) -> list[NHSNEvent]:
        """Get events that haven't been reported to NHSN yet."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM nhsn_events WHERE reported = 0 ORDER BY event_date"
            ).fetchall()
            return [self._row_to_event(row) for row in rows]

    def mark_event_reported(self, event_id: str) -> None:
        """Mark an event as reported."""
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE nhsn_events SET reported = 1, reported_at = ? WHERE id = ?",
                (datetime.now().isoformat(), event_id),
            )
            conn.commit()

    def _row_to_event(self, row: sqlite3.Row) -> NHSNEvent:
        """Convert database row to NHSNEvent."""
        return NHSNEvent(
            id=row["id"],
            candidate_id=row["candidate_id"],
            event_date=date.fromisoformat(row["event_date"]),
            hai_type=HAIType(row["hai_type"]),
            location_code=row["location_code"],
            pathogen_code=row["pathogen_code"],
            reported=bool(row["reported"]),
            reported_at=datetime.fromisoformat(row["reported_at"])
            if row["reported_at"]
            else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # --- Audit Operations ---

    def log_llm_call(self, entry: LLMAuditEntry) -> None:
        """Log an LLM API call for auditing."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO nhsn_llm_audit (
                    candidate_id, model, success, input_tokens, output_tokens,
                    response_time_ms, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.candidate_id,
                    entry.model,
                    entry.success,
                    entry.input_tokens,
                    entry.output_tokens,
                    entry.response_time_ms,
                    entry.error_message,
                    entry.created_at.isoformat(),
                ),
            )
            conn.commit()

    # --- Statistics ---

    def get_candidate_stats(self) -> list[dict[str, Any]]:
        """Get candidate statistics by type and status."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM nhsn_candidate_stats").fetchall()
            return [dict(row) for row in rows]

    def get_summary_stats(self, since_date: str | None = None) -> dict[str, Any]:
        """Get overall summary statistics.

        Args:
            since_date: Optional date string (YYYY-MM-DD) to filter stats.
                       If provided, only counts candidates created after this date.
                       Typically set to the last NHSN submission date.

        Returns:
            Dictionary with summary statistics.
        """
        with self._get_connection() as conn:
            # Build date filter clause
            date_filter = ""
            date_params = ()
            if since_date:
                date_filter = " AND created_at >= ?"
                date_params = (since_date,)

            total = conn.execute(
                f"SELECT COUNT(*) FROM hai_candidates WHERE 1=1{date_filter}",
                date_params,
            ).fetchone()[0]
            pending = conn.execute(
                f"SELECT COUNT(*) FROM hai_candidates WHERE status = 'pending'{date_filter}",
                date_params,
            ).fetchone()[0]
            pending_review = conn.execute(
                f"SELECT COUNT(*) FROM hai_candidates WHERE status = 'pending_review'{date_filter}",
                date_params,
            ).fetchone()[0]
            confirmed = conn.execute(
                f"SELECT COUNT(*) FROM hai_candidates WHERE status = 'confirmed'{date_filter}",
                date_params,
            ).fetchone()[0]
            rejected = conn.execute(
                f"SELECT COUNT(*) FROM hai_candidates WHERE status = 'rejected'{date_filter}",
                date_params,
            ).fetchone()[0]

            return {
                "total_candidates": total,
                "pending_classification": pending,
                "pending_review": pending_review,
                "confirmed_hai": confirmed,
                "rejected_hai": rejected,
                "since_date": since_date,
            }

    def get_override_stats(self) -> dict[str, Any]:
        """Get LLM classification override statistics.

        Returns:
            Dictionary with override metrics for assessing LLM quality.
        """
        with self._get_connection() as conn:
            # Check if override columns exist
            cursor = conn.execute("PRAGMA table_info(nhsn_reviews)")
            columns = [row[1] for row in cursor.fetchall()]

            if "is_override" not in columns:
                # Override tracking not yet in place
                return {
                    "total_reviews": 0,
                    "completed_reviews": 0,
                    "total_overrides": 0,
                    "accepted_classifications": 0,
                    "acceptance_rate_pct": None,
                    "override_rate_pct": None,
                    "by_llm_decision": {},
                }

            # Total reviews
            total = conn.execute("SELECT COUNT(*) FROM nhsn_reviews").fetchone()[0]

            # Completed reviews
            completed = conn.execute(
                "SELECT COUNT(*) FROM nhsn_reviews WHERE reviewed = 1"
            ).fetchone()[0]

            # Total overrides
            overrides = conn.execute(
                "SELECT COUNT(*) FROM nhsn_reviews WHERE is_override = 1"
            ).fetchone()[0]

            # Accepted (completed and not override)
            accepted = conn.execute(
                "SELECT COUNT(*) FROM nhsn_reviews WHERE reviewed = 1 AND is_override = 0"
            ).fetchone()[0]

            # Calculate rates
            acceptance_rate = (accepted / completed * 100) if completed > 0 else None
            override_rate = (overrides / completed * 100) if completed > 0 else None

            # Breakdown by LLM decision
            by_decision_rows = conn.execute(
                """
                SELECT llm_decision,
                       COUNT(*) as total,
                       SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) as overrides
                FROM nhsn_reviews
                WHERE reviewed = 1 AND llm_decision IS NOT NULL
                GROUP BY llm_decision
                """
            ).fetchall()

            by_decision = {}
            for row in by_decision_rows:
                decision = row["llm_decision"]
                total_for_decision = row["total"]
                overrides_for_decision = row["overrides"]
                by_decision[decision] = {
                    "total": total_for_decision,
                    "overrides": overrides_for_decision,
                    "override_rate_pct": (
                        overrides_for_decision / total_for_decision * 100
                        if total_for_decision > 0
                        else 0
                    ),
                }

            return {
                "total_reviews": total,
                "completed_reviews": completed,
                "total_overrides": overrides,
                "accepted_classifications": accepted,
                "acceptance_rate_pct": round(acceptance_rate, 1) if acceptance_rate else None,
                "override_rate_pct": round(override_rate, 1) if override_rate else None,
                "by_llm_decision": by_decision,
            }

    def get_recent_overrides(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent override details for analysis.

        Args:
            limit: Maximum number of overrides to return

        Returns:
            List of override details
        """
        with self._get_connection() as conn:
            # Check if override columns exist
            cursor = conn.execute("PRAGMA table_info(nhsn_reviews)")
            columns = [row[1] for row in cursor.fetchall()]

            if "is_override" not in columns:
                return []

            rows = conn.execute(
                """
                SELECT r.*, c.patient_mrn, c.organism
                FROM nhsn_reviews r
                JOIN hai_candidates c ON r.candidate_id = c.id
                WHERE r.is_override = 1
                ORDER BY r.reviewed_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            return [
                {
                    "review_id": row["id"],
                    "patient_mrn": row["patient_mrn"],
                    "organism": row["organism"],
                    "llm_decision": row["llm_decision"],
                    "reviewer_decision": row["reviewer_decision"],
                    "reviewer": row["reviewer"],
                    "reviewer_notes": row["reviewer_notes"],
                    "override_reason": row["override_reason"],
                    "reviewed_at": row["reviewed_at"],
                }
                for row in rows
            ]

    # --- Reporting ---

    def get_confirmed_hai_in_period(
        self, days: int = 30, hai_type: HAIType | None = None
    ) -> list[HAICandidate]:
        """Get confirmed HAI candidates in the given time period.

        Args:
            days: Number of days to look back
            hai_type: Filter by HAI type (all types if None)

        Returns:
            List of confirmed HAI candidates
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_connection() as conn:
            if hai_type:
                rows = conn.execute(
                    """
                    SELECT * FROM hai_candidates
                    WHERE status = 'confirmed'
                    AND hai_type = ?
                    AND created_at >= ?
                    ORDER BY created_at DESC
                    """,
                    (hai_type.value, cutoff),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM hai_candidates
                    WHERE status = 'confirmed'
                    AND created_at >= ?
                    ORDER BY created_at DESC
                    """,
                    (cutoff,),
                ).fetchall()

            return [self._row_to_candidate(row) for row in rows]

    def get_hai_counts_by_type(
        self, days: int = 30, since_date: str | None = None
    ) -> dict[str, int]:
        """Get counts of confirmed HAI by type in the given period.

        Args:
            days: Number of days to look back (ignored if since_date provided)
            since_date: Optional date string (YYYY-MM-DD) to filter from

        Returns:
            Dictionary mapping HAI type to count
        """
        if since_date:
            cutoff = since_date
        else:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT hai_type, COUNT(*) as count
                FROM hai_candidates
                WHERE status = 'confirmed'
                AND created_at >= ?
                GROUP BY hai_type
                ORDER BY count DESC
                """,
                (cutoff,),
            ).fetchall()

            return {row["hai_type"]: row["count"] for row in rows}

    def get_hai_counts_by_day(
        self,
        days: int = 30,
        since_date: str | None = None,
        hai_type: HAIType | None = None,
    ) -> list[dict]:
        """Get daily counts of confirmed HAI in the given period.

        Args:
            days: Number of days to look back (ignored if since_date provided)
            since_date: Optional date string (YYYY-MM-DD) to filter from
            hai_type: Filter by HAI type (all types if None)

        Returns:
            List of dicts with 'date' and 'count' keys
        """
        if since_date:
            cutoff = since_date
        else:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_connection() as conn:
            if hai_type:
                rows = conn.execute(
                    """
                    SELECT DATE(created_at) as date, COUNT(*) as count
                    FROM hai_candidates
                    WHERE status = 'confirmed'
                    AND hai_type = ?
                    AND created_at >= ?
                    GROUP BY DATE(created_at)
                    ORDER BY date
                    """,
                    (hai_type.value, cutoff),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT DATE(created_at) as date, COUNT(*) as count
                    FROM hai_candidates
                    WHERE status = 'confirmed'
                    AND created_at >= ?
                    GROUP BY DATE(created_at)
                    ORDER BY date
                    """,
                    (cutoff,),
                ).fetchall()

            return [{"date": row["date"], "count": row["count"]} for row in rows]

    def get_hai_report_data(
        self, days: int = 30, since_date: str | None = None
    ) -> dict[str, Any]:
        """Get comprehensive HAI report data.

        Args:
            days: Number of days to look back (ignored if since_date provided)
            since_date: Optional date string (YYYY-MM-DD) to filter from.
                       Typically set to last NHSN submission date.

        Returns:
            Dictionary with all report metrics
        """
        if since_date:
            cutoff = since_date
        else:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_connection() as conn:
            # Total confirmed in period
            total_confirmed = conn.execute(
                """
                SELECT COUNT(*) FROM hai_candidates
                WHERE status = 'confirmed' AND created_at >= ?
                """,
                (cutoff,),
            ).fetchone()[0]

            # Total rejected in period
            total_rejected = conn.execute(
                """
                SELECT COUNT(*) FROM hai_candidates
                WHERE status = 'rejected' AND created_at >= ?
                """,
                (cutoff,),
            ).fetchone()[0]

            # Total reviewed (confirmed + rejected)
            total_reviewed = total_confirmed + total_rejected

            # Confirmation rate
            confirmation_rate = (
                (total_confirmed / total_reviewed * 100) if total_reviewed > 0 else 0
            )

            # Counts by type
            by_type = self.get_hai_counts_by_type(days, since_date)

            # Counts by day
            by_day = self.get_hai_counts_by_day(days, since_date)

            # Get review decision breakdown
            review_breakdown = conn.execute(
                """
                SELECT reviewer_decision, COUNT(*) as count
                FROM nhsn_reviews
                WHERE reviewed = 1
                AND created_at >= ?
                GROUP BY reviewer_decision
                ORDER BY count DESC
                """,
                (cutoff,),
            ).fetchall()

            return {
                "total_confirmed": total_confirmed,
                "total_rejected": total_rejected,
                "total_reviewed": total_reviewed,
                "confirmation_rate": confirmation_rate,
                "by_type": by_type,
                "by_day": by_day,
                "review_breakdown": [
                    {"decision": row["reviewer_decision"], "count": row["count"]}
                    for row in review_breakdown
                ],
                "since_date": since_date,
            }

    # --- NHSN Submission Operations ---

    def get_confirmed_hai_in_date_range(
        self, from_date: datetime, to_date: datetime
    ) -> list[HAICandidate]:
        """Get confirmed HAI candidates in a specific date range.

        Args:
            from_date: Start date (inclusive)
            to_date: End date (inclusive)

        Returns:
            List of confirmed HAI candidates
        """
        # Convert to ISO format strings
        from_str = from_date.strftime("%Y-%m-%d")
        to_str = (to_date + timedelta(days=1)).strftime("%Y-%m-%d")  # Include the end date

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM hai_candidates
                WHERE status = 'confirmed'
                AND DATE(culture_date) >= DATE(?)
                AND DATE(culture_date) < DATE(?)
                ORDER BY culture_date DESC
                """,
                (from_str, to_str),
            ).fetchall()

            return [self._row_to_candidate(row) for row in rows]

    def mark_events_as_submitted(self, candidate_ids: list[str]) -> int:
        """Mark candidates as submitted to NHSN.

        Args:
            candidate_ids: List of candidate IDs to mark as submitted

        Returns:
            Number of candidates marked
        """
        if not candidate_ids:
            return 0

        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            # Update the nhsn_reported flag (we need to add this column if it doesn't exist)
            # First check if column exists
            cursor = conn.execute("PRAGMA table_info(hai_candidates)")
            columns = [row[1] for row in cursor.fetchall()]

            if "nhsn_reported" not in columns:
                conn.execute(
                    "ALTER TABLE hai_candidates ADD COLUMN nhsn_reported INTEGER DEFAULT 0"
                )
                conn.execute(
                    "ALTER TABLE hai_candidates ADD COLUMN nhsn_reported_at TEXT"
                )

            placeholders = ",".join(["?" for _ in candidate_ids])
            conn.execute(
                f"""
                UPDATE hai_candidates
                SET nhsn_reported = 1, nhsn_reported_at = ?
                WHERE id IN ({placeholders})
                """,
                [now] + candidate_ids,
            )
            conn.commit()

            return len(candidate_ids)

    def log_submission_action(
        self,
        action: str,
        user_name: str,
        period_start: str,
        period_end: str,
        event_count: int,
        notes: str | None = None,
    ) -> str:
        """Log a submission-related action (export, submission, etc).

        Args:
            action: Type of action (exported, submitted, etc.)
            user_name: Name of the user performing the action
            period_start: Start of reporting period
            period_end: End of reporting period
            event_count: Number of events in the action
            notes: Optional notes

        Returns:
            ID of the log entry
        """
        import uuid

        log_id = str(uuid.uuid4())
        now = datetime.now()

        with self._get_connection() as conn:
            # Create table if not exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nhsn_submission_audit (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                INSERT INTO nhsn_submission_audit (
                    id, action, user_name, period_start, period_end, event_count, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, action, user_name, period_start, period_end, event_count, notes, now.isoformat()),
            )
            conn.commit()

        return log_id

    def get_last_submission(self) -> dict[str, Any] | None:
        """Get the most recent submission to NHSN.

        Returns:
            Dictionary with last submission info, or None if no submissions
        """
        with self._get_connection() as conn:
            # Create table if not exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nhsn_submission_audit (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            row = conn.execute(
                """
                SELECT * FROM nhsn_submission_audit
                WHERE action = 'submitted'
                ORDER BY created_at DESC
                LIMIT 1
                """,
            ).fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "action": row["action"],
                "user_name": row["user_name"],
                "period_start": row["period_start"],
                "period_end": row["period_end"],
                "event_count": row["event_count"],
                "notes": row["notes"],
                "created_at": datetime.fromisoformat(row["created_at"]),
            }

    def get_submission_audit_log(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get the submission audit log.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of audit log entries
        """
        with self._get_connection() as conn:
            # Create table if not exists (in case it hasn't been created yet)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nhsn_submission_audit (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

            rows = conn.execute(
                """
                SELECT * FROM nhsn_submission_audit
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            result = []
            for row in rows:
                result.append({
                    "id": row["id"],
                    "action": row["action"],
                    "user_name": row["user_name"],
                    "period_start": row["period_start"],
                    "period_end": row["period_end"],
                    "event_count": row["event_count"],
                    "notes": row["notes"],
                    "created_at": datetime.fromisoformat(row["created_at"]),
                })

            return result
