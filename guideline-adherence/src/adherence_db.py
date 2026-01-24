"""Database for tracking guideline adherence assessments."""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from .config import config
from .models import (
    ElementCheckResult,
    ElementCheckStatus,
    EpisodeStatus,
    GuidelineMonitorResult,
)

logger = logging.getLogger(__name__)

SCHEMA = """
-- Episodes being monitored for guideline adherence
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_mrn TEXT,
    patient_name TEXT,
    encounter_id TEXT,
    location TEXT,
    bundle_id TEXT NOT NULL,
    bundle_name TEXT,
    trigger_time TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(patient_id, encounter_id, bundle_id)
);

-- Individual element assessments within episodes
CREATE TABLE IF NOT EXISTS element_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    element_id TEXT NOT NULL,
    element_name TEXT,
    status TEXT NOT NULL,
    time_window_hours REAL,
    deadline TEXT,
    completed_at TEXT,
    value TEXT,
    notes TEXT,
    assessed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (episode_id) REFERENCES episodes(id),
    UNIQUE(episode_id, element_id, assessed_at)
);

-- Alerts generated for deviations
CREATE TABLE IF NOT EXISTS deviation_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    element_id TEXT NOT NULL,
    alert_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (episode_id) REFERENCES episodes(id),
    UNIQUE(episode_id, element_id)
);

-- Indices for common queries
CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);
CREATE INDEX IF NOT EXISTS idx_episodes_bundle ON episodes(bundle_id);
CREATE INDEX IF NOT EXISTS idx_episodes_patient ON episodes(patient_id);
CREATE INDEX IF NOT EXISTS idx_element_results_episode ON element_results(episode_id);
CREATE INDEX IF NOT EXISTS idx_element_results_status ON element_results(status);
CREATE INDEX IF NOT EXISTS idx_deviation_alerts_episode ON deviation_alerts(episode_id);
"""


