"""Discrepancy logging for HAI classification.

This module logs cases where AEGIS classification differs from historic IP
classification. These discrepancies are valuable for:

1. Calibrating the rules engine strictness level
2. Identifying where CCHMC practice diverges from NHSN literal interpretation
3. Building evidence for other institutions evaluating AEGIS
4. Training data annotation and quality assurance

## Usage

```python
from hai_src.rules.discrepancy_logger import DiscrepancyLogger

logger = DiscrepancyLogger()

# After classification, compare with historic IP classification
logger.log_discrepancy(
    candidate_id="abc123",
    aegis_classification="clabsi",
    historic_ip_classification="secondary_bsi",
    aegis_reasoning=["No culture-confirmed alternate source", "..."],
    discrepancy_reason="UTI was not microbiologically confirmed",
    strictness_level="nhsn_moderate",
)

# Get statistics
stats = logger.get_discrepancy_stats()
print(f"Override rate: {stats['override_rate_pct']}%")
```

## Discrepancy Categories

- **upgrade**: AEGIS is stricter (calls CLABSI where IP called not-CLABSI)
- **downgrade**: AEGIS is more lenient (excludes where IP called CLABSI)
- **reclassify**: Different exclusion category (e.g., MBI-LCBI vs secondary)
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DiscrepancyRecord:
    """A single discrepancy between AEGIS and historic IP classification."""
    candidate_id: str
    patient_mrn: str | None
    organism: str | None
    culture_date: str | None

    # AEGIS classification
    aegis_classification: str
    aegis_confidence: float | None
    aegis_reasoning: list[str]
    strictness_level: str

    # Historic IP classification
    historic_ip_classification: str
    historic_reviewer: str | None = None
    historic_review_date: str | None = None

    # Discrepancy analysis
    discrepancy_type: str | None = None  # upgrade, downgrade, reclassify
    discrepancy_reason: str | None = None
    nhsn_criteria_applied: list[str] = field(default_factory=list)

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reviewed: bool = False
    review_notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "DiscrepancyRecord":
        """Create from dictionary."""
        return cls(**data)


class DiscrepancyLogger:
    """Logs and analyzes discrepancies between AEGIS and IP classifications.

    Discrepancies are stored in a SQLite database for analysis and reporting.
    The logger provides methods for:
    - Recording individual discrepancies
    - Aggregating statistics
    - Exporting for analysis
    """

    def __init__(self, db_path: str | Path | None = None):
        """Initialize the discrepancy logger.

        Args:
            db_path: Path to discrepancy database. Defaults to project data dir.
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "discrepancies.db"
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS classification_discrepancies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    patient_mrn TEXT,
                    organism TEXT,
                    culture_date TEXT,

                    aegis_classification TEXT NOT NULL,
                    aegis_confidence REAL,
                    aegis_reasoning TEXT,  -- JSON array
                    strictness_level TEXT NOT NULL,

                    historic_ip_classification TEXT NOT NULL,
                    historic_reviewer TEXT,
                    historic_review_date TEXT,

                    discrepancy_type TEXT,
                    discrepancy_reason TEXT,
                    nhsn_criteria_applied TEXT,  -- JSON array

                    created_at TEXT NOT NULL,
                    reviewed INTEGER DEFAULT 0,
                    review_notes TEXT,

                    UNIQUE(candidate_id, strictness_level)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_discrepancies_type
                ON classification_discrepancies(discrepancy_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_discrepancies_strictness
                ON classification_discrepancies(strictness_level)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_discrepancies_created
                ON classification_discrepancies(created_at)
            """)
            conn.commit()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def log_discrepancy(
        self,
        candidate_id: str,
        aegis_classification: str,
        historic_ip_classification: str,
        aegis_reasoning: list[str],
        strictness_level: str,
        aegis_confidence: float | None = None,
        patient_mrn: str | None = None,
        organism: str | None = None,
        culture_date: str | None = None,
        historic_reviewer: str | None = None,
        historic_review_date: str | None = None,
        discrepancy_reason: str | None = None,
        nhsn_criteria_applied: list[str] | None = None,
    ) -> int:
        """Log a classification discrepancy.

        Args:
            candidate_id: The HAI candidate ID
            aegis_classification: What AEGIS classified
            historic_ip_classification: What IP historically called it
            aegis_reasoning: AEGIS reasoning chain
            strictness_level: Which strictness level was used
            aegis_confidence: AEGIS confidence score
            patient_mrn: Patient MRN for reference
            organism: Culture organism
            culture_date: Culture collection date
            historic_reviewer: Who did the historic review
            historic_review_date: When the historic review occurred
            discrepancy_reason: Why they differ
            nhsn_criteria_applied: Which NHSN criteria AEGIS applied

        Returns:
            Database row ID of the logged discrepancy
        """
        # Determine discrepancy type
        discrepancy_type = self._classify_discrepancy(
            aegis_classification, historic_ip_classification
        )

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO classification_discrepancies (
                    candidate_id, patient_mrn, organism, culture_date,
                    aegis_classification, aegis_confidence, aegis_reasoning, strictness_level,
                    historic_ip_classification, historic_reviewer, historic_review_date,
                    discrepancy_type, discrepancy_reason, nhsn_criteria_applied,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    patient_mrn,
                    organism,
                    culture_date,
                    aegis_classification,
                    aegis_confidence,
                    json.dumps(aegis_reasoning),
                    strictness_level,
                    historic_ip_classification,
                    historic_reviewer,
                    historic_review_date,
                    discrepancy_type,
                    discrepancy_reason,
                    json.dumps(nhsn_criteria_applied or []),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            row_id = cursor.lastrowid

        logger.info(
            f"Logged discrepancy: {candidate_id} - AEGIS={aegis_classification}, "
            f"IP={historic_ip_classification}, type={discrepancy_type}"
        )
        return row_id

    def _classify_discrepancy(self, aegis: str, historic: str) -> str:
        """Classify the type of discrepancy.

        Args:
            aegis: AEGIS classification
            historic: Historic IP classification

        Returns:
            Discrepancy type: upgrade, downgrade, or reclassify
        """
        # Normalize to lowercase
        aegis = aegis.lower()
        historic = historic.lower()

        # Define "CLABSI" classifications
        clabsi_classifications = {"clabsi", "hai_confirmed", "confirmed"}
        non_clabsi_classifications = {
            "secondary_bsi", "mbi_lcbi", "contamination",
            "not_eligible", "not_hai", "rejected"
        }

        aegis_is_clabsi = aegis in clabsi_classifications
        historic_is_clabsi = historic in clabsi_classifications

        if aegis_is_clabsi and not historic_is_clabsi:
            return "upgrade"  # AEGIS stricter (calls CLABSI where IP didn't)
        elif not aegis_is_clabsi and historic_is_clabsi:
            return "downgrade"  # AEGIS more lenient (excludes where IP called CLABSI)
        else:
            return "reclassify"  # Different exclusion category

    def get_discrepancy(self, candidate_id: str, strictness_level: str | None = None) -> dict | None:
        """Get a specific discrepancy record.

        Args:
            candidate_id: The candidate ID
            strictness_level: Optional strictness level filter

        Returns:
            Discrepancy record as dict, or None
        """
        with self._get_connection() as conn:
            if strictness_level:
                row = conn.execute(
                    """
                    SELECT * FROM classification_discrepancies
                    WHERE candidate_id = ? AND strictness_level = ?
                    """,
                    (candidate_id, strictness_level),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM classification_discrepancies
                    WHERE candidate_id = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (candidate_id,),
                ).fetchone()

            if row:
                return self._row_to_dict(row)
            return None

    def get_discrepancy_stats(self, strictness_level: str | None = None) -> dict[str, Any]:
        """Get aggregate statistics on discrepancies.

        Args:
            strictness_level: Filter to specific strictness level

        Returns:
            Dictionary with discrepancy statistics
        """
        with self._get_connection() as conn:
            # Build filter
            where = ""
            params = ()
            if strictness_level:
                where = "WHERE strictness_level = ?"
                params = (strictness_level,)

            # Total discrepancies
            total = conn.execute(
                f"SELECT COUNT(*) FROM classification_discrepancies {where}",
                params,
            ).fetchone()[0]

            # By type
            by_type_rows = conn.execute(
                f"""
                SELECT discrepancy_type, COUNT(*) as count
                FROM classification_discrepancies {where}
                GROUP BY discrepancy_type
                """,
                params,
            ).fetchall()
            by_type = {row["discrepancy_type"]: row["count"] for row in by_type_rows}

            # By strictness level
            by_strictness_rows = conn.execute(
                """
                SELECT strictness_level, COUNT(*) as count
                FROM classification_discrepancies
                GROUP BY strictness_level
                """,
            ).fetchall()
            by_strictness = {row["strictness_level"]: row["count"] for row in by_strictness_rows}

            # Upgrade rate (AEGIS stricter than IP)
            upgrades = by_type.get("upgrade", 0)
            upgrade_rate = (upgrades / total * 100) if total > 0 else 0

            # Downgrade rate (AEGIS more lenient than IP)
            downgrades = by_type.get("downgrade", 0)
            downgrade_rate = (downgrades / total * 100) if total > 0 else 0

            return {
                "total_discrepancies": total,
                "by_type": by_type,
                "by_strictness_level": by_strictness,
                "upgrade_rate_pct": round(upgrade_rate, 1),
                "downgrade_rate_pct": round(downgrade_rate, 1),
                "strictness_filter": strictness_level,
            }

    def get_recent_discrepancies(
        self,
        limit: int = 50,
        strictness_level: str | None = None,
        discrepancy_type: str | None = None,
    ) -> list[dict]:
        """Get recent discrepancy records.

        Args:
            limit: Maximum number to return
            strictness_level: Filter to specific strictness level
            discrepancy_type: Filter to specific type (upgrade/downgrade/reclassify)

        Returns:
            List of discrepancy records as dicts
        """
        with self._get_connection() as conn:
            conditions = []
            params = []

            if strictness_level:
                conditions.append("strictness_level = ?")
                params.append(strictness_level)
            if discrepancy_type:
                conditions.append("discrepancy_type = ?")
                params.append(discrepancy_type)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.append(limit)

            rows = conn.execute(
                f"""
                SELECT * FROM classification_discrepancies
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

            return [self._row_to_dict(row) for row in rows]

    def export_discrepancies(
        self,
        output_path: str | Path,
        strictness_level: str | None = None,
    ) -> int:
        """Export discrepancies to JSONL file for analysis.

        Args:
            output_path: Path to output file
            strictness_level: Filter to specific strictness level

        Returns:
            Number of records exported
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            if strictness_level:
                rows = conn.execute(
                    """
                    SELECT * FROM classification_discrepancies
                    WHERE strictness_level = ?
                    ORDER BY created_at
                    """,
                    (strictness_level,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM classification_discrepancies ORDER BY created_at"
                ).fetchall()

            with open(output_path, "w") as f:
                for row in rows:
                    record = self._row_to_dict(row)
                    f.write(json.dumps(record) + "\n")

            logger.info(f"Exported {len(rows)} discrepancies to {output_path}")
            return len(rows)

    def mark_reviewed(
        self,
        candidate_id: str,
        review_notes: str | None = None,
        strictness_level: str | None = None,
    ) -> bool:
        """Mark a discrepancy as reviewed.

        Args:
            candidate_id: The candidate ID
            review_notes: Optional review notes
            strictness_level: The strictness level to mark

        Returns:
            True if record was found and updated
        """
        with self._get_connection() as conn:
            if strictness_level:
                cursor = conn.execute(
                    """
                    UPDATE classification_discrepancies
                    SET reviewed = 1, review_notes = ?
                    WHERE candidate_id = ? AND strictness_level = ?
                    """,
                    (review_notes, candidate_id, strictness_level),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE classification_discrepancies
                    SET reviewed = 1, review_notes = ?
                    WHERE candidate_id = ?
                    """,
                    (review_notes, candidate_id),
                )
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert database row to dictionary."""
        d = dict(row)
        # Parse JSON fields
        if d.get("aegis_reasoning"):
            d["aegis_reasoning"] = json.loads(d["aegis_reasoning"])
        if d.get("nhsn_criteria_applied"):
            d["nhsn_criteria_applied"] = json.loads(d["nhsn_criteria_applied"])
        d["reviewed"] = bool(d.get("reviewed", 0))
        return d


# =============================================================================
# Convenience function for checking discrepancy
# =============================================================================

def check_and_log_discrepancy(
    candidate_id: str,
    aegis_classification: str,
    historic_ip_classification: str | None,
    aegis_reasoning: list[str],
    strictness_level: str,
    aegis_confidence: float | None = None,
    **kwargs,
) -> bool:
    """Check if there's a discrepancy and log it if so.

    This is a convenience function for use in the classification pipeline.

    Args:
        candidate_id: The HAI candidate ID
        aegis_classification: What AEGIS classified
        historic_ip_classification: What IP historically called it (or None)
        aegis_reasoning: AEGIS reasoning chain
        strictness_level: Which strictness level was used
        aegis_confidence: AEGIS confidence score
        **kwargs: Additional fields to pass to log_discrepancy

    Returns:
        True if a discrepancy was logged, False if no discrepancy or no historic
    """
    if not historic_ip_classification:
        return False

    # Normalize for comparison
    aegis_norm = aegis_classification.lower()
    historic_norm = historic_ip_classification.lower()

    # Check if they match (accounting for synonyms)
    aegis_confirmed = aegis_norm in {"clabsi", "hai_confirmed", "confirmed"}
    historic_confirmed = historic_norm in {"clabsi", "hai_confirmed", "confirmed"}

    if aegis_confirmed == historic_confirmed and aegis_norm == historic_norm:
        return False  # No discrepancy

    # Log the discrepancy
    logger = DiscrepancyLogger()
    logger.log_discrepancy(
        candidate_id=candidate_id,
        aegis_classification=aegis_classification,
        historic_ip_classification=historic_ip_classification,
        aegis_reasoning=aegis_reasoning,
        strictness_level=strictness_level,
        aegis_confidence=aegis_confidence,
        **kwargs,
    )
    return True
