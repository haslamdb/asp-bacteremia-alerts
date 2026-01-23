#!/usr/bin/env python3
"""Migrate HAI detection tables from nhsn_* to hai_* prefix.

This script renames the following tables:
- nhsn_candidates -> hai_candidates
- nhsn_classifications -> hai_classifications
- nhsn_reviews -> hai_reviews
- nhsn_llm_audit -> hai_llm_audit

And updates the corresponding views.

Usage:
    python scripts/migrate_hai_tables.py [--db-path /path/to/nhsn.db] [--dry-run]

The script is safe to run multiple times - it will skip tables that have
already been migrated.
"""

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_default_db_path() -> Path:
    """Get the default database path."""
    return Path.home() / ".aegis" / "nhsn.db"


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Check if a table exists in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def view_exists(conn: sqlite3.Connection, view_name: str) -> bool:
    """Check if a view exists in the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name=?",
        (view_name,),
    )
    return cursor.fetchone() is not None


def migrate_table(
    conn: sqlite3.Connection,
    old_name: str,
    new_name: str,
    dry_run: bool = False,
) -> bool:
    """Rename a table from old_name to new_name.

    Returns True if migration was performed, False if skipped.
    """
    if not table_exists(conn, old_name):
        if table_exists(conn, new_name):
            logger.info(f"  Table {new_name} already exists (migration complete)")
            return False
        else:
            logger.warning(f"  Table {old_name} does not exist and {new_name} not found")
            return False

    if table_exists(conn, new_name):
        logger.warning(f"  Both {old_name} and {new_name} exist - manual intervention needed")
        return False

    if dry_run:
        logger.info(f"  [DRY RUN] Would rename {old_name} -> {new_name}")
        return True

    logger.info(f"  Renaming {old_name} -> {new_name}")
    conn.execute(f"ALTER TABLE {old_name} RENAME TO {new_name}")
    return True


def drop_view_if_exists(conn: sqlite3.Connection, view_name: str, dry_run: bool = False) -> None:
    """Drop a view if it exists."""
    if view_exists(conn, view_name):
        if dry_run:
            logger.info(f"  [DRY RUN] Would drop view {view_name}")
        else:
            logger.info(f"  Dropping view {view_name}")
            conn.execute(f"DROP VIEW {view_name}")


def create_hai_views(conn: sqlite3.Connection, dry_run: bool = False) -> None:
    """Create updated views for HAI tables."""
    views = {
        "hai_candidate_stats": """
            CREATE VIEW IF NOT EXISTS hai_candidate_stats AS
            SELECT
                hai_type,
                status,
                COUNT(*) as count,
                DATE(created_at) as date
            FROM hai_candidates
            GROUP BY hai_type, status, DATE(created_at)
        """,
        "hai_pending_reviews": """
            CREATE VIEW IF NOT EXISTS hai_pending_reviews AS
            SELECT
                r.id as review_id,
                r.queue_type,
                r.created_at as queued_at,
                c.id as candidate_id,
                c.hai_type,
                c.patient_mrn,
                c.patient_name,
                c.culture_date,
                c.organism,
                c.device_days_at_culture as device_days,
                cl.decision,
                cl.confidence,
                cl.reasoning
            FROM hai_reviews r
            JOIN hai_candidates c ON r.candidate_id = c.id
            LEFT JOIN hai_classifications cl ON r.classification_id = cl.id
            WHERE r.reviewed = 0
              AND c.status IN ('pending_review', 'classified', 'pending')
            ORDER BY r.created_at ASC
        """,
        "hai_override_stats": """
            CREATE VIEW IF NOT EXISTS hai_override_stats AS
            SELECT
                COUNT(*) as total_reviews,
                SUM(CASE WHEN reviewed = 1 THEN 1 ELSE 0 END) as completed_reviews,
                SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) as total_overrides,
                SUM(CASE WHEN reviewed = 1 AND is_override = 0 THEN 1 ELSE 0 END) as accepted_classifications,
                ROUND(
                    100.0 * SUM(CASE WHEN reviewed = 1 AND is_override = 0 THEN 1 ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN reviewed = 1 THEN 1 ELSE 0 END), 0),
                    1
                ) as acceptance_rate_pct,
                ROUND(
                    100.0 * SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) /
                    NULLIF(SUM(CASE WHEN reviewed = 1 THEN 1 ELSE 0 END), 0),
                    1
                ) as override_rate_pct
            FROM hai_reviews
        """,
        "hai_override_details": """
            CREATE VIEW IF NOT EXISTS hai_override_details AS
            SELECT
                r.id as review_id,
                r.reviewed_at,
                r.reviewer,
                c.patient_mrn,
                c.organism,
                c.hai_type,
                cl.decision as llm_decision,
                cl.confidence as llm_confidence,
                r.reviewer_decision,
                r.is_override,
                r.reviewer_notes,
                r.override_reason
            FROM hai_reviews r
            JOIN hai_candidates c ON r.candidate_id = c.id
            LEFT JOIN hai_classifications cl ON r.classification_id = cl.id
            WHERE r.reviewed = 1
            ORDER BY r.reviewed_at DESC
        """,
        "hai_override_by_decision": """
            CREATE VIEW IF NOT EXISTS hai_override_by_decision AS
            SELECT
                llm_decision,
                COUNT(*) as total_cases,
                SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) as overrides,
                ROUND(
                    100.0 * SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) / COUNT(*),
                    1
                ) as override_rate_pct
            FROM hai_reviews
            WHERE reviewed = 1 AND llm_decision IS NOT NULL
            GROUP BY llm_decision
        """,
    }

    for view_name, view_sql in views.items():
        if dry_run:
            logger.info(f"  [DRY RUN] Would create view {view_name}")
        else:
            logger.info(f"  Creating view {view_name}")
            conn.execute(view_sql)


def run_migration(db_path: Path, dry_run: bool = False) -> int:
    """Run the full migration.

    Returns 0 on success, 1 on error.
    """
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return 1

    logger.info(f"Migrating database: {db_path}")
    if dry_run:
        logger.info("DRY RUN - no changes will be made")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Step 1: Rename tables
        logger.info("Step 1: Renaming tables...")
        table_renames = [
            ("nhsn_candidates", "hai_candidates"),
            ("nhsn_classifications", "hai_classifications"),
            ("nhsn_reviews", "hai_reviews"),
            ("nhsn_llm_audit", "hai_llm_audit"),
        ]

        tables_migrated = 0
        for old_name, new_name in table_renames:
            if migrate_table(conn, old_name, new_name, dry_run):
                tables_migrated += 1

        # Step 2: Drop old views
        logger.info("Step 2: Dropping old views...")
        old_views = [
            "nhsn_candidate_stats",
            "nhsn_pending_reviews",
            "nhsn_override_stats",
            "nhsn_override_details",
            "nhsn_override_by_decision",
        ]

        for view_name in old_views:
            drop_view_if_exists(conn, view_name, dry_run)

        # Step 3: Create new views
        logger.info("Step 3: Creating new views...")
        create_hai_views(conn, dry_run)

        # Commit changes
        if not dry_run:
            conn.commit()
            logger.info(f"Migration complete! {tables_migrated} tables renamed.")
        else:
            logger.info(f"[DRY RUN] Would rename {tables_migrated} tables.")

        return 0

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()
        return 1

    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate HAI detection tables from nhsn_* to hai_* prefix",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Preview migration (no changes)
    python scripts/migrate_hai_tables.py --dry-run

    # Run migration on default database
    python scripts/migrate_hai_tables.py

    # Run migration on specific database
    python scripts/migrate_hai_tables.py --db-path /path/to/nhsn.db
        """,
    )

    parser.add_argument(
        "--db-path",
        type=Path,
        default=get_default_db_path(),
        help=f"Path to the SQLite database (default: {get_default_db_path()})",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying the database",
    )

    args = parser.parse_args()

    return run_migration(args.db_path, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