class AdherenceDatabase:
    """SQLite database for guideline adherence tracking."""

    def __init__(self, db_path: str | None = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path or config.ADHERENCE_DB_PATH

        # Ensure directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection with context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Episode management
    # -------------------------------------------------------------------------

    def create_or_update_episode(self, result: GuidelineMonitorResult) -> str:
        """Create or update an episode record.

        Args:
            result: The monitoring result.

        Returns:
            Episode ID.
        """
        episode_id = f"{result.patient_id}_{result.encounter_id}_{result.bundle_id}"

        with self._get_connection() as conn:
            # Check if exists
            cursor = conn.execute(
                "SELECT id FROM episodes WHERE id = ?",
                (episode_id,)
            )
            existing = cursor.fetchone()

            if existing:
                # Update
                conn.execute(
                    """
                    UPDATE episodes SET
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        result.episode_status.value,
                        datetime.now().isoformat(),
                        episode_id,
                    )
                )
            else:
                # Insert
                conn.execute(
                    """
                    INSERT INTO episodes (
                        id, patient_id, patient_mrn, patient_name,
                        encounter_id, location, bundle_id, bundle_name,
                        trigger_time, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        episode_id,
                        result.patient_id,
                        result.patient_mrn,
                        result.patient_name,
                        result.encounter_id,
                        result.location,
                        result.bundle_id,
                        result.bundle_name,
                        result.trigger_time.isoformat() if result.trigger_time else None,
                        result.episode_status.value,
                    )
                )

            conn.commit()

        return episode_id

    def save_element_results(
        self,
        episode_id: str,
        results: list[ElementCheckResult],
    ) -> None:
        """Save element check results for an episode.

        Args:
            episode_id: The episode ID.
            results: List of element check results.
        """
        with self._get_connection() as conn:
            for result in results:
                conn.execute(
                    """
                    INSERT INTO element_results (
                        episode_id, element_id, element_name, status,
                        time_window_hours, deadline, completed_at, value, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        episode_id,
                        result.element_id,
                        result.element_name,
                        result.status.value,
                        result.time_window_hours,
                        result.deadline.isoformat() if result.deadline else None,
                        result.completed_at.isoformat() if result.completed_at else None,
                        json.dumps(result.value) if result.value is not None else None,
                        result.notes,
                    )
                )
            conn.commit()

    def record_deviation_alert(
        self,
        episode_id: str,
        element_id: str,
        alert_id: str,
    ) -> None:
        """Record that an alert was created for a deviation.

        Args:
            episode_id: The episode ID.
            element_id: The element that deviated.
            alert_id: The alert store ID.
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO deviation_alerts (
                    episode_id, element_id, alert_id
                ) VALUES (?, ?, ?)
                """,
                (episode_id, element_id, alert_id)
            )
            conn.commit()

    def has_deviation_alert(self, episode_id: str, element_id: str) -> bool:
        """Check if a deviation alert already exists.

        Args:
            episode_id: The episode ID.
            element_id: The element ID.

        Returns:
            True if alert already exists.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM deviation_alerts WHERE episode_id = ? AND element_id = ?",
                (episode_id, element_id)
            )
            return cursor.fetchone() is not None

    # -------------------------------------------------------------------------
    # Query methods
    # -------------------------------------------------------------------------

    def get_active_episodes(self, bundle_id: str | None = None) -> list[dict]:
        """Get all active episodes.

        Args:
            bundle_id: Optional filter by bundle.

        Returns:
            List of episode dicts.
        """
        with self._get_connection() as conn:
            if bundle_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM episodes
                    WHERE status = 'active' AND bundle_id = ?
                    ORDER BY trigger_time DESC
                    """,
                    (bundle_id,)
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM episodes
                    WHERE status = 'active'
                    ORDER BY trigger_time DESC
                    """
                )

            return [dict(row) for row in cursor.fetchall()]

    def get_episode(self, episode_id: str) -> dict | None:
        """Get episode by ID.

        Args:
            episode_id: The episode ID.

        Returns:
            Episode dict or None.
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM episodes WHERE id = ?",
                (episode_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_episode_results(self, episode_id: str) -> list[dict]:
        """Get latest element results for an episode.

        Args:
            episode_id: The episode ID.

        Returns:
            List of result dicts.
        """
        with self._get_connection() as conn:
            # Get latest result for each element
            cursor = conn.execute(
                """
                SELECT er.* FROM element_results er
                INNER JOIN (
                    SELECT element_id, MAX(assessed_at) as max_assessed
                    FROM element_results
                    WHERE episode_id = ?
                    GROUP BY element_id
                ) latest ON er.element_id = latest.element_id
                    AND er.assessed_at = latest.max_assessed
                WHERE er.episode_id = ?
                ORDER BY er.element_id
                """,
                (episode_id, episode_id)
            )

            return [dict(row) for row in cursor.fetchall()]

    def get_compliance_metrics(
        self,
        bundle_id: str | None = None,
        days: int = 30,
    ) -> dict:
        """Get aggregate compliance metrics.

        Args:
            bundle_id: Optional filter by bundle.
            days: Number of days to include.

        Returns:
            Dict with compliance statistics.
        """
        with self._get_connection() as conn:
            # Get episode counts by status
            if bundle_id:
                cursor = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                        SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) as complete
                    FROM episodes
                    WHERE bundle_id = ?
                        AND created_at >= datetime('now', ?)
                    """,
                    (bundle_id, f"-{days} days")
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                        SUM(CASE WHEN status = 'complete' THEN 1 ELSE 0 END) as complete
                    FROM episodes
                    WHERE created_at >= datetime('now', ?)
                    """,
                    (f"-{days} days",)
                )

            episode_counts = dict(cursor.fetchone())

            # Get element compliance rates
            if bundle_id:
                cursor = conn.execute(
                    """
                    SELECT
                        er.element_id,
                        er.element_name,
                        COUNT(*) as total_assessed,
                        SUM(CASE WHEN er.status = 'met' THEN 1 ELSE 0 END) as met,
                        SUM(CASE WHEN er.status = 'not_met' THEN 1 ELSE 0 END) as not_met
                    FROM element_results er
                    INNER JOIN episodes e ON er.episode_id = e.id
                    WHERE e.bundle_id = ?
                        AND e.created_at >= datetime('now', ?)
                    GROUP BY er.element_id, er.element_name
                    """,
                    (bundle_id, f"-{days} days")
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT
                        er.element_id,
                        er.element_name,
                        COUNT(*) as total_assessed,
                        SUM(CASE WHEN er.status = 'met' THEN 1 ELSE 0 END) as met,
                        SUM(CASE WHEN er.status = 'not_met' THEN 1 ELSE 0 END) as not_met
                    FROM element_results er
                    INNER JOIN episodes e ON er.episode_id = e.id
                    WHERE e.created_at >= datetime('now', ?)
                    GROUP BY er.element_id, er.element_name
                    """,
                    (f"-{days} days",)
                )

            element_rates = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                total = row_dict["met"] + row_dict["not_met"]
                rate = (row_dict["met"] / total * 100) if total > 0 else 0
                element_rates.append({
                    "element_id": row_dict["element_id"],
                    "element_name": row_dict["element_name"],
                    "compliance_rate": round(rate, 1),
                    "total_assessed": total,
                })

            return {
                "episode_counts": episode_counts,
                "element_rates": element_rates,
                "days": days,
                "bundle_id": bundle_id,
            }

    def close_episode(self, episode_id: str, status: EpisodeStatus = EpisodeStatus.COMPLETE) -> None:
        """Close an episode (patient discharged or bundle complete).

        Args:
            episode_id: The episode ID.
            status: Final status.
        """
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE episodes SET
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status.value, datetime.now().isoformat(), episode_id)
            )
            conn.commit()
