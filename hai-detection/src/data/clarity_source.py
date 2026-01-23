"""Clarity SQL-based data source implementations.

This module provides access to Epic Clarity data warehouse for clinical notes
and device information. Requires CLARITY_CONNECTION_STRING to be configured.
"""

import logging
from datetime import datetime

from ..config import Config
from ..models import ClinicalNote, DeviceInfo, CultureResult, Patient
from .base import BaseNoteSource, BaseDeviceSource, BaseCultureSource

logger = logging.getLogger(__name__)


class ClarityNoteSource(BaseNoteSource):
    """Clarity HNO_INFO-based note retrieval."""

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string or Config.get_clarity_connection_string()
        self._engine = None

    def _get_engine(self):
        """Lazy initialization of SQLAlchemy engine."""
        if self._engine is None:
            if not self.connection_string:
                raise ValueError("Clarity connection string not configured")
            try:
                from sqlalchemy import create_engine
                self._engine = create_engine(self.connection_string)
            except ImportError:
                raise ImportError("sqlalchemy required for Clarity access")
        return self._engine

    def _is_sqlite(self) -> bool:
        """Check if using SQLite (mock) database."""
        return "sqlite" in (self.connection_string or "").lower()

    def get_notes_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        note_types: list[str] | None = None,
    ) -> list[ClinicalNote]:
        """Retrieve clinical notes from Clarity HNO_INFO.

        Note: This is a template implementation. The exact SQL will depend
        on your institution's Clarity configuration.
        """
        notes = []

        # Map note types to Clarity note type IDs
        # These IDs are institution-specific
        type_filter = ""
        if note_types:
            type_ids = self._map_note_types_to_clarity_ids(note_types)
            if type_ids:
                type_filter = f"AND ip.NOTE_TYPE_C IN ({','.join(map(str, type_ids))})"

        query = f"""
        SELECT
            hn.NOTE_ID,
            pat.PAT_ID,
            ip.NOTE_TYPE_C,
            znt.NAME as NOTE_TYPE_NAME,
            hn.ENTRY_INSTANT_DTTM,
            emp.PROV_NAME as AUTHOR_NAME,
            hn.NOTE_TEXT
        FROM HNO_INFO hn
        JOIN PAT_ENC pe ON hn.PAT_ENC_CSN_ID = pe.PAT_ENC_CSN_ID
        JOIN PATIENT pat ON pe.PAT_ID = pat.PAT_ID
        LEFT JOIN IP_NOTE_TYPE ip ON hn.NOTE_ID = ip.NOTE_ID
        LEFT JOIN ZC_NOTE_TYPE_IP znt ON ip.NOTE_TYPE_C = znt.NOTE_TYPE_C
        LEFT JOIN CLARITY_EMP emp ON hn.ENTRY_USER_ID = emp.PROV_ID
        WHERE pat.PAT_MRN_ID = :patient_id
          AND hn.ENTRY_INSTANT_DTTM BETWEEN :start_date AND :end_date
          {type_filter}
        ORDER BY hn.ENTRY_INSTANT_DTTM DESC
        LIMIT :limit
        """

        try:
            from sqlalchemy import text
            engine = self._get_engine()
            with engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {
                        "patient_id": patient_id,
                        "start_date": start_date,
                        "end_date": end_date,
                        "limit": Config.MAX_NOTES_PER_PATIENT,
                    },
                )

                for row in result:
                    note = ClinicalNote(
                        id=str(row.NOTE_ID),
                        patient_id=patient_id,
                        note_type=self._normalize_note_type(row.NOTE_TYPE_NAME),
                        author=row.AUTHOR_NAME,
                        date=row.ENTRY_INSTANT_DTTM,
                        content=row.NOTE_TEXT or "",
                        source="clarity",
                    )
                    notes.append(note)

        except Exception as e:
            logger.error(f"Clarity note query failed: {e}")

        return notes

    def get_note_by_id(self, note_id: str) -> ClinicalNote | None:
        """Retrieve a specific note by ID from Clarity."""
        query = """
        SELECT
            hn.NOTE_ID,
            pat.PAT_MRN_ID,
            znt.NAME as NOTE_TYPE_NAME,
            hn.ENTRY_INSTANT_DTTM,
            emp.PROV_NAME as AUTHOR_NAME,
            hn.NOTE_TEXT
        FROM HNO_INFO hn
        JOIN PAT_ENC pe ON hn.PAT_ENC_CSN_ID = pe.PAT_ENC_CSN_ID
        JOIN PATIENT pat ON pe.PAT_ID = pat.PAT_ID
        LEFT JOIN IP_NOTE_TYPE ip ON hn.NOTE_ID = ip.NOTE_ID
        LEFT JOIN ZC_NOTE_TYPE_IP znt ON ip.NOTE_TYPE_C = znt.NOTE_TYPE_C
        LEFT JOIN CLARITY_EMP emp ON hn.ENTRY_USER_ID = emp.PROV_ID
        WHERE hn.NOTE_ID = :note_id
        """

        try:
            from sqlalchemy import text
            engine = self._get_engine()
            with engine.connect() as conn:
                result = conn.execute(text(query), {"note_id": note_id}).fetchone()

                if result:
                    return ClinicalNote(
                        id=str(result.NOTE_ID),
                        patient_id=result.PAT_MRN_ID,
                        note_type=self._normalize_note_type(result.NOTE_TYPE_NAME),
                        author=result.AUTHOR_NAME,
                        date=result.ENTRY_INSTANT_DTTM,
                        content=result.NOTE_TEXT or "",
                        source="clarity",
                    )

        except Exception as e:
            logger.error(f"Clarity note fetch failed: {e}")

        return None

    def _map_note_types_to_clarity_ids(self, note_types: list[str]) -> list[int]:
        """Map internal note types to Clarity note type IDs.

        NOTE: These IDs are institution-specific and should be configured.
        """
        # Example mapping - adjust for your institution
        type_map = {
            "progress_note": [1, 2],  # Example IDs
            "id_consult": [10],
            "discharge_summary": [3],
            "h_and_p": [4],
        }
        ids = []
        for t in note_types:
            if t in type_map:
                ids.extend(type_map[t])
        return ids

    def _normalize_note_type(self, clarity_type: str | None) -> str:
        """Normalize Clarity note type name to internal type."""
        if not clarity_type:
            return "other"

        clarity_lower = clarity_type.lower()
        if "progress" in clarity_lower:
            return "progress_note"
        if "consult" in clarity_lower:
            return "consult"
        if "infectious" in clarity_lower or "id " in clarity_lower:
            return "id_consult"
        if "discharge" in clarity_lower:
            return "discharge_summary"
        if "h&p" in clarity_lower or "history" in clarity_lower:
            return "h_and_p"
        return "other"


