"""Antimicrobial Resistance (AR) data extraction for NHSN reporting.

This module extracts culture and susceptibility data from Clarity for NHSN AR
reporting. It implements first-isolate deduplication and phenotype calculations.

NHSN AR Reporting Requirements:
- Quarterly aggregation by NHSN location
- First isolate per patient per organism per quarter (deduplication)
- Phenotype calculations (MRSA, VRE, ESBL, CRE, etc.)
- Specimen type filtering (blood, urine, respiratory, CSF)

Reference: CDC NHSN Antimicrobial Use and Resistance Module Protocol
"""

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from ..config import Config

logger = logging.getLogger(__name__)


@dataclass
class Isolate:
    """Individual isolate record."""

    isolate_id: str
    patient_id: str
    encounter_id: str | None
    nhsn_location_code: str
    specimen_date: date
    specimen_type: str
    organism_name: str
    organism_group: str | None
    is_first_isolate: bool


@dataclass
class SusceptibilityResult:
    """Susceptibility test result for an isolate."""

    isolate_id: str
    antibiotic: str
    antibiotic_code: str | None
    mic: float | None
    interpretation: str  # 'S', 'I', 'R'


@dataclass
class ResistanceSummary:
    """Summary of resistance rates for a location/quarter."""

    nhsn_location_code: str
    quarter: str  # YYYY-Q#
    organism_name: str
    antibiotic: str
    total_isolates: int
    resistant_isolates: int
    intermediate_isolates: int
    susceptible_isolates: int
    percent_resistant: float
    percent_non_susceptible: float  # R + I


@dataclass
class PhenotypeSummary:
    """Summary of resistance phenotype prevalence."""

    nhsn_location_code: str
    quarter: str
    phenotype_code: str  # 'MRSA', 'VRE', 'ESBL', 'CRE', etc.
    phenotype_name: str
    total_isolates: int
    phenotype_isolates: int
    percent_positive: float


