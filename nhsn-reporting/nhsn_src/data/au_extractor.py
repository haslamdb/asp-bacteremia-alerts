"""Antibiotic Usage (AU) data extraction for NHSN reporting.

This module calculates Days of Therapy (DOT) and Defined Daily Doses (DDD)
from Clarity MAR (Medication Administration Record) data for NHSN AU reporting.

NHSN AU Reporting Requirements:
- Monthly aggregation by NHSN location
- DOT = distinct calendar days with antimicrobial administration
- DDD = total grams administered / WHO defined daily dose

Reference: CDC NHSN Antimicrobial Use and Resistance Module Protocol
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from ..config import Config

logger = logging.getLogger(__name__)


@dataclass
class AntimicrobialUsage:
    """Summary of antimicrobial usage for a location/month."""

    nhsn_location_code: str
    month: str  # YYYY-MM
    nhsn_code: str  # Antimicrobial NHSN code (e.g., 'VAN')
    nhsn_category: str  # NHSN category (e.g., 'Glycopeptides')
    generic_name: str
    route: str  # 'IV', 'PO', etc.
    days_of_therapy: int  # DOT
    defined_daily_doses: float | None  # DDD (optional)
    patient_days: int  # Denominator
    dot_per_1000_pd: float  # DOT per 1,000 patient days


@dataclass
class PatientLevelUsage:
    """Patient-level antimicrobial usage for audit trail."""

    patient_id: str
    encounter_id: str
    nhsn_location_code: str
    medication_name: str
    nhsn_code: str
    route: str
    first_admin_date: date
    last_admin_date: date
    days_of_therapy: int
    total_dose_grams: float


class AUDataExtractor:
    """Extract antibiotic usage data from Clarity for NHSN reporting.

    This class calculates Days of Therapy (DOT) by counting distinct
    calendar days on which a patient received an antimicrobial agent.
    Data is aggregated by NHSN location and month.

    Example:
        extractor = AUDataExtractor()
        summary = extractor.get_monthly_summary(
            locations=['T5A', 'T5B'],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31)
        )
    """

    def __init__(self, connection_string: str | None = None):
        """Initialize the extractor.

        Args:
            connection_string: Database connection string. If not provided,
                uses Config.get_clarity_connection_string().
        """
        self.connection_string = connection_string or Config.get_clarity_connection_string()
        self._engine = None

    def _get_engine(self):
        """Lazy initialization of SQLAlchemy engine."""
        if self._engine is None:
            if not self.connection_string:
                raise ValueError(
                    "No Clarity connection configured. Set CLARITY_CONNECTION_STRING "
                    "or MOCK_CLARITY_DB_PATH in environment."
                )
            try:
                from sqlalchemy import create_engine

                self._engine = create_engine(self.connection_string)
            except ImportError:
                raise ImportError("sqlalchemy required for AU data extraction")
        return self._engine

    def _is_sqlite(self) -> bool:
        """Check if using SQLite (mock) database."""
        return "sqlite" in (self.connection_string or "").lower()

    def get_antimicrobial_administrations(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        include_oral: bool | None = None,
    ) -> pd.DataFrame:
        """Get raw antimicrobial administration records.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.
            include_oral: Include oral (PO) administrations. Defaults to Config.AU_INCLUDE_ORAL.

        Returns:
            DataFrame with administration details including patient, medication,
            route, dose, and timestamp.
        """
        if start_date is None:
            start_date = date.today().replace(day=1)
        if end_date is None:
            end_date = date.today()
        if include_oral is None:
            include_oral = Config.AU_INCLUDE_ORAL

        # Build location filter
        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        # Build route filter
        route_filter = ""
        if not include_oral:
            route_filter = "AND om.ADMIN_ROUTE NOT IN ('PO', 'ORAL')"

        # SQLite vs SQL Server date expressions
        if self._is_sqlite():
            date_expr = "date(mar.TAKEN_TIME)"
            month_expr = "strftime('%Y-%m', mar.TAKEN_TIME)"
        else:
            date_expr = "CONVERT(DATE, mar.TAKEN_TIME)"
            month_expr = "FORMAT(mar.TAKEN_TIME, 'yyyy-MM')"

        query = f"""
        SELECT
            pat.PAT_MRN_ID as patient_id,
            pe.PAT_ENC_CSN_ID as encounter_id,
            loc.NHSN_LOCATION_CODE,
            rx.GENERIC_NAME as medication_name,
            nm.NHSN_CODE,
            nm.NHSN_CATEGORY,
            nm.DDD as ddd_value,
            nm.DDD_UNIT as ddd_unit,
            om.ADMIN_ROUTE as route,
            mar.TAKEN_TIME as admin_time,
            {date_expr} as admin_date,
            {month_expr} as month,
            mar.DOSE_GIVEN,
            mar.DOSE_UNIT,
            mar.ACTION_NAME
        FROM MAR_ADMIN_INFO mar
        JOIN ORDER_MED om ON mar.ORDER_MED_ID = om.ORDER_MED_ID
        JOIN RX_MED_ONE rx ON om.MEDICATION_ID = rx.MEDICATION_ID
        JOIN NHSN_ANTIMICROBIAL_MAP nm ON rx.MEDICATION_ID = nm.MEDICATION_ID
        JOIN PAT_ENC pe ON om.PAT_ENC_CSN_ID = pe.PAT_ENC_CSN_ID
        JOIN PATIENT pat ON pe.PAT_ID = pat.PAT_ID
        JOIN NHSN_LOCATION_MAP loc ON pe.DEPARTMENT_ID = loc.EPIC_DEPT_ID
        WHERE mar.ACTION_NAME = 'Given'
            AND mar.TAKEN_TIME >= :start_date
            AND mar.TAKEN_TIME <= :end_date
            {location_filter}
            {route_filter}
        ORDER BY pat.PAT_MRN_ID, mar.TAKEN_TIME
        """

        try:
            from sqlalchemy import text

            engine = self._get_engine()
            with engine.connect() as conn:
                df = pd.read_sql(
                    text(query),
                    conn,
                    params={"start_date": start_date, "end_date": end_date},
                )
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"Antimicrobial administration query failed: {e}")
            return pd.DataFrame()

    def calculate_dot(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        include_oral: bool | None = None,
    ) -> pd.DataFrame:
        """Calculate Days of Therapy (DOT) by location, month, and antimicrobial.

        DOT = count of distinct patient-days with at least one administration
        of an antimicrobial agent. Each unique patient-drug-date combination
        counts as 1 DOT.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.
            include_oral: Include oral administrations.

        Returns:
            DataFrame with columns:
            - nhsn_location_code
            - month
            - nhsn_code
            - nhsn_category
            - medication_name
            - route
            - days_of_therapy
        """
        if start_date is None:
            start_date = date.today().replace(day=1)
        if end_date is None:
            end_date = date.today()
        if include_oral is None:
            include_oral = Config.AU_INCLUDE_ORAL

        # Build filters
        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        route_filter = ""
        if not include_oral:
            route_filter = "AND om.ADMIN_ROUTE NOT IN ('PO', 'ORAL')"

        if self._is_sqlite():
            date_expr = "date(mar.TAKEN_TIME)"
            month_expr = "strftime('%Y-%m', mar.TAKEN_TIME)"
        else:
            date_expr = "CONVERT(DATE, mar.TAKEN_TIME)"
            month_expr = "FORMAT(mar.TAKEN_TIME, 'yyyy-MM')"

        # DOT query: count distinct patient-drug-date combinations
        query = f"""
        SELECT
            loc.NHSN_LOCATION_CODE as nhsn_location_code,
            {month_expr} as month,
            nm.NHSN_CODE as nhsn_code,
            nm.NHSN_CATEGORY as nhsn_category,
            rx.GENERIC_NAME as medication_name,
            om.ADMIN_ROUTE as route,
            COUNT(DISTINCT pat.PAT_MRN_ID || '-' || nm.NHSN_CODE || '-' || {date_expr}) as days_of_therapy
        FROM MAR_ADMIN_INFO mar
        JOIN ORDER_MED om ON mar.ORDER_MED_ID = om.ORDER_MED_ID
        JOIN RX_MED_ONE rx ON om.MEDICATION_ID = rx.MEDICATION_ID
        JOIN NHSN_ANTIMICROBIAL_MAP nm ON rx.MEDICATION_ID = nm.MEDICATION_ID
        JOIN PAT_ENC pe ON om.PAT_ENC_CSN_ID = pe.PAT_ENC_CSN_ID
        JOIN PATIENT pat ON pe.PAT_ID = pat.PAT_ID
        JOIN NHSN_LOCATION_MAP loc ON pe.DEPARTMENT_ID = loc.EPIC_DEPT_ID
        WHERE mar.ACTION_NAME = 'Given'
            AND mar.TAKEN_TIME >= :start_date
            AND mar.TAKEN_TIME <= :end_date
            {location_filter}
            {route_filter}
        GROUP BY loc.NHSN_LOCATION_CODE, {month_expr}, nm.NHSN_CODE, nm.NHSN_CATEGORY, rx.GENERIC_NAME, om.ADMIN_ROUTE
        ORDER BY {month_expr}, loc.NHSN_LOCATION_CODE, nm.NHSN_CATEGORY, nm.NHSN_CODE
        """

        try:
            from sqlalchemy import text

            engine = self._get_engine()
            with engine.connect() as conn:
                df = pd.read_sql(
                    text(query),
                    conn,
                    params={"start_date": start_date, "end_date": end_date},
                )
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"DOT calculation query failed: {e}")
            return pd.DataFrame()

    def calculate_ddd(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Calculate Defined Daily Doses (DDD) by location, month, and antimicrobial.

        DDD = total grams administered / WHO defined daily dose for the drug.
        This provides a standardized measure of antimicrobial consumption.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            DataFrame with columns:
            - nhsn_location_code
            - month
            - nhsn_code
            - nhsn_category
            - medication_name
            - total_grams
            - defined_daily_doses
        """
        if start_date is None:
            start_date = date.today().replace(day=1)
        if end_date is None:
            end_date = date.today()

        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        if self._is_sqlite():
            month_expr = "strftime('%Y-%m', mar.TAKEN_TIME)"
        else:
            month_expr = "FORMAT(mar.TAKEN_TIME, 'yyyy-MM')"

        # DDD calculation: sum doses and divide by standard DDD
        query = f"""
        SELECT
            loc.NHSN_LOCATION_CODE as nhsn_location_code,
            {month_expr} as month,
            nm.NHSN_CODE as nhsn_code,
            nm.NHSN_CATEGORY as nhsn_category,
            rx.GENERIC_NAME as medication_name,
            nm.DDD as ddd_standard,
            nm.DDD_UNIT as ddd_unit,
            SUM(CASE
                WHEN mar.DOSE_UNIT IN ('g', 'gram', 'grams') THEN mar.DOSE_GIVEN
                WHEN mar.DOSE_UNIT IN ('mg', 'milligram', 'milligrams') THEN mar.DOSE_GIVEN / 1000.0
                WHEN mar.DOSE_UNIT IN ('mcg', 'microgram', 'micrograms') THEN mar.DOSE_GIVEN / 1000000.0
                ELSE 0
            END) as total_grams,
            CASE
                WHEN nm.DDD > 0 THEN
                    SUM(CASE
                        WHEN mar.DOSE_UNIT IN ('g', 'gram', 'grams') THEN mar.DOSE_GIVEN
                        WHEN mar.DOSE_UNIT IN ('mg', 'milligram', 'milligrams') THEN mar.DOSE_GIVEN / 1000.0
                        WHEN mar.DOSE_UNIT IN ('mcg', 'microgram', 'micrograms') THEN mar.DOSE_GIVEN / 1000000.0
                        ELSE 0
                    END) / nm.DDD
                ELSE NULL
            END as defined_daily_doses
        FROM MAR_ADMIN_INFO mar
        JOIN ORDER_MED om ON mar.ORDER_MED_ID = om.ORDER_MED_ID
        JOIN RX_MED_ONE rx ON om.MEDICATION_ID = rx.MEDICATION_ID
        JOIN NHSN_ANTIMICROBIAL_MAP nm ON rx.MEDICATION_ID = nm.MEDICATION_ID
        JOIN PAT_ENC pe ON om.PAT_ENC_CSN_ID = pe.PAT_ENC_CSN_ID
        JOIN NHSN_LOCATION_MAP loc ON pe.DEPARTMENT_ID = loc.EPIC_DEPT_ID
        WHERE mar.ACTION_NAME = 'Given'
            AND mar.TAKEN_TIME >= :start_date
            AND mar.TAKEN_TIME <= :end_date
            {location_filter}
        GROUP BY loc.NHSN_LOCATION_CODE, {month_expr}, nm.NHSN_CODE, nm.NHSN_CATEGORY, rx.GENERIC_NAME, nm.DDD, nm.DDD_UNIT
        ORDER BY {month_expr}, loc.NHSN_LOCATION_CODE, nm.NHSN_CATEGORY, nm.NHSN_CODE
        """

        try:
            from sqlalchemy import text

            engine = self._get_engine()
            with engine.connect() as conn:
                df = pd.read_sql(
                    text(query),
                    conn,
                    params={"start_date": start_date, "end_date": end_date},
                )
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"DDD calculation query failed: {e}")
            return pd.DataFrame()

    def get_monthly_summary(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        include_oral: bool | None = None,
    ) -> dict[str, Any]:
        """Get comprehensive monthly AU summary for NHSN reporting.

        Combines DOT calculations with patient days to compute rates.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.
            include_oral: Include oral administrations.

        Returns:
            Dictionary with:
            - date_range: Start and end dates
            - locations: List of location summaries with monthly AU data
            - overall_totals: Aggregate totals across all locations
        """
        from .denominator import DenominatorCalculator

        # Get DOT data
        dot_df = self.calculate_dot(locations, start_date, end_date, include_oral)
        ddd_df = self.calculate_ddd(locations, start_date, end_date)

        # Get patient days for rate calculation
        denom_calc = DenominatorCalculator(self.connection_string)
        patient_days_df = denom_calc.get_patient_days(locations, start_date, end_date)

        if dot_df.empty:
            return {
                "date_range": {
                    "start": str(start_date) if start_date else None,
                    "end": str(end_date) if end_date else None,
                },
                "locations": [],
                "overall_totals": {
                    "total_dot": 0,
                    "total_patient_days": 0,
                    "dot_per_1000_pd": 0,
                },
            }

        # Merge DOT with patient days
        merged = pd.merge(
            dot_df,
            patient_days_df[["nhsn_location_code", "month", "patient_days"]],
            on=["nhsn_location_code", "month"],
            how="left",
        )
        merged["patient_days"] = merged["patient_days"].fillna(0).astype(int)

        # Calculate rates
        merged["dot_per_1000_pd"] = merged.apply(
            lambda row: round(row["days_of_therapy"] / row["patient_days"] * 1000, 2)
            if row["patient_days"] > 0
            else 0,
            axis=1,
        )

        # Merge with DDD data if available
        if not ddd_df.empty:
            merged = pd.merge(
                merged,
                ddd_df[["nhsn_location_code", "month", "nhsn_code", "defined_daily_doses"]],
                on=["nhsn_location_code", "month", "nhsn_code"],
                how="left",
            )

        # Build result structure
        result = {
            "date_range": {
                "start": str(start_date) if start_date else None,
                "end": str(end_date) if end_date else None,
            },
            "locations": [],
            "overall_totals": {
                "total_dot": int(merged["days_of_therapy"].sum()),
                "total_patient_days": int(patient_days_df["patient_days"].sum()),
            },
        }

        # Calculate overall rate
        if result["overall_totals"]["total_patient_days"] > 0:
            result["overall_totals"]["dot_per_1000_pd"] = round(
                result["overall_totals"]["total_dot"]
                / result["overall_totals"]["total_patient_days"]
                * 1000,
                2,
            )
        else:
            result["overall_totals"]["dot_per_1000_pd"] = 0

        # Group by location
        for loc_code in sorted(merged["nhsn_location_code"].unique()):
            loc_data = merged[merged["nhsn_location_code"] == loc_code]

            loc_summary = {
                "nhsn_location_code": loc_code,
                "months": [],
                "totals": {
                    "total_dot": int(loc_data["days_of_therapy"].sum()),
                    "patient_days": int(loc_data["patient_days"].sum()),
                },
            }

            # Calculate location rate
            if loc_summary["totals"]["patient_days"] > 0:
                loc_summary["totals"]["dot_per_1000_pd"] = round(
                    loc_summary["totals"]["total_dot"]
                    / loc_summary["totals"]["patient_days"]
                    * 1000,
                    2,
                )
            else:
                loc_summary["totals"]["dot_per_1000_pd"] = 0

            # Group by month within location
            for month in sorted(loc_data["month"].unique()):
                month_data = loc_data[loc_data["month"] == month]
                month_patient_days = int(month_data["patient_days"].iloc[0]) if len(month_data) > 0 else 0

                month_summary = {
                    "month": month,
                    "patient_days": month_patient_days,
                    "total_dot": int(month_data["days_of_therapy"].sum()),
                    "antimicrobials": [],
                }

                # Calculate month rate
                if month_patient_days > 0:
                    month_summary["dot_per_1000_pd"] = round(
                        month_summary["total_dot"] / month_patient_days * 1000, 2
                    )
                else:
                    month_summary["dot_per_1000_pd"] = 0

                # Add antimicrobial details
                for _, row in month_data.iterrows():
                    antimicrobial = {
                        "nhsn_code": row["nhsn_code"],
                        "nhsn_category": row["nhsn_category"],
                        "medication_name": row["medication_name"],
                        "route": row["route"],
                        "days_of_therapy": int(row["days_of_therapy"]),
                        "dot_per_1000_pd": row["dot_per_1000_pd"],
                    }
                    if "defined_daily_doses" in row and pd.notna(row["defined_daily_doses"]):
                        antimicrobial["defined_daily_doses"] = round(row["defined_daily_doses"], 2)
                    month_summary["antimicrobials"].append(antimicrobial)

                loc_summary["months"].append(month_summary)

            result["locations"].append(loc_summary)

        return result

    def get_usage_by_category(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Get antimicrobial usage aggregated by NHSN category.

        Useful for high-level reporting and trending by antimicrobial class.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            DataFrame with DOT totals by NHSN category.
        """
        dot_df = self.calculate_dot(locations, start_date, end_date)

        if dot_df.empty:
            return pd.DataFrame(
                columns=["nhsn_location_code", "month", "nhsn_category", "total_dot"]
            )

        # Aggregate by category
        category_df = (
            dot_df.groupby(["nhsn_location_code", "month", "nhsn_category"])
            .agg({"days_of_therapy": "sum"})
            .reset_index()
        )
        category_df = category_df.rename(columns={"days_of_therapy": "total_dot"})

        return category_df

    def export_for_nhsn(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Export AU data in NHSN submission format.

        Prepares data according to NHSN AU module CSV format requirements.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            DataFrame formatted for NHSN submission.
        """
        from .denominator import DenominatorCalculator

        dot_df = self.calculate_dot(locations, start_date, end_date)
        denom_calc = DenominatorCalculator(self.connection_string)
        patient_days_df = denom_calc.get_patient_days(locations, start_date, end_date)

        if dot_df.empty:
            return pd.DataFrame()

        # Merge with patient days
        merged = pd.merge(
            dot_df,
            patient_days_df[["nhsn_location_code", "month", "patient_days"]],
            on=["nhsn_location_code", "month"],
            how="left",
        )

        # Format for NHSN
        nhsn_df = pd.DataFrame(
            {
                "orgID": Config.NHSN_FACILITY_ID or "",
                "locationCode": merged["nhsn_location_code"],
                "summaryYM": merged["month"].str.replace("-", ""),  # YYYYMM format
                "antimicrobialCode": merged["nhsn_code"],
                "antimicrobialCategory": merged["nhsn_category"],
                "route": merged["route"],
                "daysOfTherapy": merged["days_of_therapy"],
                "patientDays": merged["patient_days"].fillna(0).astype(int),
            }
        )

        return nhsn_df