class ClarityDeviceSource(BaseDeviceSource):
    """Clarity IP_FLWSHT_MEAS-based device retrieval."""

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string or Config.get_clarity_connection_string()
        self._engine = None

    def _get_engine(self):
        """Lazy initialization of SQLAlchemy engine."""
        if self._engine is None:
            if not self.connection_string:
                raise ValueError("Clarity connection string not configured")
            try:
                from sqlalchemy import create_engine
                self._engine = create_engine(self.connection_string)
            except ImportError:
                raise ImportError("sqlalchemy required for Clarity access")
        return self._engine

    def _is_sqlite(self) -> bool:
        """Check if using SQLite (mock) database."""
        return "sqlite" in (self.connection_string or "").lower()

    def get_central_lines(
        self,
        patient_id: str,
        as_of_date: datetime,
    ) -> list[DeviceInfo]:
        """Get central lines present at a given date from Clarity flowsheets.

        NOTE: This query is highly institution-specific based on how central
        lines are documented in flowsheets.
        """
        devices = []

        # Example query - adjust for your institution's flowsheet templates
        query = """
        SELECT DISTINCT
            fm.FLO_MEAS_ID,
            fd.DISP_NAME as LINE_TYPE,
            MIN(fm.RECORDED_TIME) as INSERTION_DATE,
            MAX(CASE WHEN fm.MEAS_VALUE LIKE '%removed%' THEN fm.RECORDED_TIME END) as REMOVAL_DATE,
            MAX(CASE WHEN fd.DISP_NAME LIKE '%site%' THEN fm.MEAS_VALUE END) as SITE
        FROM IP_FLWSHT_MEAS fm
        JOIN IP_FLWSHT_REC fr ON fm.FSD_ID = fr.FSD_ID
        JOIN IP_FLO_GP_DATA fd ON fm.FLO_MEAS_ID = fd.FLO_MEAS_ID
        JOIN PAT_ENC pe ON fr.INPATIENT_DATA_ID = pe.INPATIENT_DATA_ID
        JOIN PATIENT pat ON pe.PAT_ID = pat.PAT_ID
        WHERE pat.PAT_MRN_ID = :patient_id
          AND fd.DISP_NAME LIKE '%central%line%'
          AND fm.RECORDED_TIME <= :as_of_date
        GROUP BY fm.FLO_MEAS_ID, fd.DISP_NAME
        HAVING MIN(fm.RECORDED_TIME) <= :as_of_date
           AND (MAX(CASE WHEN fm.MEAS_VALUE LIKE '%removed%' THEN fm.RECORDED_TIME END) IS NULL
                OR MAX(CASE WHEN fm.MEAS_VALUE LIKE '%removed%' THEN fm.RECORDED_TIME END) >= :as_of_date)
        """

        try:
            from sqlalchemy import text
            engine = self._get_engine()
            with engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {"patient_id": patient_id, "as_of_date": as_of_date},
                )

                for row in result:
                    device = DeviceInfo(
                        device_type=self._normalize_line_type(row.LINE_TYPE),
                        insertion_date=row.INSERTION_DATE,
                        removal_date=row.REMOVAL_DATE,
                        site=row.SITE,
                        fhir_id=None,  # Not applicable for Clarity
                    )
                    devices.append(device)

        except Exception as e:
            logger.error(f"Clarity device query failed: {e}")

        return devices

    def get_active_devices(
        self,
        patient_id: str,
        device_types: list[str] | None = None,
    ) -> list[DeviceInfo]:
        """Get currently active devices from Clarity."""
        # Similar implementation to get_central_lines but for current date
        from datetime import datetime
        return self.get_central_lines(patient_id, datetime.now())

    def _normalize_line_type(self, clarity_type: str | None) -> str:
        """Normalize Clarity line type to internal representation."""
        if not clarity_type:
            return "unknown"

        clarity_lower = clarity_type.lower()
        if "picc" in clarity_lower:
            return "picc"
        if "tunneled" in clarity_lower:
            return "tunneled_catheter"
        if "central" in clarity_lower:
            return "central_venous_catheter"
        return "central_venous_catheter"


