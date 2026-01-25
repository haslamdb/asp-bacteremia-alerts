"""Denominator data aggregation for NHSN reporting.

This module calculates device-days and patient-days from Clarity data
for NHSN monthly summary reporting. These denominators are required
for calculating HAI rates (infections per 1,000 device-days).
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import Config

logger = logging.getLogger(__name__)


class DenominatorCalculator:
    """Calculate device-days and patient-days from Clarity data.

    This class provides methods to aggregate denominator data from Clarity
    (or mock Clarity SQLite) for NHSN monthly summary reporting.

    Denominators needed for CLABSI reporting:
    - Central line days: Count of patient-days with a central line present
    - Patient days: Total patient census days per location

    Example:
        calc = DenominatorCalculator()
        df = calc.get_central_line_days(
            locations=['T5A', 'T5B'],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31)
        )
    """

    def __init__(self, connection_string: str | None = None):
        """Initialize the calculator.

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
                raise ImportError("sqlalchemy required for denominator calculations")
        return self._engine

    def _is_sqlite(self) -> bool:
        """Check if using SQLite (mock) database."""
        return "sqlite" in (self.connection_string or "").lower()

    def get_central_line_days(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Calculate central line days by location and month.

        Central line days = count of distinct patient-days with a central
        line documented as present. This is the denominator for CLABSI rate.

        Args:
            locations: List of NHSN location codes (e.g., ['T5A', 'T5B']).
                      If None, includes all locations.
            start_date: Start of date range (inclusive). Defaults to 1 year ago.
            end_date: End of date range (inclusive). Defaults to today.

        Returns:
            DataFrame with columns:
            - nhsn_location_code: NHSN location identifier
            - month: Year-month string (YYYY-MM)
            - central_line_days: Count of patient-days with line present
        """
        if start_date is None:
            start_date = date.today().replace(year=date.today().year - 1)
        if end_date is None:
            end_date = date.today()

        # SQLite uses strftime, SQL Server uses FORMAT/CONVERT
        if self._is_sqlite():
            month_expr = "strftime('%Y-%m', fm.RECORDED_TIME)"
            date_expr = "date(fm.RECORDED_TIME)"
        else:
            month_expr = "FORMAT(fm.RECORDED_TIME, 'yyyy-MM')"
            date_expr = "CONVERT(DATE, fm.RECORDED_TIME)"

        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        query = f"""
        SELECT
            loc.NHSN_LOCATION_CODE,
            {month_expr} AS month,
            COUNT(DISTINCT pe.PAT_ID || '-' || {date_expr}) AS central_line_days
        FROM IP_FLWSHT_MEAS fm
        JOIN IP_FLWSHT_REC rec ON fm.FSD_ID = rec.FSD_ID
        JOIN PAT_ENC pe ON rec.INPATIENT_DATA_ID = pe.INPATIENT_DATA_ID
        JOIN NHSN_LOCATION_MAP loc ON pe.DEPARTMENT_ID = loc.EPIC_DEPT_ID
        JOIN IP_FLO_GP_DATA fd ON fm.FLO_MEAS_ID = fd.FLO_MEAS_ID
        WHERE (fd.DISP_NAME LIKE '%central%line%' OR fd.DISP_NAME LIKE '%PICC%')
            AND fm.MEAS_VALUE NOT LIKE '%removed%'
            AND fm.RECORDED_TIME >= :start_date
            AND fm.RECORDED_TIME <= :end_date
            {location_filter}
        GROUP BY loc.NHSN_LOCATION_CODE, {month_expr}
        ORDER BY {month_expr}, loc.NHSN_LOCATION_CODE
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
                # Normalize column names to lowercase
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"Central line days query failed: {e}")
            return pd.DataFrame(columns=["nhsn_location_code", "month", "central_line_days"])

    def get_urinary_catheter_days(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Calculate urinary catheter days by location and month.

        Urinary catheter days = count of distinct patient-days with an
        indwelling urinary catheter documented as present. This is the
        denominator for CAUTI rate calculation.

        Args:
            locations: List of NHSN location codes (e.g., ['T5A', 'T5B']).
                      If None, includes all locations.
            start_date: Start of date range (inclusive). Defaults to 1 year ago.
            end_date: End of date range (inclusive). Defaults to today.

        Returns:
            DataFrame with columns:
            - nhsn_location_code: NHSN location identifier
            - month: Year-month string (YYYY-MM)
            - urinary_catheter_days: Count of patient-days with catheter present
        """
        if start_date is None:
            start_date = date.today().replace(year=date.today().year - 1)
        if end_date is None:
            end_date = date.today()

        # SQLite uses strftime, SQL Server uses FORMAT/CONVERT
        if self._is_sqlite():
            month_expr = "strftime('%Y-%m', fm.RECORDED_TIME)"
            date_expr = "date(fm.RECORDED_TIME)"
        else:
            month_expr = "FORMAT(fm.RECORDED_TIME, 'yyyy-MM')"
            date_expr = "CONVERT(DATE, fm.RECORDED_TIME)"

        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        query = f"""
        SELECT
            loc.NHSN_LOCATION_CODE,
            {month_expr} AS month,
            COUNT(DISTINCT pe.PAT_ID || '-' || {date_expr}) AS urinary_catheter_days
        FROM IP_FLWSHT_MEAS fm
        JOIN IP_FLWSHT_REC rec ON fm.FSD_ID = rec.FSD_ID
        JOIN PAT_ENC pe ON rec.INPATIENT_DATA_ID = pe.INPATIENT_DATA_ID
        JOIN NHSN_LOCATION_MAP loc ON pe.DEPARTMENT_ID = loc.EPIC_DEPT_ID
        JOIN IP_FLO_GP_DATA fd ON fm.FLO_MEAS_ID = fd.FLO_MEAS_ID
        WHERE (fd.DISP_NAME LIKE '%foley%'
               OR fd.DISP_NAME LIKE '%urinary%catheter%'
               OR fd.DISP_NAME LIKE '%indwelling%catheter%')
            AND fm.MEAS_VALUE NOT LIKE '%removed%'
            AND fm.MEAS_VALUE NOT LIKE '%discontinued%'
            AND fm.RECORDED_TIME >= :start_date
            AND fm.RECORDED_TIME <= :end_date
            {location_filter}
        GROUP BY loc.NHSN_LOCATION_CODE, {month_expr}
        ORDER BY {month_expr}, loc.NHSN_LOCATION_CODE
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
                # Normalize column names to lowercase
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"Urinary catheter days query failed: {e}")
            return pd.DataFrame(columns=["nhsn_location_code", "month", "urinary_catheter_days"])

    def get_ventilator_days(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Calculate ventilator days by location and month.

        Ventilator days = count of distinct patient-days with mechanical
        ventilation documented. This is the denominator for VAE/VAP rate
        calculation.

        Args:
            locations: List of NHSN location codes (e.g., ['T5A', 'T5B']).
                      If None, includes all locations.
            start_date: Start of date range (inclusive). Defaults to 1 year ago.
            end_date: End of date range (inclusive). Defaults to today.

        Returns:
            DataFrame with columns:
            - nhsn_location_code: NHSN location identifier
            - month: Year-month string (YYYY-MM)
            - ventilator_days: Count of patient-days on mechanical ventilation
        """
        if start_date is None:
            start_date = date.today().replace(year=date.today().year - 1)
        if end_date is None:
            end_date = date.today()

        # SQLite uses strftime, SQL Server uses FORMAT/CONVERT
        if self._is_sqlite():
            month_expr = "strftime('%Y-%m', fm.RECORDED_TIME)"
            date_expr = "date(fm.RECORDED_TIME)"
        else:
            month_expr = "FORMAT(fm.RECORDED_TIME, 'yyyy-MM')"
            date_expr = "CONVERT(DATE, fm.RECORDED_TIME)"

        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        query = f"""
        SELECT
            loc.NHSN_LOCATION_CODE,
            {month_expr} AS month,
            COUNT(DISTINCT pe.PAT_ID || '-' || {date_expr}) AS ventilator_days
        FROM IP_FLWSHT_MEAS fm
        JOIN IP_FLWSHT_REC rec ON fm.FSD_ID = rec.FSD_ID
        JOIN PAT_ENC pe ON rec.INPATIENT_DATA_ID = pe.INPATIENT_DATA_ID
        JOIN NHSN_LOCATION_MAP loc ON pe.DEPARTMENT_ID = loc.EPIC_DEPT_ID
        JOIN IP_FLO_GP_DATA fd ON fm.FLO_MEAS_ID = fd.FLO_MEAS_ID
        WHERE (fd.DISP_NAME LIKE '%ventilator%'
               OR fd.DISP_NAME LIKE '%mechanical%vent%'
               OR fd.DISP_NAME LIKE '%vent%mode%'
               OR fd.DISP_NAME LIKE '%intubat%')
            AND fm.MEAS_VALUE NOT LIKE '%removed%'
            AND fm.MEAS_VALUE NOT LIKE '%extubat%'
            AND fm.MEAS_VALUE NOT LIKE '%discontinued%'
            AND fm.RECORDED_TIME >= :start_date
            AND fm.RECORDED_TIME <= :end_date
            {location_filter}
        GROUP BY loc.NHSN_LOCATION_CODE, {month_expr}
        ORDER BY {month_expr}, loc.NHSN_LOCATION_CODE
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
                # Normalize column names to lowercase
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"Ventilator days query failed: {e}")
            return pd.DataFrame(columns=["nhsn_location_code", "month", "ventilator_days"])

    def get_patient_days(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> pd.DataFrame:
        """Calculate patient days by location and month.

        Patient days = sum of days patients were admitted to each unit.
        Each day is attributed to its correct calendar month (not admission month).
        This provides context for HAI rates (device utilization ratio).

        Args:
            locations: List of NHSN location codes. If None, includes all.
            start_date: Start of date range. Defaults to 1 year ago.
            end_date: End of date range. Defaults to today.

        Returns:
            DataFrame with columns:
            - nhsn_location_code: NHSN location identifier
            - month: Year-month string (YYYY-MM)
            - patient_days: Sum of patient census days
        """
        if start_date is None:
            start_date = date.today().replace(year=date.today().year - 1)
        if end_date is None:
            end_date = date.today()

        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        if self._is_sqlite():
            # Use recursive CTE to expand each stay into individual days,
            # then attribute each day to its correct calendar month
            query = f"""
            WITH RECURSIVE stay_days AS (
                -- Base case: first day of each stay (clipped to start_date)
                SELECT
                    pe.PAT_ENC_CSN_ID,
                    pe.DEPARTMENT_ID,
                    MAX(date(pe.HOSP_ADMIT_DTTM), date(:start_date)) AS census_date,
                    MIN(date(COALESCE(pe.HOSP_DISCH_DTTM, :end_date)), date(:end_date)) AS end_dt
                FROM PAT_ENC pe
                WHERE pe.HOSP_ADMIT_DTTM <= :end_date
                    AND (pe.HOSP_DISCH_DTTM IS NULL OR pe.HOSP_DISCH_DTTM >= :start_date)

                UNION ALL

                -- Recursive case: add one day until we reach discharge/end
                SELECT
                    PAT_ENC_CSN_ID,
                    DEPARTMENT_ID,
                    date(census_date, '+1 day'),
                    end_dt
                FROM stay_days
                WHERE census_date < end_dt
            )
            SELECT
                loc.NHSN_LOCATION_CODE,
                strftime('%Y-%m', sd.census_date) AS month,
                COUNT(*) AS patient_days
            FROM stay_days sd
            JOIN NHSN_LOCATION_MAP loc ON sd.DEPARTMENT_ID = loc.EPIC_DEPT_ID
            WHERE 1=1 {location_filter}
            GROUP BY loc.NHSN_LOCATION_CODE, strftime('%Y-%m', sd.census_date)
            ORDER BY month, loc.NHSN_LOCATION_CODE
            """
        else:
            # SQL Server: use recursive CTE with DATEADD
            query = f"""
            WITH stay_days AS (
                -- Base case: first day of each stay (clipped to start_date)
                SELECT
                    pe.PAT_ENC_CSN_ID,
                    pe.DEPARTMENT_ID,
                    CAST(CASE WHEN pe.HOSP_ADMIT_DTTM > :start_date
                         THEN pe.HOSP_ADMIT_DTTM ELSE :start_date END AS DATE) AS census_date,
                    CAST(CASE WHEN pe.HOSP_DISCH_DTTM IS NULL OR pe.HOSP_DISCH_DTTM > :end_date
                         THEN :end_date ELSE pe.HOSP_DISCH_DTTM END AS DATE) AS end_dt
                FROM PAT_ENC pe
                WHERE pe.HOSP_ADMIT_DTTM <= :end_date
                    AND (pe.HOSP_DISCH_DTTM IS NULL OR pe.HOSP_DISCH_DTTM >= :start_date)

                UNION ALL

                -- Recursive case: add one day until we reach discharge/end
                SELECT
                    PAT_ENC_CSN_ID,
                    DEPARTMENT_ID,
                    DATEADD(DAY, 1, census_date),
                    end_dt
                FROM stay_days
                WHERE census_date < end_dt
            )
            SELECT
                loc.NHSN_LOCATION_CODE,
                FORMAT(sd.census_date, 'yyyy-MM') AS month,
                COUNT(*) AS patient_days
            FROM stay_days sd
            JOIN NHSN_LOCATION_MAP loc ON sd.DEPARTMENT_ID = loc.EPIC_DEPT_ID
            WHERE 1=1 {location_filter}
            GROUP BY loc.NHSN_LOCATION_CODE, FORMAT(sd.census_date, 'yyyy-MM')
            ORDER BY month, loc.NHSN_LOCATION_CODE
            OPTION (MAXRECURSION 366)
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
                # Normalize column names to lowercase
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"Patient days query failed: {e}")
            return pd.DataFrame(columns=["nhsn_location_code", "month", "patient_days"])

    def get_denominator_summary(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        """Get combined denominator summary for NHSN submission.

        Returns a structured summary combining all device-days and patient
        days, suitable for NHSN monthly summary data entry.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            Dictionary with:
            - date_range: Dict with start and end dates
            - locations: List of location summaries, each containing:
                - nhsn_location_code
                - months: List of monthly data with device-days and patient_days
                - totals: Aggregate totals for the period
        """
        # Fetch all denominator data
        line_days_df = self.get_central_line_days(locations, start_date, end_date)
        catheter_days_df = self.get_urinary_catheter_days(locations, start_date, end_date)
        vent_days_df = self.get_ventilator_days(locations, start_date, end_date)
        patient_days_df = self.get_patient_days(locations, start_date, end_date)

        # Check if all empty
        all_empty = (
            line_days_df.empty
            and catheter_days_df.empty
            and vent_days_df.empty
            and patient_days_df.empty
        )
        if all_empty:
            return {
                "date_range": {
                    "start": str(start_date) if start_date else None,
                    "end": str(end_date) if end_date else None,
                },
                "locations": [],
            }

        # Start with patient days as base, merge all device days
        merged = patient_days_df[["nhsn_location_code", "month", "patient_days"]].copy()

        if not line_days_df.empty:
            merged = pd.merge(
                merged,
                line_days_df[["nhsn_location_code", "month", "central_line_days"]],
                on=["nhsn_location_code", "month"],
                how="outer",
            )

        if not catheter_days_df.empty:
            merged = pd.merge(
                merged,
                catheter_days_df[["nhsn_location_code", "month", "urinary_catheter_days"]],
                on=["nhsn_location_code", "month"],
                how="outer",
            )

        if not vent_days_df.empty:
            merged = pd.merge(
                merged,
                vent_days_df[["nhsn_location_code", "month", "ventilator_days"]],
                on=["nhsn_location_code", "month"],
                how="outer",
            )

        # Fill NaN with 0 for all numeric columns
        merged = merged.fillna(0)

        # Ensure all expected columns exist
        for col in ["central_line_days", "urinary_catheter_days", "ventilator_days", "patient_days"]:
            if col not in merged.columns:
                merged[col] = 0

        # Build summary structure
        result = {
            "date_range": {
                "start": str(start_date) if start_date else None,
                "end": str(end_date) if end_date else None,
            },
            "locations": [],
        }

        location_codes = merged["nhsn_location_code"].unique()
        for loc_code in sorted(location_codes):
            loc_data = merged[merged["nhsn_location_code"] == loc_code]

            months = []
            for _, row in loc_data.iterrows():
                patient_days = int(row["patient_days"])
                central_line_days = int(row["central_line_days"])
                urinary_catheter_days = int(row["urinary_catheter_days"])
                ventilator_days = int(row["ventilator_days"])

                months.append({
                    "month": row["month"],
                    "patient_days": patient_days,
                    "central_line_days": central_line_days,
                    "urinary_catheter_days": urinary_catheter_days,
                    "ventilator_days": ventilator_days,
                    "central_line_utilization": (
                        round(central_line_days / patient_days, 3)
                        if patient_days > 0 else 0
                    ),
                    "urinary_catheter_utilization": (
                        round(urinary_catheter_days / patient_days, 3)
                        if patient_days > 0 else 0
                    ),
                    "ventilator_utilization": (
                        round(ventilator_days / patient_days, 3)
                        if patient_days > 0 else 0
                    ),
                })

            # Calculate totals
            total_patient_days = int(loc_data["patient_days"].sum())
            total_line_days = int(loc_data["central_line_days"].sum())
            total_catheter_days = int(loc_data["urinary_catheter_days"].sum())
            total_vent_days = int(loc_data["ventilator_days"].sum())

            totals = {
                "patient_days": total_patient_days,
                "central_line_days": total_line_days,
                "urinary_catheter_days": total_catheter_days,
                "ventilator_days": total_vent_days,
            }

            if total_patient_days > 0:
                totals["central_line_utilization"] = round(
                    total_line_days / total_patient_days, 3
                )
                totals["urinary_catheter_utilization"] = round(
                    total_catheter_days / total_patient_days, 3
                )
                totals["ventilator_utilization"] = round(
                    total_vent_days / total_patient_days, 3
                )
            else:
                totals["central_line_utilization"] = 0
                totals["urinary_catheter_utilization"] = 0
                totals["ventilator_utilization"] = 0

            result["locations"].append({
                "nhsn_location_code": loc_code,
                "months": months,
                "totals": totals,
            })

        return result

    def get_clabsi_rate(
        self,
        clabsi_count: int,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, float]:
        """Calculate CLABSI rate per 1,000 central line days.

        This is the standard NHSN metric for comparing CLABSI performance.

        Args:
            clabsi_count: Number of confirmed CLABSIs in the period.
            locations: NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            Dictionary with:
            - clabsi_count: Input CLABSI count
            - central_line_days: Total line days
            - rate_per_1000: CLABSIs per 1,000 line days
        """
        line_days_df = self.get_central_line_days(locations, start_date, end_date)
        total_line_days = int(line_days_df["central_line_days"].sum())

        rate = (clabsi_count / total_line_days * 1000) if total_line_days > 0 else 0

        return {
            "clabsi_count": clabsi_count,
            "central_line_days": total_line_days,
            "rate_per_1000": round(rate, 2),
        }

    def get_cauti_rate(
        self,
        cauti_count: int,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, float]:
        """Calculate CAUTI rate per 1,000 urinary catheter days.

        This is the standard NHSN metric for comparing CAUTI performance.

        Args:
            cauti_count: Number of confirmed CAUTIs in the period.
            locations: NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            Dictionary with:
            - cauti_count: Input CAUTI count
            - urinary_catheter_days: Total catheter days
            - rate_per_1000: CAUTIs per 1,000 catheter days
        """
        catheter_days_df = self.get_urinary_catheter_days(locations, start_date, end_date)
        total_catheter_days = int(catheter_days_df["urinary_catheter_days"].sum())

        rate = (cauti_count / total_catheter_days * 1000) if total_catheter_days > 0 else 0

        return {
            "cauti_count": cauti_count,
            "urinary_catheter_days": total_catheter_days,
            "rate_per_1000": round(rate, 2),
        }

    def get_vae_rate(
        self,
        vae_count: int,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, float]:
        """Calculate VAE rate per 1,000 ventilator days.

        This is the standard NHSN metric for comparing VAE/VAP performance.

        Args:
            vae_count: Number of confirmed VAEs in the period.
            locations: NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.

        Returns:
            Dictionary with:
            - vae_count: Input VAE count
            - ventilator_days: Total ventilator days
            - rate_per_1000: VAEs per 1,000 ventilator days
        """
        vent_days_df = self.get_ventilator_days(locations, start_date, end_date)
        total_vent_days = int(vent_days_df["ventilator_days"].sum())

        rate = (vae_count / total_vent_days * 1000) if total_vent_days > 0 else 0

        return {
            "vae_count": vae_count,
            "ventilator_days": total_vent_days,
            "rate_per_1000": round(rate, 2),
        }