class ARDataExtractor:
    """Extract antimicrobial resistance data from Clarity for NHSN reporting.

    This class queries culture and susceptibility data, implements NHSN's
    first-isolate rule (one isolate per patient per organism per quarter),
    and calculates resistance phenotypes.

    Example:
        extractor = ARDataExtractor()
        summary = extractor.get_quarterly_summary(
            locations=['T5A', 'T5B'],
            year=2026,
            quarter=1
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
                raise ImportError("sqlalchemy required for AR data extraction")
        return self._engine

    def _is_sqlite(self) -> bool:
        """Check if using SQLite (mock) database."""
        return "sqlite" in (self.connection_string or "").lower()

    def _get_quarter_dates(self, year: int, quarter: int) -> tuple[date, date]:
        """Get start and end dates for a quarter."""
        quarter_starts = {1: 1, 2: 4, 3: 7, 4: 10}
        quarter_ends = {1: 3, 2: 6, 3: 9, 4: 12}

        start_month = quarter_starts[quarter]
        end_month = quarter_ends[quarter]

        start_date = date(year, start_month, 1)

        # Last day of end month
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1).replace(day=1)
            end_date = end_date.replace(day=1) - pd.Timedelta(days=1)
            end_date = date(year, end_month + 1, 1)
            # Get last day of end_month
            import calendar
            last_day = calendar.monthrange(year, end_month)[1]
            end_date = date(year, end_month, last_day)

        return start_date, end_date

    def get_culture_results(
        self,
        locations: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        specimen_types: list[str] | None = None,
    ) -> pd.DataFrame:
        """Get culture results with organism identification.

        Args:
            locations: List of NHSN location codes.
            start_date: Start of date range.
            end_date: End of date range.
            specimen_types: Specimen types to include (defaults to Config.AR_SPECIMEN_TYPES).

        Returns:
            DataFrame with culture and organism information.
        """
        if start_date is None:
            # Default to current quarter
            today = date.today()
            quarter = (today.month - 1) // 3 + 1
            start_date, _ = self._get_quarter_dates(today.year, quarter)
        if end_date is None:
            end_date = date.today()

        if specimen_types is None:
            specimen_types = [s.strip() for s in Config.AR_SPECIMEN_TYPES.split(",")]

        # Build filters
        location_filter = ""
        if locations:
            location_list = ", ".join(f"'{loc}'" for loc in locations)
            location_filter = f"AND loc.NHSN_LOCATION_CODE IN ({location_list})"

        specimen_filter = ""
        if specimen_types:
            specimen_list = ", ".join(f"'{s}'" for s in specimen_types)
            specimen_filter = f"AND cr.SPECIMEN_TYPE IN ({specimen_list})"

        if self._is_sqlite():
            quarter_expr = """
                CAST(strftime('%Y', cr.SPECIMEN_TAKEN_TIME) AS TEXT) || '-Q' ||
                CAST((CAST(strftime('%m', cr.SPECIMEN_TAKEN_TIME) AS INTEGER) + 2) / 3 AS TEXT)
            """
        else:
            quarter_expr = """
                CAST(YEAR(cr.SPECIMEN_TAKEN_TIME) AS VARCHAR) + '-Q' +
                CAST(DATEPART(QUARTER, cr.SPECIMEN_TAKEN_TIME) AS VARCHAR)
            """

        query = f"""
        SELECT
            co.CULTURE_ORGANISM_ID as isolate_id,
            cr.CULTURE_ID,
            pat.PAT_MRN_ID as patient_id,
            pe.PAT_ENC_CSN_ID as encounter_id,
            loc.NHSN_LOCATION_CODE,
            cr.SPECIMEN_TAKEN_TIME as specimen_date,
            cr.SPECIMEN_TYPE,
            cr.SPECIMEN_SOURCE,
            cr.CULTURE_STATUS,
            co.ORGANISM_NAME,
            co.ORGANISM_GROUP,
            co.CFU_COUNT,
            co.IS_PRIMARY,
            {quarter_expr} as quarter
        FROM CULTURE_RESULTS cr
        JOIN CULTURE_ORGANISM co ON cr.CULTURE_ID = co.CULTURE_ID
        JOIN PATIENT pat ON cr.PAT_ID = pat.PAT_ID
        LEFT JOIN PAT_ENC pe ON cr.PAT_ENC_CSN_ID = pe.PAT_ENC_CSN_ID
        LEFT JOIN NHSN_LOCATION_MAP loc ON pe.DEPARTMENT_ID = loc.EPIC_DEPT_ID
        WHERE cr.CULTURE_STATUS = 'Positive'
            AND cr.SPECIMEN_TAKEN_TIME >= :start_date
            AND cr.SPECIMEN_TAKEN_TIME <= :end_date
            {location_filter}
            {specimen_filter}
        ORDER BY pat.PAT_MRN_ID, cr.SPECIMEN_TAKEN_TIME, co.ORGANISM_NAME
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
            logger.error(f"Culture results query failed: {e}")
            return pd.DataFrame()

    def get_susceptibility_results(
        self,
        isolate_ids: list[int] | None = None,
    ) -> pd.DataFrame:
        """Get susceptibility results for isolates.

        Args:
            isolate_ids: List of culture_organism_ids to fetch susceptibilities for.
                        If None, returns all susceptibilities.

        Returns:
            DataFrame with susceptibility test results.
        """
        isolate_filter = ""
        if isolate_ids:
            id_list = ", ".join(str(i) for i in isolate_ids)
            isolate_filter = f"WHERE sr.CULTURE_ORGANISM_ID IN ({id_list})"

        query = f"""
        SELECT
            sr.SUSCEPTIBILITY_ID,
            sr.CULTURE_ORGANISM_ID as isolate_id,
            sr.ANTIBIOTIC,
            sr.ANTIBIOTIC_CODE,
            sr.MIC,
            sr.MIC_UNITS,
            sr.INTERPRETATION,
            sr.METHOD
        FROM SUSCEPTIBILITY_RESULTS sr
        {isolate_filter}
        ORDER BY sr.CULTURE_ORGANISM_ID, sr.ANTIBIOTIC
        """

        try:
            from sqlalchemy import text

            engine = self._get_engine()
            with engine.connect() as conn:
                df = pd.read_sql(text(query), conn)
                df.columns = df.columns.str.lower()
                return df
        except Exception as e:
            logger.error(f"Susceptibility results query failed: {e}")
            return pd.DataFrame()

    def apply_first_isolate_rule(
        self,
        cultures_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Apply NHSN first-isolate deduplication rule.

        NHSN requires counting only the first isolate per patient per organism
        per quarter. This prevents over-counting from repeat cultures.

        Args:
            cultures_df: DataFrame from get_culture_results()

        Returns:
            DataFrame with is_first_isolate column added, filtered to first isolates only.
        """
        if cultures_df.empty:
            return cultures_df

        if not Config.AR_FIRST_ISOLATE_ONLY:
            cultures_df["is_first_isolate"] = True
            return cultures_df

        # Sort by patient, organism, and date
        df = cultures_df.copy()
        df = df.sort_values(["patient_id", "organism_name", "quarter", "specimen_date"])

        # Mark first isolate per patient/organism/quarter
        df["is_first_isolate"] = ~df.duplicated(
            subset=["patient_id", "organism_name", "quarter"], keep="first"
        )

        # Return only first isolates
        return df[df["is_first_isolate"]]

    def calculate_resistance_rates(
        self,
        locations: list[str] | None = None,
        year: int | None = None,
        quarter: int | None = None,
        specimen_types: list[str] | None = None,
    ) -> pd.DataFrame:
        """Calculate antimicrobial resistance rates by organism and antibiotic.

        Args:
            locations: List of NHSN location codes.
            year: Year for quarterly reporting.
            quarter: Quarter (1-4) for reporting.
            specimen_types: Specimen types to include.

        Returns:
            DataFrame with resistance rates by organism/antibiotic combination.
        """
        if year is None:
            year = date.today().year
        if quarter is None:
            quarter = (date.today().month - 1) // 3 + 1

        start_date, end_date = self._get_quarter_dates(year, quarter)

        # Get cultures and apply first-isolate rule
        cultures_df = self.get_culture_results(locations, start_date, end_date, specimen_types)
        if cultures_df.empty:
            return pd.DataFrame()

        first_isolates = self.apply_first_isolate_rule(cultures_df)
        if first_isolates.empty:
            return pd.DataFrame()

        # Get susceptibilities for first isolates
        isolate_ids = first_isolates["isolate_id"].tolist()
        suscept_df = self.get_susceptibility_results(isolate_ids)

        if suscept_df.empty:
            return pd.DataFrame()

        # Merge cultures with susceptibilities
        merged = pd.merge(
            first_isolates[["isolate_id", "nhsn_location_code", "quarter", "organism_name"]],
            suscept_df[["isolate_id", "antibiotic", "antibiotic_code", "interpretation"]],
            on="isolate_id",
        )

        # Calculate resistance rates
        resistance_df = (
            merged.groupby(["nhsn_location_code", "quarter", "organism_name", "antibiotic"])
            .agg(
                total_isolates=("isolate_id", "nunique"),
                resistant_isolates=("interpretation", lambda x: (x == "R").sum()),
                intermediate_isolates=("interpretation", lambda x: (x == "I").sum()),
                susceptible_isolates=("interpretation", lambda x: (x == "S").sum()),
            )
            .reset_index()
        )

        # Calculate percentages
        resistance_df["percent_resistant"] = (
            resistance_df["resistant_isolates"] / resistance_df["total_isolates"] * 100
        ).round(1)
        resistance_df["percent_non_susceptible"] = (
            (resistance_df["resistant_isolates"] + resistance_df["intermediate_isolates"])
            / resistance_df["total_isolates"]
            * 100
        ).round(1)

        return resistance_df

    def _check_phenotype_match(
        self,
        organism_name: str,
        susceptibilities: pd.DataFrame,
        organism_pattern: str,
        resistance_pattern: str,
    ) -> bool:
        """Check if an isolate matches a resistance phenotype definition.

        Args:
            organism_name: Name of the organism.
            susceptibilities: Susceptibility results for the isolate.
            organism_pattern: Regex pattern for matching organism.
            resistance_pattern: Pattern defining resistance (e.g., 'OXA:R').

        Returns:
            True if isolate matches the phenotype definition.
        """
        # Check organism match
        if organism_pattern:
            # Handle SQL LIKE patterns
            regex_pattern = organism_pattern.replace("%", ".*").replace("|", "|")
            if not re.search(regex_pattern, organism_name, re.IGNORECASE):
                return False

        # Check resistance pattern
        if resistance_pattern and not susceptibilities.empty:
            # Parse resistance requirements (e.g., "OXA:R" or "MEM:R|ETP:R")
            # OR conditions split by |
            or_conditions = resistance_pattern.split("|")

            for or_cond in or_conditions:
                # AND conditions split by ,
                and_conditions = or_cond.split(",")
                all_met = True

                for cond in and_conditions:
                    if ":" not in cond:
                        continue
                    abx_code, required_interp = cond.split(":")
                    abx_code = abx_code.strip()
                    required_interp = required_interp.strip()

                    # Find matching susceptibility
                    matching = susceptibilities[
                        susceptibilities["antibiotic_code"].str.upper() == abx_code.upper()
                    ]

                    if matching.empty:
                        all_met = False
                        break

                    actual_interp = matching.iloc[0]["interpretation"]
                    if actual_interp != required_interp:
                        all_met = False
                        break

                if all_met:
                    return True

            return False

        return True

    def calculate_phenotypes(
        self,
        locations: list[str] | None = None,
        year: int | None = None,
        quarter: int | None = None,
        specimen_types: list[str] | None = None,
    ) -> pd.DataFrame:
        """Calculate resistance phenotype prevalence (MRSA, VRE, ESBL, CRE, etc.).

        Args:
            locations: List of NHSN location codes.
            year: Year for quarterly reporting.
            quarter: Quarter (1-4) for reporting.
            specimen_types: Specimen types to include.

        Returns:
            DataFrame with phenotype prevalence by location and quarter.
        """
        if year is None:
            year = date.today().year
        if quarter is None:
            quarter = (date.today().month - 1) // 3 + 1

        start_date, end_date = self._get_quarter_dates(year, quarter)

        # Get cultures and apply first-isolate rule
        cultures_df = self.get_culture_results(locations, start_date, end_date, specimen_types)
        if cultures_df.empty:
            return pd.DataFrame()

        first_isolates = self.apply_first_isolate_rule(cultures_df)
        if first_isolates.empty:
            return pd.DataFrame()

        # Get susceptibilities
        isolate_ids = first_isolates["isolate_id"].tolist()
        suscept_df = self.get_susceptibility_results(isolate_ids)

        # Get phenotype definitions
        phenotype_query = """
        SELECT PHENOTYPE_CODE, PHENOTYPE_NAME, ORGANISM_PATTERN, RESISTANCE_PATTERN
        FROM NHSN_PHENOTYPE_MAP
        """

        try:
            from sqlalchemy import text

            engine = self._get_engine()
            with engine.connect() as conn:
                phenotypes = pd.read_sql(text(phenotype_query), conn)
                phenotypes.columns = phenotypes.columns.str.lower()
        except Exception as e:
            logger.error(f"Phenotype query failed: {e}")
            return pd.DataFrame()

        results = []

        # For each location and phenotype, calculate prevalence
        for loc in first_isolates["nhsn_location_code"].unique():
            loc_isolates = first_isolates[first_isolates["nhsn_location_code"] == loc]
            quarter_str = f"{year}-Q{quarter}"

            for _, pheno in phenotypes.iterrows():
                phenotype_matches = 0
                eligible_isolates = 0

                for _, isolate in loc_isolates.iterrows():
                    # Get susceptibilities for this isolate
                    iso_suscept = suscept_df[suscept_df["isolate_id"] == isolate["isolate_id"]]

                    # Check organism eligibility
                    org_pattern = pheno["organism_pattern"] or ""
                    if org_pattern:
                        regex_pattern = org_pattern.replace("%", ".*")
                        if not re.search(regex_pattern, isolate["organism_name"], re.IGNORECASE):
                            continue

                    eligible_isolates += 1

                    # Check phenotype match
                    if self._check_phenotype_match(
                        isolate["organism_name"],
                        iso_suscept,
                        pheno["organism_pattern"] or "",
                        pheno["resistance_pattern"] or "",
                    ):
                        phenotype_matches += 1

                if eligible_isolates > 0:
                    results.append(
                        {
                            "nhsn_location_code": loc,
                            "quarter": quarter_str,
                            "phenotype_code": pheno["phenotype_code"],
                            "phenotype_name": pheno["phenotype_name"],
                            "eligible_isolates": eligible_isolates,
                            "phenotype_isolates": phenotype_matches,
                            "percent_positive": round(
                                phenotype_matches / eligible_isolates * 100, 1
                            ),
                        }
                    )

        return pd.DataFrame(results)

    def get_quarterly_summary(
        self,
        locations: list[str] | None = None,
        year: int | None = None,
        quarter: int | None = None,
        specimen_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Get comprehensive quarterly AR summary for NHSN reporting.

        Args:
            locations: List of NHSN location codes.
            year: Year for quarterly reporting.
            quarter: Quarter (1-4) for reporting.
            specimen_types: Specimen types to include.

        Returns:
            Dictionary with:
            - period: Quarter information
            - locations: List of location summaries with resistance data
            - phenotypes: Resistance phenotype prevalence
            - overall_totals: Aggregate totals
        """
        if year is None:
            year = date.today().year
        if quarter is None:
            quarter = (date.today().month - 1) // 3 + 1

        start_date, end_date = self._get_quarter_dates(year, quarter)
        quarter_str = f"{year}-Q{quarter}"

        # Get all data
        cultures_df = self.get_culture_results(locations, start_date, end_date, specimen_types)
        first_isolates = self.apply_first_isolate_rule(cultures_df)
        resistance_df = self.calculate_resistance_rates(locations, year, quarter, specimen_types)
        phenotype_df = self.calculate_phenotypes(locations, year, quarter, specimen_types)

        result = {
            "period": {
                "year": year,
                "quarter": quarter,
                "quarter_string": quarter_str,
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
            "overall_totals": {
                "total_cultures": len(cultures_df) if not cultures_df.empty else 0,
                "first_isolates": len(first_isolates) if not first_isolates.empty else 0,
                "unique_organisms": (
                    first_isolates["organism_name"].nunique()
                    if not first_isolates.empty
                    else 0
                ),
            },
            "locations": [],
            "phenotypes": [],
        }

        # Build location summaries
        if not first_isolates.empty:
            for loc in sorted(first_isolates["nhsn_location_code"].dropna().unique()):
                loc_isolates = first_isolates[first_isolates["nhsn_location_code"] == loc]
                loc_resistance = (
                    resistance_df[resistance_df["nhsn_location_code"] == loc]
                    if not resistance_df.empty
                    else pd.DataFrame()
                )

                loc_summary = {
                    "nhsn_location_code": loc,
                    "total_isolates": len(loc_isolates),
                    "organisms": [],
                }

                # Summarize by organism
                for org in loc_isolates["organism_name"].unique():
                    org_count = len(loc_isolates[loc_isolates["organism_name"] == org])
                    org_resistance = (
                        loc_resistance[loc_resistance["organism_name"] == org].to_dict("records")
                        if not loc_resistance.empty
                        else []
                    )

                    loc_summary["organisms"].append(
                        {
                            "organism_name": org,
                            "isolate_count": org_count,
                            "resistance_data": org_resistance,
                        }
                    )

                result["locations"].append(loc_summary)

        # Add phenotype summary
        if not phenotype_df.empty:
            result["phenotypes"] = phenotype_df.to_dict("records")

        return result

    def export_for_nhsn(
        self,
        locations: list[str] | None = None,
        year: int | None = None,
        quarter: int | None = None,
        specimen_types: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Export AR data in NHSN submission format.

        Returns separate DataFrames for isolates and susceptibilities.

        Args:
            locations: List of NHSN location codes.
            year: Year for quarterly reporting.
            quarter: Quarter (1-4) for reporting.
            specimen_types: Specimen types to include.

        Returns:
            Dictionary with 'isolates' and 'susceptibilities' DataFrames.
        """
        if year is None:
            year = date.today().year
        if quarter is None:
            quarter = (date.today().month - 1) // 3 + 1

        start_date, end_date = self._get_quarter_dates(year, quarter)

        cultures_df = self.get_culture_results(locations, start_date, end_date, specimen_types)
        first_isolates = self.apply_first_isolate_rule(cultures_df)

        if first_isolates.empty:
            return {"isolates": pd.DataFrame(), "susceptibilities": pd.DataFrame()}

        # Format isolates for NHSN
        isolates_df = pd.DataFrame(
            {
                "orgID": Config.NHSN_FACILITY_ID or "",
                "locationCode": first_isolates["nhsn_location_code"],
                "specimenDate": first_isolates["specimen_date"],
                "specimenType": first_isolates["specimen_type"],
                "organismName": first_isolates["organism_name"],
                "patientID": first_isolates["patient_id"],
                "isolateID": first_isolates["isolate_id"],
            }
        )

        # Get and format susceptibilities
        isolate_ids = first_isolates["isolate_id"].tolist()
        suscept_df = self.get_susceptibility_results(isolate_ids)

        if not suscept_df.empty:
            susceptibilities_df = pd.DataFrame(
                {
                    "isolateID": suscept_df["isolate_id"],
                    "antibiotic": suscept_df["antibiotic"],
                    "antibioticCode": suscept_df["antibiotic_code"],
                    "MIC": suscept_df["mic"],
                    "interpretation": suscept_df["interpretation"],
                }
            )
        else:
            susceptibilities_df = pd.DataFrame()

        return {"isolates": isolates_df, "susceptibilities": susceptibilities_df}
