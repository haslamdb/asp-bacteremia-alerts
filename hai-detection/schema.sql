-- HAI Detection Module Database Schema
-- SQLite schema for HAI candidate tracking, classification, and review

-- HAI Candidates (rule-based screening results)
CREATE TABLE IF NOT EXISTS hai_candidates (
    id TEXT PRIMARY KEY,
    hai_type TEXT NOT NULL DEFAULT 'clabsi',
    patient_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    patient_name TEXT,
    culture_id TEXT NOT NULL,
    culture_date TIMESTAMP NOT NULL,
    organism TEXT,
    device_info TEXT,  -- JSON: line_type, insertion_date, site
    device_days_at_culture INTEGER,
    meets_initial_criteria BOOLEAN NOT NULL DEFAULT 1,
    exclusion_reason TEXT,
    status TEXT DEFAULT 'pending',
    nhsn_reported INTEGER DEFAULT 0,
    nhsn_reported_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hai_type, culture_id)
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_hai_candidates_status ON hai_candidates(status);
CREATE INDEX IF NOT EXISTS idx_hai_candidates_patient ON hai_candidates(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_hai_candidates_date ON hai_candidates(culture_date);
CREATE INDEX IF NOT EXISTS idx_hai_candidates_hai_type ON hai_candidates(hai_type);

-- LLM Classifications
CREATE TABLE IF NOT EXISTS hai_classifications (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    decision TEXT NOT NULL,  -- hai_confirmed, not_hai, pending_review
    confidence REAL NOT NULL,
    alternative_source TEXT,
    is_mbi_lcbi BOOLEAN DEFAULT 0,
    supporting_evidence TEXT,  -- JSON array
    contradicting_evidence TEXT,  -- JSON array
    reasoning TEXT,
    model_used TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    tokens_used INTEGER,
    processing_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES hai_candidates(id)
);

CREATE INDEX IF NOT EXISTS idx_hai_classifications_candidate ON hai_classifications(candidate_id);
CREATE INDEX IF NOT EXISTS idx_hai_classifications_decision ON hai_classifications(decision);

-- IP Review Queue
CREATE TABLE IF NOT EXISTS hai_reviews (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    classification_id TEXT,
    queue_type TEXT NOT NULL DEFAULT 'ip_review',  -- ip_review, manual_review
    reviewed BOOLEAN DEFAULT 0,
    reviewer TEXT,
    reviewer_decision TEXT,  -- confirmed, rejected, needs_more_info
    reviewer_notes TEXT,
    -- Override tracking fields
    llm_decision TEXT,  -- Original LLM decision for comparison
    is_override BOOLEAN DEFAULT 0,  -- True if reviewer disagreed with LLM
    override_reason TEXT,  -- Specific reason for override (optional, detailed)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES hai_candidates(id),
    FOREIGN KEY (classification_id) REFERENCES hai_classifications(id)
);

CREATE INDEX IF NOT EXISTS idx_hai_reviews_candidate ON hai_reviews(candidate_id);
CREATE INDEX IF NOT EXISTS idx_hai_reviews_reviewed ON hai_reviews(reviewed);
CREATE INDEX IF NOT EXISTS idx_hai_reviews_queue_type ON hai_reviews(queue_type);
CREATE INDEX IF NOT EXISTS idx_hai_reviews_override ON hai_reviews(is_override);

-- LLM Audit Log
CREATE TABLE IF NOT EXISTS hai_llm_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT,
    model TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    response_time_ms INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hai_llm_audit_candidate ON hai_llm_audit(candidate_id);
CREATE INDEX IF NOT EXISTS idx_hai_llm_audit_model ON hai_llm_audit(model);

-- Statistics/Metrics view
CREATE VIEW IF NOT EXISTS hai_candidate_stats AS
SELECT
    hai_type,
    status,
    COUNT(*) as count,
    DATE(created_at) as date
FROM hai_candidates
GROUP BY hai_type, status, DATE(created_at);

-- Pending reviews view
-- Filters out resolved candidates (confirmed/rejected) to prevent stale reviews from appearing
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
ORDER BY r.created_at ASC;

-- IP Review Override Statistics
-- Tracks acceptance rate and override patterns for LLM quality assessment
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
FROM hai_reviews;

-- Detailed override history for analysis
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
ORDER BY r.reviewed_at DESC;

-- Override breakdown by LLM decision type
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
GROUP BY llm_decision;

-- ============================================================
-- SSI (Surgical Site Infection) Tracking Tables
-- ============================================================

-- SSI Procedures - tracked surgical procedures for SSI surveillance
CREATE TABLE IF NOT EXISTS ssi_procedures (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    procedure_code TEXT NOT NULL,
    procedure_name TEXT NOT NULL,
    procedure_date TIMESTAMP NOT NULL,
    nhsn_category TEXT,  -- COLO, HPRO, CABG, etc.
    wound_class INTEGER,  -- 1=Clean, 2=Clean-Contaminated, 3=Contaminated, 4=Dirty
    duration_minutes INTEGER,
    asa_score INTEGER,  -- ASA Physical Status 1-5
    primary_surgeon TEXT,
    implant_used BOOLEAN DEFAULT 0,
    implant_type TEXT,
    fhir_id TEXT,
    encounter_id TEXT,
    location_code TEXT,
    surveillance_end_date DATE,  -- Calculated: procedure_date + surveillance window
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(fhir_id)
);

CREATE INDEX IF NOT EXISTS idx_ssi_procedures_patient ON ssi_procedures(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_ssi_procedures_date ON ssi_procedures(procedure_date);
CREATE INDEX IF NOT EXISTS idx_ssi_procedures_category ON ssi_procedures(nhsn_category);
CREATE INDEX IF NOT EXISTS idx_ssi_procedures_surveillance ON ssi_procedures(surveillance_end_date);

-- SSI Candidate Details - SSI-specific data linked to hai_candidates
CREATE TABLE IF NOT EXISTS ssi_candidate_details (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    days_post_op INTEGER NOT NULL,
    ssi_type TEXT,  -- superficial_incisional, deep_incisional, organ_space
    infection_date DATE,
    wound_culture_organism TEXT,
    wound_culture_date DATE,
    readmission_for_ssi BOOLEAN DEFAULT 0,
    reoperation_for_ssi BOOLEAN DEFAULT 0,
    organ_space_site TEXT,  -- NHSN specific site code for organ/space SSI
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES hai_candidates(id),
    FOREIGN KEY (procedure_id) REFERENCES ssi_procedures(id)
);

CREATE INDEX IF NOT EXISTS idx_ssi_details_candidate ON ssi_candidate_details(candidate_id);
CREATE INDEX IF NOT EXISTS idx_ssi_details_procedure ON ssi_candidate_details(procedure_id);
CREATE INDEX IF NOT EXISTS idx_ssi_details_type ON ssi_candidate_details(ssi_type);

-- SSI Rates View - monthly SSI rates by procedure category
CREATE VIEW IF NOT EXISTS ssi_rates_monthly AS
SELECT
    strftime('%Y-%m', p.procedure_date) as month,
    p.nhsn_category,
    COUNT(DISTINCT p.id) as procedures,
    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL AND c.status = 'confirmed' THEN c.id END) as ssi_count,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN c.id IS NOT NULL AND c.status = 'confirmed' THEN c.id END) /
          NULLIF(COUNT(DISTINCT p.id), 0), 2) as ssi_rate_pct