class ClarityCultureSource(BaseCultureSource):
    """Clarity-based culture result retrieval."""

    def __init__(self, connection_string: str | None = None):
        self.connection_string = connection_string or Config.get_clarity_connection_string()
        self._engine = None

    def _get_engine(self):
        """Lazy initialization of SQLAlchemy engine."""
        if self._engine is None:
            if not self.connection_string:
                raise ValueError("Clarity connection string not configured")
            try:
                from sqlalchemy import create_engine
                self._engine = create_engine(self.connection_string)
            except ImportError:
                raise ImportError("sqlalchemy required for Clarity access")
        return self._engine

    def _is_sqlite(self) -> bool:
        """Check if using SQLite (mock) database."""
        return "sqlite" in (self.connection_string or "").lower()

    def get_positive_blood_cultures(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[Patient, CultureResult]]:
        """Get positive blood cultures from Clarity ORDER_RESULTS."""
        results = []

        # Example query - adjust for your institution
        query = """
        SELECT
            ores.ORDER_ID,
            pat.PAT_ID,
            pat.PAT_MRN_ID,
            pat.PAT_NAME,
            pat.BIRTH_DATE,
            ores.SPECIMN_TAKEN_TIME as COLLECTION_DATE,
            ores.RESULT_TIME,
            orc.NAME as ORGANISM,
            ores.ORD_VALUE
        FROM ORDER_RESULTS ores
        JOIN ORDER_PROC op ON ores.ORDER_PROC_ID = op.ORDER_PROC_ID
        JOIN PATIENT pat ON op.PAT_ID = pat.PAT_ID
        LEFT JOIN CLARITY_COMPONENT orc ON ores.COMPONENT_ID = orc.COMPONENT_ID
        WHERE op.PROC_NAME LIKE '%blood culture%'
          AND ores.SPECIMN_TAKEN_TIME BETWEEN :start_date AND :end_date
          AND (ores.ORD_VALUE LIKE '%positive%'
               OR ores.ORD_VALUE LIKE '%growth%'
               OR orc.NAME IS NOT NULL)
        ORDER BY ores.SPECIMN_TAKEN_TIME DESC
        """

        try:
            from sqlalchemy import text
            engine = self._get_engine()
            with engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {"start_date": start_date, "end_date": end_date},
                )

                for row in result:
                    patient = Patient(
                        fhir_id=str(row.PAT_ID),
                        mrn=row.PAT_MRN_ID,
                        name=row.PAT_NAME or "",
                        birth_date=str(row.BIRTH_DATE) if row.BIRTH_DATE else None,
                    )

                    culture = CultureResult(
                        fhir_id=str(row.ORDER_ID),
                        collection_date=row.COLLECTION_DATE,
                        organism=row.ORGANISM,
                        result_date=row.RESULT_TIME,
                        specimen_source="blood",
                        is_positive=True,
                    )

                    results.append((patient, culture))

        except Exception as e:
            logger.error(f"Clarity culture query failed: {e}")

        return results

    def get_cultures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CultureResult]:
        """Get cultures for a specific patient from Clarity."""
        cultures = []

        query = """
        SELECT
            ores.ORDER_ID,
            ores.SPECIMN_TAKEN_TIME as COLLECTION_DATE,
            ores.RESULT_TIME,
            orc.NAME as ORGANISM,
            ores.ORD_VALUE
        FROM ORDER_RESULTS ores
        JOIN ORDER_PROC op ON ores.ORDER_PROC_ID = op.ORDER_PROC_ID
        JOIN PATIENT pat ON op.PAT_ID = pat.PAT_ID
        LEFT JOIN CLARITY_COMPONENT orc ON ores.COMPONENT_ID = orc.COMPONENT_ID
        WHERE pat.PAT_MRN_ID = :patient_id
          AND op.PROC_NAME LIKE '%blood culture%'
          AND ores.SPECIMN_TAKEN_TIME BETWEEN :start_date AND :end_date
        ORDER BY ores.SPECIMN_TAKEN_TIME DESC
        """

        try:
            from sqlalchemy import text
            engine = self._get_engine()
            with engine.connect() as conn:
                result = conn.execute(
                    text(query),
                    {
                        "patient_id": patient_id,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )

                for row in result:
                    is_positive = (
                        "positive" in (row.ORD_VALUE or "").lower()
                        or "growth" in (row.ORD_VALUE or "").lower()
                        or row.ORGANISM is not None
                    )

                    culture = CultureResult(
                        fhir_id=str(row.ORDER_ID),
                        collection_date=row.COLLECTION_DATE,
                        organism=row.ORGANISM,
                        result_date=row.RESULT_TIME,
                        specimen_source="blood",
                        is_positive=is_positive,
                    )
                    cultures.append(culture)

        except Exception as e:
            logger.error(f"Clarity culture query failed: {e}")

        return cultures
