"""Database operations for HAI Detection module."""

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
    Patient,
    CultureResult,
    DeviceInfo,
    SupportingEvidence,
    LLMAuditEntry,
    SSICandidate,
    SurgicalProcedure,
    VAECandidate,
    VentilationEpisode,
)

logger = logging.getLogger(__name__)


class HAIDatabase:
    """SQLite database for HAI candidate and classification storage."""

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

        # Save SSI-specific data if present
        if candidate.hai_type == HAIType.SSI and hasattr(candidate, "_ssi_data"):
            self.save_ssi_data(candidate)

        # Save VAE-specific data if present
        if candidate.hai_type == HAIType.VAE and hasattr(candidate, "_vae_data"):
            self.save_vae_data(candidate)

        # Save CDI-specific data if present
        if candidate.hai_type == HAIType.CDI and hasattr(candidate, "_cdi_data"):
            self.save_cdi_data(candidate)

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

        # Load SSI-specific data if this is an SSI candidate
        if candidate.hai_type == HAIType.SSI:
            ssi_data = self._load_ssi_data(candidate.id)
            if ssi_data:
                candidate._ssi_data = ssi_data  # type: ignore

        # Load VAE-specific data if this is a VAE candidate
        if candidate.hai_type == HAIType.VAE:
            vae_data = self._load_vae_data(candidate.id)
            if vae_data:
                candidate._vae_data = vae_data  # type: ignore

        # Load CDI-specific data if this is a CDI candidate
        if candidate.hai_type == HAIType.CDI:
            cdi_data = self.get_cdi_data(candidate.id)
            if cdi_data:
                candidate._cdi_data = cdi_data  # type: ignore

        return candidate

    # --- SSI Operations ---

    def save_ssi_data(self, candidate: HAICandidate) -> None:
        """Save SSI-specific data (procedure and candidate details).

        Args:
            candidate: HAI candidate with _ssi_data attached
        """
        ssi_data: SSICandidate | None = getattr(candidate, "_ssi_data", None)
        if not ssi_data:
            return

        with self._get_connection() as conn:
            # Save procedure first
            proc = ssi_data.procedure
            conn.execute(
                """
                INSERT OR REPLACE INTO ssi_procedures (
                    id, patient_id, patient_mrn, procedure_code, procedure_name,
                    procedure_date, nhsn_category, wound_class, duration_minutes,
                    asa_score, primary_surgeon, implant_used, implant_type,
                    fhir_id, encounter_id, location_code, surveillance_end_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proc.id,
                    candidate.patient.fhir_id,
                    candidate.patient.mrn,
                    proc.procedure_code,
                    proc.procedure_name,
                    proc.procedure_date.isoformat(),
                    proc.nhsn_category,
                    proc.wound_class,
                    proc.duration_minutes,
                    proc.asa_score,
                    proc.primary_surgeon,
                    proc.implant_used,
                    proc.implant_type,
                    proc.fhir_id,
                    proc.encounter_id,
                    proc.location_code,
                    (proc.procedure_date + timedelta(days=proc.get_surveillance_days())).date().isoformat(),
                ),
            )

            # Save SSI candidate details
            import uuid
            detail_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT OR REPLACE INTO ssi_candidate_details (
                    id, candidate_id, procedure_id, days_post_op, ssi_type,
                    infection_date, wound_culture_organism, wound_culture_date,
                    readmission_for_ssi, reoperation_for_ssi
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    detail_id,
                    candidate.id,
                    proc.id,
                    ssi_data.days_post_op,
                    ssi_data.ssi_type,
                    ssi_data.infection_date.isoformat() if ssi_data.infection_date else None,
                    ssi_data.wound_culture_organism,
                    ssi_data.wound_culture_date.isoformat() if ssi_data.wound_culture_date else None,
                    ssi_data.readmission_for_ssi,
                    ssi_data.reoperation_for_ssi,
                ),
            )
            conn.commit()

    def _load_ssi_data(self, candidate_id: str) -> SSICandidate | None:
        """Load SSI-specific data for a candidate.

        Args:
            candidate_id: The candidate ID

        Returns:
            SSICandidate with procedure data, or None if not found
        """
        with self._get_connection() as conn:
            # Get SSI details
            detail_row = conn.execute(
                """
                SELECT d.*, p.*
                FROM ssi_candidate_details d
                JOIN ssi_procedures p ON d.procedure_id = p.id
                WHERE d.candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()

            if not detail_row:
                return None

            # Build SurgicalProcedure
            procedure = SurgicalProcedure(
                id=detail_row["procedure_id"],
                patient_id=detail_row["patient_id"],
                procedure_code=detail_row["procedure_code"],
                procedure_name=detail_row["procedure_name"],
                procedure_date=datetime.fromisoformat(detail_row["procedure_date"]),
                nhsn_category=detail_row["nhsn_category"],
                wound_class=detail_row["wound_class"],
                duration_minutes=detail_row["duration_minutes"],
                asa_score=detail_row["asa_score"],
                primary_surgeon=detail_row["primary_surgeon"],
                implant_used=bool(detail_row["implant_used"]) if detail_row["implant_used"] is not None else False,
                implant_type=detail_row["implant_type"],
                fhir_id=detail_row["fhir_id"],
                encounter_id=detail_row["encounter_id"],
                location_code=detail_row["location_code"],
            )

            # Build SSICandidate
            return SSICandidate(
                candidate_id=candidate_id,
                procedure=procedure,
                days_post_op=detail_row["days_post_op"],
                ssi_type=detail_row["ssi_type"],
                infection_date=datetime.fromisoformat(detail_row["infection_date"]) if detail_row["infection_date"] else None,
                wound_culture_organism=detail_row["wound_culture_organism"],
                wound_culture_date=datetime.fromisoformat(detail_row["wound_culture_date"]) if detail_row["wound_culture_date"] else None,
                readmission_for_ssi=bool(detail_row["readmission_for_ssi"]),
                reoperation_for_ssi=bool(detail_row["reoperation_for_ssi"]),
            )

    # --- VAE Operations ---

    def save_vae_data(self, candidate: HAICandidate) -> None:
        """Save VAE-specific data (episode and candidate details).

        Args:
            candidate: HAI candidate with _vae_data attached
        """
        vae_data: VAECandidate | None = getattr(candidate, "_vae_data", None)
        if not vae_data:
            return

        with self._get_connection() as conn:
            # Save ventilation episode first
            episode = vae_data.episode
            conn.execute(
                """
                INSERT OR REPLACE INTO vae_ventilation_episodes (
                    id, patient_id, patient_mrn, intubation_date, extubation_date,
                    encounter_id, location_code, fhir_device_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.id,
                    episode.patient_id,
                    episode.patient_mrn,
                    episode.intubation_date.isoformat(),
                    episode.extubation_date.isoformat() if episode.extubation_date else None,
                    episode.encounter_id,
                    episode.location_code,
                    episode.fhir_device_id,
                ),
            )

            # Save VAE candidate details
            import uuid
            detail_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT OR REPLACE INTO vae_candidate_details (
                    id, candidate_id, episode_id, vac_onset_date, ventilator_day_at_onset,
                    baseline_start_date, baseline_end_date, baseline_min_fio2, baseline_min_peep,
                    worsening_start_date, fio2_increase, peep_increase,
                    met_fio2_criterion, met_peep_criterion,
                    vae_classification, vae_tier,
                    temperature_criterion_met, wbc_criterion_met, antimicrobial_criterion_met,
                    qualifying_antimicrobials,
                    purulent_secretions_met, positive_culture_met, quantitative_culture_met,
                    organism_identified, specimen_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    detail_id,
                    candidate.id,
                    episode.id,
                    vae_data.vac_onset_date.isoformat(),
                    vae_data.ventilator_day_at_onset,
                    vae_data.baseline_start_date.isoformat() if vae_data.baseline_start_date else None,
                    vae_data.baseline_end_date.isoformat() if vae_data.baseline_end_date else None,
                    vae_data.baseline_min_fio2,
                    vae_data.baseline_min_peep,
                    vae_data.worsening_start_date.isoformat() if vae_data.worsening_start_date else None,
                    vae_data.fio2_increase,
                    vae_data.peep_increase,
                    vae_data.met_fio2_criterion,
                    vae_data.met_peep_criterion,
                    vae_data.vae_classification,
                    vae_data.vae_tier,
                    vae_data.temperature_criterion_met,
                    vae_data.wbc_criterion_met,
                    vae_data.antimicrobial_criterion_met,
                    json.dumps(vae_data.qualifying_antimicrobials),
                    vae_data.purulent_secretions_met,
                    vae_data.positive_culture_met,
                    vae_data.quantitative_culture_met,
                    vae_data.organism_identified,
                    vae_data.specimen_type,
                ),
            )
            conn.commit()

    def _load_vae_data(self, candidate_id: str) -> VAECandidate | None:
        """Load VAE-specific data for a candidate.

        Args:
            candidate_id: The candidate ID

        Returns:
            VAECandidate with episode data, or None if not found
        """
        with self._get_connection() as conn:
            # Get VAE details with episode data
            detail_row = conn.execute(
                """
                SELECT d.*, e.patient_id, e.patient_mrn, e.intubation_date, e.extubation_date,
                       e.encounter_id, e.location_code, e.fhir_device_id
                FROM vae_candidate_details d
                JOIN vae_ventilation_episodes e ON d.episode_id = e.id
                WHERE d.candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()

            if not detail_row:
                return None

            # Build VentilationEpisode
            episode = VentilationEpisode(
                id=detail_row["episode_id"],
                patient_id=detail_row["patient_id"],
                patient_mrn=detail_row["patient_mrn"],
                intubation_date=datetime.fromisoformat(detail_row["intubation_date"]),
                extubation_date=datetime.fromisoformat(detail_row["extubation_date"]) if detail_row["extubation_date"] else None,
                encounter_id=detail_row["encounter_id"],
                location_code=detail_row["location_code"],
                fhir_device_id=detail_row["fhir_device_id"],
            )

            # Parse qualifying antimicrobials JSON
            qualifying_antimicrobials = []
            if detail_row["qualifying_antimicrobials"]:
                try:
                    qualifying_antimicrobials = json.loads(detail_row["qualifying_antimicrobials"])
                except json.JSONDecodeError:
                    pass

            # Build VAECandidate
            return VAECandidate(
                candidate_id=candidate_id,
                episode=episode,
                vac_onset_date=date.fromisoformat(detail_row["vac_onset_date"]),
                ventilator_day_at_onset=detail_row["ventilator_day_at_onset"],
                baseline_start_date=date.fromisoformat(detail_row["baseline_start_date"]) if detail_row["baseline_start_date"] else None,
                baseline_end_date=date.fromisoformat(detail_row["baseline_end_date"]) if detail_row["baseline_end_date"] else None,
                baseline_min_fio2=detail_row["baseline_min_fio2"],
                baseline_min_peep=detail_row["baseline_min_peep"],
                worsening_start_date=date.fromisoformat(detail_row["worsening_start_date"]) if detail_row["worsening_start_date"] else None,
                fio2_increase=detail_row["fio2_increase"],
                peep_increase=detail_row["peep_increase"],
                met_fio2_criterion=bool(detail_row["met_fio2_criterion"]),
                met_peep_criterion=bool(detail_row["met_peep_criterion"]),
                vae_classification=detail_row["vae_classification"],
                vae_tier=detail_row["vae_tier"],
                temperature_criterion_met=bool(detail_row["temperature_criterion_met"]),
                wbc_criterion_met=bool(detail_row["wbc_criterion_met"]),
                antimicrobial_criterion_met=bool(detail_row["antimicrobial_criterion_met"]),
                qualifying_antimicrobials=qualifying_antimicrobials,
                purulent_secretions_met=bool(detail_row["purulent_secretions_met"]),
                positive_culture_met=bool(detail_row["positive_culture_met"]),
                quantitative_culture_met=bool(detail_row["quantitative_culture_met"]),
                organism_identified=detail_row["organism_identified"],
                specimen_type=detail_row["specimen_type"],
            )

    # --- CDI Data Operations ---

    def save_cdi_data(self, candidate: HAICandidate) -> None:
        """Save CDI-specific candidate data."""
        cdi_data = getattr(candidate, "_cdi_data", None)
        if not cdi_data:
            return

        detail_id = f"cdi-{candidate.id}"

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cdi_candidate_details (
                    id, candidate_id, test_type, test_date, loinc_code,
                    specimen_day, onset_type, is_recurrent, days_since_last_cdi,
                    prior_episode_date, recent_discharge_date, days_since_prior_discharge,
                    diarrhea_documented, treatment_initiated, treatment_type,
                    classification, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    detail_id,
                    candidate.id,
                    cdi_data.test_result.test_type,
                    cdi_data.test_result.test_date.isoformat(),
                    cdi_data.test_result.loinc_code,
                    cdi_data.specimen_day,
                    cdi_data.onset_type,
                    cdi_data.is_recurrent,
                    cdi_data.days_since_last_cdi,
                    cdi_data.prior_episodes[0].test_date.isoformat() if cdi_data.prior_episodes else None,
                    cdi_data.recent_discharge_date.isoformat() if cdi_data.recent_discharge_date else None,
                    (cdi_data.admission_date.date() - cdi_data.recent_discharge_date.date()).days
                        if cdi_data.recent_discharge_date and cdi_data.admission_date else None,
                    getattr(cdi_data, "diarrhea_documented", False),
                    getattr(cdi_data, "treatment_initiated", False),
                    getattr(cdi_data, "treatment_type", None),
                    cdi_data.classification,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()

    def get_cdi_data(self, candidate_id: str) -> "CDICandidate | None":
        """Get CDI-specific data for a candidate."""
        from .models import CDICandidate, CDITestResult, CDIEpisode

        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM cdi_candidate_details WHERE candidate_id = ?
                """,
                (candidate_id,),
            ).fetchone()

            if not row:
                return None

            # Get the main candidate for admission date
            candidate_row = conn.execute(
                "SELECT culture_date FROM hai_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()

            # Build CDITestResult
            test_result = CDITestResult(
                fhir_id=candidate_id,  # We don't store original fhir_id
                patient_id="",
                test_date=datetime.fromisoformat(row["test_date"]),
                test_type=row["test_type"],
                result="positive",
                loinc_code=row["loinc_code"],
            )

            # Build prior episodes if present
            prior_episodes = []
            if row["prior_episode_date"]:
                prior_episodes.append(CDIEpisode(
                    id="prior",
                    patient_id="",
                    test_date=datetime.fromisoformat(row["prior_episode_date"]),
                    test_type=row["test_type"],
                    onset_type="unknown",
                    is_recurrent=False,
                ))

            return CDICandidate(
                candidate_id=candidate_id,
                test_result=test_result,
                admission_date=datetime.fromisoformat(candidate_row["culture_date"]) - timedelta(days=row["specimen_day"] - 1)
                    if candidate_row and row["specimen_day"] else None,
                specimen_day=row["specimen_day"],
                onset_type=row["onset_type"],
                prior_episodes=prior_episodes,
                days_since_last_cdi=row["days_since_last_cdi"],
                is_recurrent=bool(row["is_recurrent"]),
                is_duplicate=False,
                recent_discharge_date=datetime.fromisoformat(row["recent_discharge_date"]) if row["recent_discharge_date"] else None,
                recent_discharge_facility=None,
                classification=row["classification"],
                diarrhea_documented=bool(row["diarrhea_documented"]),
                treatment_initiated=bool(row["treatment_initiated"]),
                treatment_type=row["treatment_type"],
            )

    # --- Classification Operations ---

    def save_classification(self, classification: Classification) -> None:
        """Save an LLM classification."""
        row = classification.to_db_row()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO hai_classifications (
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
                "SELECT * FROM hai_classifications WHERE id = ?", (classification_id,)
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
                "SELECT * FROM hai_classifications WHERE candidate_id = ? ORDER BY created_at DESC",
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

    def get_pending_reviews(
        self, queue_type: ReviewQueueType | None = None
    ) -> list[dict[str, Any]]:
        """Get pending reviews with candidate and classification info."""
        with self._get_connection() as conn:
            if queue_type:
                rows = conn.execute(
                    "SELECT * FROM hai_pending_reviews WHERE queue_type = ?",
                    (queue_type.value,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM hai_pending_reviews").fetchall()
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
                INSERT INTO hai_reviews (
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
                INSERT INTO hai_reviews (
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
                UPDATE hai_reviews
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
                UPDATE hai_reviews
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

    # --- Audit Operations ---

    def log_llm_call(self, entry: LLMAuditEntry) -> None:
        """Log an LLM API call for auditing."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO hai_llm_audit (
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
            rows = conn.execute("SELECT * FROM hai_candidate_stats").fetchall()
            return [dict(row) for row in rows]

    def get_summary_stats(self, since_date: str | None = None) -> dict[str, Any]:
        """Get overall summary statistics.

        Args:
            since_date: Optional date string (YYYY-MM-DD) to filter stats.
                       If provided, only counts candidates created after this date.

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
            cursor = conn.execute("PRAGMA table_info(hai_reviews)")
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
            total = conn.execute("SELECT COUNT(*) FROM hai_reviews").fetchone()[0]

            # Completed reviews
            completed = conn.execute(
                "SELECT COUNT(*) FROM hai_reviews WHERE reviewed = 1"
            ).fetchone()[0]

            # Total overrides
            overrides = conn.execute(
                "SELECT COUNT(*) FROM hai_reviews WHERE is_override = 1"
            ).fetchone()[0]

            # Accepted (completed and not override)
            accepted = conn.execute(
                "SELECT COUNT(*) FROM hai_reviews WHERE reviewed = 1 AND is_override = 0"
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
                FROM hai_reviews
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
            cursor = conn.execute("PRAGMA table_info(hai_reviews)")
            columns = [row[1] for row in cursor.fetchall()]

            if "is_override" not in columns:
                return []

            rows = conn.execute(
                """
                SELECT r.*, c.patient_mrn, c.organism
                FROM hai_reviews r
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
                FROM hai_reviews
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