FROM ssi_procedures p
LEFT JOIN ssi_candidate_details d ON p.id = d.procedure_id
LEFT JOIN hai_candidates c ON d.candidate_id = c.id
GROUP BY strftime('%Y-%m', p.procedure_date), p.nhsn_category;

-- SSI by Type View
CREATE VIEW IF NOT EXISTS ssi_by_type AS
SELECT
    ssi_type,
    COUNT(*) as count,
    strftime('%Y-%m', created_at) as month
FROM ssi_candidate_details
WHERE ssi_type IS NOT NULL
GROUP BY ssi_type, strftime('%Y-%m', created_at);


-- ============================================================
-- VAE (Ventilator-Associated Event) Tracking Tables
-- ============================================================

-- VAE Ventilation Episodes - tracked mechanical ventilation episodes
CREATE TABLE IF NOT EXISTS vae_ventilation_episodes (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    intubation_date TIMESTAMP NOT NULL,
    extubation_date TIMESTAMP,
    encounter_id TEXT,
    location_code TEXT,  -- NHSN location code
    fhir_device_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(patient_id, intubation_date)
);

CREATE INDEX IF NOT EXISTS idx_vae_episodes_patient ON vae_ventilation_episodes(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_vae_episodes_intubation ON vae_ventilation_episodes(intubation_date);
CREATE INDEX IF NOT EXISTS idx_vae_episodes_encounter ON vae_ventilation_episodes(encounter_id);

-- VAE Daily Parameters - FiO2/PEEP time series for each ventilation day
CREATE TABLE IF NOT EXISTS vae_daily_parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL,
    date DATE NOT NULL,
    ventilator_day INTEGER NOT NULL,  -- 1-based day number
    min_fio2 REAL,  -- Minimum FiO2 for the day (percentage)
    min_peep REAL,  -- Minimum PEEP for the day (cmH2O)
    fio2_observation_id TEXT,  -- FHIR Observation ID
    peep_observation_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (episode_id) REFERENCES vae_ventilation_episodes(id),
    UNIQUE(episode_id, date)
);

CREATE INDEX IF NOT EXISTS idx_vae_params_episode ON vae_daily_parameters(episode_id);
CREATE INDEX IF NOT EXISTS idx_vae_params_date ON vae_daily_parameters(date);

-- VAE Candidate Details - VAE-specific data linked to hai_candidates
CREATE TABLE IF NOT EXISTS vae_candidate_details (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    vac_onset_date DATE NOT NULL,
    ventilator_day_at_onset INTEGER NOT NULL,
    -- Baseline period
    baseline_start_date DATE,
    baseline_end_date DATE,
    baseline_min_fio2 REAL,
    baseline_min_peep REAL,
    -- Worsening detection
    worsening_start_date DATE,
    fio2_increase REAL,  -- Percentage point increase
    peep_increase REAL,  -- cmH2O increase
    met_fio2_criterion BOOLEAN DEFAULT 0,
    met_peep_criterion BOOLEAN DEFAULT 0,
    -- Classification
    vae_classification TEXT,  -- vac, ivac, possible_vap, probable_vap
    vae_tier INTEGER,  -- 1, 2, or 3
    -- IVAC criteria
    temperature_criterion_met BOOLEAN DEFAULT 0,
    wbc_criterion_met BOOLEAN DEFAULT 0,
    antimicrobial_criterion_met BOOLEAN DEFAULT 0,
    qualifying_antimicrobials TEXT,  -- JSON array
    -- VAP criteria
    purulent_secretions_met BOOLEAN DEFAULT 0,
    positive_culture_met BOOLEAN DEFAULT 0,
    quantitative_culture_met BOOLEAN DEFAULT 0,
    organism_identified TEXT,
    specimen_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES hai_candidates(id),
    FOREIGN KEY (episode_id) REFERENCES vae_ventilation_episodes(id)
);

CREATE INDEX IF NOT EXISTS idx_vae_details_candidate ON vae_candidate_details(candidate_id);
CREATE INDEX IF NOT EXISTS idx_vae_details_episode ON vae_candidate_details(episode_id);
CREATE INDEX IF NOT EXISTS idx_vae_details_classification ON vae_candidate_details(vae_classification);
CREATE INDEX IF NOT EXISTS idx_vae_details_tier ON vae_candidate_details(vae_tier);

-- VAE Rates View - monthly VAE rates per 1000 ventilator days
CREATE VIEW IF NOT EXISTS vae_rates_monthly AS
SELECT
    strftime('%Y-%m', e.intubation_date) as month,
    COUNT(DISTINCT e.id) as episodes,
    SUM(
        CAST(
            julianday(COALESCE(e.extubation_date, date('now'))) -
            julianday(e.intubation_date) + 1
        AS INTEGER)
    ) as ventilator_days,
    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) as vae_count,
    ROUND(
        1000.0 * COUNT(DISTINCT CASE WHEN c.id IS NOT NULL AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) /
        NULLIF(SUM(
            CAST(
                julianday(COALESCE(e.extubation_date, date('now'))) -
                julianday(e.intubation_date) + 1
            AS INTEGER)
        ), 0),
        2
    ) as vae_rate_per_1000_vent_days
FROM vae_ventilation_episodes e
LEFT JOIN vae_candidate_details d ON e.id = d.episode_id
LEFT JOIN hai_candidates c ON d.candidate_id = c.id AND c.hai_type = 'vae'
GROUP BY strftime('%Y-%m', e.intubation_date);

-- VAE by Tier View - counts by VAE classification tier
CREATE VIEW IF NOT EXISTS vae_by_tier AS
SELECT
    vae_classification,
    vae_tier,
    COUNT(*) as count,
    strftime('%Y-%m', created_at) as month
FROM vae_candidate_details
WHERE vae_classification IS NOT NULL
GROUP BY vae_classification, vae_tier, strftime('%Y-%m', created_at);

-- VAE by Location View - VAE counts by unit/location
CREATE VIEW IF NOT EXISTS vae_by_location AS
SELECT
    e.location_code,
    strftime('%Y-%m', e.intubation_date) as month,
    COUNT(DISTINCT e.id) as episodes,
    COUNT(DISTINCT CASE WHEN d.vae_classification IS NOT NULL THEN d.id END) as vae_count,
    COUNT(DISTINCT CASE WHEN d.vae_classification = 'vac' THEN d.id END) as vac_count,
    COUNT(DISTINCT CASE WHEN d.vae_classification = 'ivac' THEN d.id END) as ivac_count,
    COUNT(DISTINCT CASE WHEN d.vae_classification IN ('possible_vap', 'probable_vap') THEN d.id END) as vap_count
FROM vae_ventilation_episodes e
LEFT JOIN vae_candidate_details d ON e.id = d.episode_id
WHERE e.location_code IS NOT NULL
GROUP BY e.location_code, strftime('%Y-%m', e.intubation_date);


-- ============================================================
-- CAUTI (Catheter-Associated Urinary Tract Infection) Tracking Tables
-- ============================================================

-- CAUTI Catheter Episodes - tracked indwelling urinary catheter episodes
CREATE TABLE IF NOT EXISTS cauti_catheter_episodes (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    insertion_date TIMESTAMP NOT NULL,
    removal_date TIMESTAMP,
    catheter_type TEXT,  -- urethral, suprapubic
    site TEXT,  -- urethral, suprapubic
    encounter_id TEXT,
    location_code TEXT,
    fhir_device_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(patient_id, insertion_date)
);

CREATE INDEX IF NOT EXISTS idx_cauti_episodes_patient ON cauti_catheter_episodes(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_cauti_episodes_insertion ON cauti_catheter_episodes(insertion_date);
CREATE INDEX IF NOT EXISTS idx_cauti_episodes_encounter ON cauti_catheter_episodes(encounter_id);

-- CAUTI Candidate Details - CAUTI-specific data linked to hai_candidates
CREATE TABLE IF NOT EXISTS cauti_candidate_details (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    catheter_episode_id TEXT NOT NULL,
    catheter_days INTEGER NOT NULL,
    patient_age INTEGER,
    -- Culture details
    culture_cfu_ml INTEGER,
    culture_organism TEXT,
    culture_organism_count INTEGER,
    -- Symptom tracking
    fever_documented BOOLEAN DEFAULT 0,
    dysuria_documented BOOLEAN DEFAULT 0,
    urgency_documented BOOLEAN DEFAULT 0,
    frequency_documented BOOLEAN DEFAULT 0,
    suprapubic_tenderness BOOLEAN DEFAULT 0,
    cva_tenderness BOOLEAN DEFAULT 0,
    -- Classification
    classification TEXT,  -- cauti, not_cauti, asymptomatic_bacteriuria
    -- Age-based fever rule
    fever_eligible_per_age_rule BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES hai_candidates(id),
    FOREIGN KEY (catheter_episode_id) REFERENCES cauti_catheter_episodes(id)
);

CREATE INDEX IF NOT EXISTS idx_cauti_details_candidate ON cauti_candidate_details(candidate_id);
CREATE INDEX IF NOT EXISTS idx_cauti_details_episode ON cauti_candidate_details(catheter_episode_id);
CREATE INDEX IF NOT EXISTS idx_cauti_details_classification ON cauti_candidate_details(classification);

-- CAUTI Rates View - monthly CAUTI rates per 1000 catheter days
CREATE VIEW IF NOT EXISTS cauti_rates_monthly AS
SELECT
    strftime('%Y-%m', e.insertion_date) as month,
    COUNT(DISTINCT e.id) as episodes,
    SUM(
        CAST(
            julianday(COALESCE(e.removal_date, date('now'))) -
            julianday(e.insertion_date) + 1
        AS INTEGER)
    ) as catheter_days,
    COUNT(DISTINCT CASE WHEN c.id IS NOT NULL AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) as cauti_count,
    ROUND(
        1000.0 * COUNT(DISTINCT CASE WHEN c.id IS NOT NULL AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) /
        NULLIF(SUM(
            CAST(
                julianday(COALESCE(e.removal_date, date('now'))) -
                julianday(e.insertion_date) + 1
            AS INTEGER)
        ), 0),
        2
    ) as cauti_rate_per_1000_cath_days
FROM cauti_catheter_episodes e
LEFT JOIN cauti_candidate_details d ON e.id = d.catheter_episode_id
LEFT JOIN hai_candidates c ON d.candidate_id = c.id AND c.hai_type = 'cauti'
GROUP BY strftime('%Y-%m', e.insertion_date);

-- CAUTI by Classification View
CREATE VIEW IF NOT EXISTS cauti_by_classification AS
SELECT
    classification,
    COUNT(*) as count,
    strftime('%Y-%m', created_at) as month
FROM cauti_candidate_details
WHERE classification IS NOT NULL
GROUP BY classification, strftime('%Y-%m', created_at);

-- CAUTI by Location View
CREATE VIEW IF NOT EXISTS cauti_by_location AS
SELECT
    e.location_code,
    strftime('%Y-%m', e.insertion_date) as month,
    COUNT(DISTINCT e.id) as episodes,
    COUNT(DISTINCT CASE WHEN d.classification = 'cauti' THEN d.id END) as cauti_count,
    COUNT(DISTINCT CASE WHEN d.classification = 'asymptomatic_bacteriuria' THEN d.id END) as asb_count
FROM cauti_catheter_episodes e
LEFT JOIN cauti_candidate_details d ON e.id = d.catheter_episode_id
WHERE e.location_code IS NOT NULL
GROUP BY e.location_code, strftime('%Y-%m', e.insertion_date);

-- CAUTI Symptom Distribution View
CREATE VIEW IF NOT EXISTS cauti_symptom_distribution AS
SELECT
    strftime('%Y-%m', created_at) as month,
    SUM(CASE WHEN fever_documented = 1 THEN 1 ELSE 0 END) as fever_count,
    SUM(CASE WHEN dysuria_documented = 1 THEN 1 ELSE 0 END) as dysuria_count,
    SUM(CASE WHEN urgency_documented = 1 THEN 1 ELSE 0 END) as urgency_count,
    SUM(CASE WHEN frequency_documented = 1 THEN 1 ELSE 0 END) as frequency_count,
    SUM(CASE WHEN suprapubic_tenderness = 1 THEN 1 ELSE 0 END) as suprapubic_count,
    SUM(CASE WHEN cva_tenderness = 1 THEN 1 ELSE 0 END) as cva_count,
    COUNT(*) as total_candidates
FROM cauti_candidate_details
WHERE classification = 'cauti'
GROUP BY strftime('%Y-%m', created_at);


-- ============================================================
-- CDI (Clostridioides difficile Infection) Tracking Tables
-- ============================================================

-- CDI Episodes - tracked CDI events for recurrence detection
-- This table stores all confirmed CDI episodes for tracking recurrence
CREATE TABLE IF NOT EXISTS cdi_episodes (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    test_date TIMESTAMP NOT NULL,
    test_type TEXT NOT NULL,  -- toxin_ab, pcr, naat, etc.
    loinc_code TEXT,
    specimen_day INTEGER NOT NULL,  -- Days since admission (day 1 = admission)
    onset_type TEXT NOT NULL,  -- ho (healthcare-facility), co (community), co_hcfa
    is_recurrent BOOLEAN DEFAULT 0,
    prior_episode_id TEXT REFERENCES cdi_episodes(id),
    admission_date TIMESTAMP,
    discharge_date TIMESTAMP,
    fhir_observation_id TEXT,
    encounter_id TEXT,
    location_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(patient_id, test_date)
);

CREATE INDEX IF NOT EXISTS idx_cdi_episodes_patient ON cdi_episodes(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_cdi_episodes_test_date ON cdi_episodes(test_date);
CREATE INDEX IF NOT EXISTS idx_cdi_episodes_onset_type ON cdi_episodes(onset_type);
CREATE INDEX IF NOT EXISTS idx_cdi_episodes_encounter ON cdi_episodes(encounter_id);

-- CDI Candidate Details - CDI-specific data linked to hai_candidates
CREATE TABLE IF NOT EXISTS cdi_candidate_details (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    episode_id TEXT REFERENCES cdi_episodes(id),
    test_type TEXT NOT NULL,
    test_date TIMESTAMP NOT NULL,
    loinc_code TEXT,
    specimen_day INTEGER NOT NULL,  -- Days since admission
    onset_type TEXT NOT NULL,  -- ho, co, co_hcfa
    is_recurrent BOOLEAN DEFAULT 0,
    days_since_last_cdi INTEGER,
    prior_episode_date TIMESTAMP,
    -- CO-HCFA tracking
    recent_discharge_date TIMESTAMP,
    days_since_prior_discharge INTEGER,
    -- Clinical documentation
    diarrhea_documented BOOLEAN DEFAULT 0,
    treatment_initiated BOOLEAN DEFAULT 0,
    treatment_type TEXT,  -- vancomycin, fidaxomicin, metronidazole
    -- Classification
    classification TEXT,  -- ho_cdi, co_cdi, co_hcfa_cdi, recurrent_ho, recurrent_co, duplicate, not_cdi
    recurrence_status TEXT,  -- incident, recurrent, duplicate
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES hai_candidates(id)
);

CREATE INDEX IF NOT EXISTS idx_cdi_details_candidate ON cdi_candidate_details(candidate_id);
CREATE INDEX IF NOT EXISTS idx_cdi_details_episode ON cdi_candidate_details(episode_id);
CREATE INDEX IF NOT EXISTS idx_cdi_details_classification ON cdi_candidate_details(classification);
CREATE INDEX IF NOT EXISTS idx_cdi_details_onset_type ON cdi_candidate_details(onset_type);
CREATE INDEX IF NOT EXISTS idx_cdi_details_recurrence ON cdi_candidate_details(recurrence_status);

-- CDI Rates View - monthly HO-CDI rates per 10,000 patient days
-- NHSN reporting focuses on HO-CDI (Healthcare-Facility Onset)
CREATE VIEW IF NOT EXISTS cdi_rates_monthly AS
SELECT
    strftime('%Y-%m', c.culture_date) as month,
    COUNT(DISTINCT CASE WHEN d.onset_type = 'ho' AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) as ho_cdi_count,
    COUNT(DISTINCT CASE WHEN d.onset_type = 'co' AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) as co_cdi_count,
    COUNT(DISTINCT CASE WHEN d.onset_type = 'co_hcfa' AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) as co_hcfa_count,
    COUNT(DISTINCT CASE WHEN d.is_recurrent = 1 AND c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) as recurrent_count,
    COUNT(DISTINCT CASE WHEN c.status IN ('confirmed', 'pending_review', 'classified') THEN c.id END) as total_cdi_count
FROM hai_candidates c
JOIN cdi_candidate_details d ON c.id = d.candidate_id
WHERE c.hai_type = 'cdi'
  AND d.classification NOT IN ('duplicate', 'not_cdi', 'not_eligible')
GROUP BY strftime('%Y-%m', c.culture_date);

-- CDI by Onset Type View
CREATE VIEW IF NOT EXISTS cdi_by_onset_type AS
SELECT
    onset_type,
    recurrence_status,
    COUNT(*) as count,
    strftime('%Y-%m', created_at) as month
FROM cdi_candidate_details
WHERE classification NOT IN ('duplicate', 'not_cdi', 'not_eligible')
GROUP BY onset_type, recurrence_status, strftime('%Y-%m', created_at);

-- CDI by Location View - CDI counts by unit/location
CREATE VIEW IF NOT EXISTS cdi_by_location AS
SELECT
    c.patient_id,
    strftime('%Y-%m', c.culture_date) as month,
    d.onset_type,
    COUNT(DISTINCT c.id) as cdi_count,
    COUNT(DISTINCT CASE WHEN d.onset_type = 'ho' THEN c.id END) as ho_count,
    COUNT(DISTINCT CASE WHEN d.onset_type = 'co' THEN c.id END) as co_count,
    COUNT(DISTINCT CASE WHEN d.onset_type = 'co_hcfa' THEN c.id END) as co_hcfa_count
FROM hai_candidates c
JOIN cdi_candidate_details d ON c.id = d.candidate_id
WHERE c.hai_type = 'cdi'
  AND d.classification NOT IN ('duplicate', 'not_cdi', 'not_eligible')
GROUP BY c.patient_id, strftime('%Y-%m', c.culture_date), d.onset_type;

-- CDI Recurrence Tracking View - for analyzing recurrence patterns
CREATE VIEW IF NOT EXISTS cdi_recurrence_tracking AS
SELECT
    e1.patient_mrn,
    e1.test_date as current_episode_date,
    e1.onset_type as current_onset_type,
    e2.test_date as prior_episode_date,
    e2.onset_type as prior_onset_type,
    CAST(julianday(e1.test_date) - julianday(e2.test_date) AS INTEGER) as days_between,
    CASE
        WHEN CAST(julianday(e1.test_date) - julianday(e2.test_date) AS INTEGER) <= 14 THEN 'duplicate'
        WHEN CAST(julianday(e1.test_date) - julianday(e2.test_date) AS INTEGER) <= 56 THEN 'recurrent'
        ELSE 'incident'
    END as recurrence_status
FROM cdi_episodes e1
LEFT JOIN cdi_episodes e2 ON e1.patient_id = e2.patient_id
    AND e2.test_date < e1.test_date
    AND e2.test_date = (
        SELECT MAX(e3.test_date)
        FROM cdi_episodes e3
        WHERE e3.patient_id = e1.patient_id
          AND e3.test_date < e1.test_date
    )
ORDER BY e1.patient_mrn, e1.test_date;
