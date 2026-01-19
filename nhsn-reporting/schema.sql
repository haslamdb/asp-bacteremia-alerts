-- NHSN Reporting Module Database Schema
-- SQLite schema for HAI candidate tracking, classification, and reporting

-- NHSN Candidates (rule-based screening results)
CREATE TABLE IF NOT EXISTS nhsn_candidates (
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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hai_type, culture_id)
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_candidates_status ON nhsn_candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_patient ON nhsn_candidates(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_candidates_date ON nhsn_candidates(culture_date);
CREATE INDEX IF NOT EXISTS idx_candidates_hai_type ON nhsn_candidates(hai_type);

-- LLM Classifications
CREATE TABLE IF NOT EXISTS nhsn_classifications (
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
    FOREIGN KEY (candidate_id) REFERENCES nhsn_candidates(id)
);

CREATE INDEX IF NOT EXISTS idx_classifications_candidate ON nhsn_classifications(candidate_id);
CREATE INDEX IF NOT EXISTS idx_classifications_decision ON nhsn_classifications(decision);

-- IP Review Queue
CREATE TABLE IF NOT EXISTS nhsn_reviews (
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
    FOREIGN KEY (candidate_id) REFERENCES nhsn_candidates(id),
    FOREIGN KEY (classification_id) REFERENCES nhsn_classifications(id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_candidate ON nhsn_reviews(candidate_id);
CREATE INDEX IF NOT EXISTS idx_reviews_reviewed ON nhsn_reviews(reviewed);
CREATE INDEX IF NOT EXISTS idx_reviews_queue_type ON nhsn_reviews(queue_type);
CREATE INDEX IF NOT EXISTS idx_reviews_override ON nhsn_reviews(is_override);

-- Confirmed NHSN Events
CREATE TABLE IF NOT EXISTS nhsn_events (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    event_date DATE NOT NULL,
    hai_type TEXT NOT NULL,
    location_code TEXT,
    pathogen_code TEXT,
    reported BOOLEAN DEFAULT 0,
    reported_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (candidate_id) REFERENCES nhsn_candidates(id)
);

CREATE INDEX IF NOT EXISTS idx_events_date ON nhsn_events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_reported ON nhsn_events(reported);
CREATE INDEX IF NOT EXISTS idx_events_hai_type ON nhsn_events(hai_type);

-- LLM Audit Log
CREATE TABLE IF NOT EXISTS nhsn_llm_audit (
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

CREATE INDEX IF NOT EXISTS idx_llm_audit_candidate ON nhsn_llm_audit(candidate_id);
CREATE INDEX IF NOT EXISTS idx_llm_audit_model ON nhsn_llm_audit(model);

-- Statistics/Metrics view
CREATE VIEW IF NOT EXISTS nhsn_candidate_stats AS
SELECT
    hai_type,
    status,
    COUNT(*) as count,
    DATE(created_at) as date
FROM nhsn_candidates
GROUP BY hai_type, status, DATE(created_at);

-- Pending reviews view
-- Filters out resolved candidates (confirmed/rejected) to prevent stale reviews from appearing
CREATE VIEW IF NOT EXISTS nhsn_pending_reviews AS
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
FROM nhsn_reviews r
JOIN nhsn_candidates c ON r.candidate_id = c.id
LEFT JOIN nhsn_classifications cl ON r.classification_id = cl.id
WHERE r.reviewed = 0
  AND c.status IN ('pending_review', 'classified', 'pending')
ORDER BY r.created_at ASC;

-- IP Review Override Statistics
-- Tracks acceptance rate and override patterns for LLM quality assessment
CREATE VIEW IF NOT EXISTS nhsn_override_stats AS
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
FROM nhsn_reviews;

-- Detailed override history for analysis
CREATE VIEW IF NOT EXISTS nhsn_override_details AS
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
FROM nhsn_reviews r
JOIN nhsn_candidates c ON r.candidate_id = c.id
LEFT JOIN nhsn_classifications cl ON r.classification_id = cl.id
WHERE r.reviewed = 1
ORDER BY r.reviewed_at DESC;

-- Override breakdown by LLM decision type
CREATE VIEW IF NOT EXISTS nhsn_override_by_decision AS
SELECT
    llm_decision,
    COUNT(*) as total_cases,
    SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) as overrides,
    ROUND(
        100.0 * SUM(CASE WHEN is_override = 1 THEN 1 ELSE 0 END) / COUNT(*),
        1
    ) as override_rate_pct
FROM nhsn_reviews
WHERE reviewed = 1 AND llm_decision IS NOT NULL
GROUP BY llm_decision;

-- ============================================================
-- Denominator Tracking Tables
-- ============================================================

-- Daily denominator data (device days, patient days by location)
CREATE TABLE IF NOT EXISTS denominators_daily (
    id TEXT PRIMARY KEY,
    date DATE NOT NULL,
    location_code TEXT NOT NULL,  -- NHSN location code
    location_type TEXT,  -- ICU, Ward, NICU, etc.
    patient_days INTEGER DEFAULT 0,
    central_line_days INTEGER DEFAULT 0,
    urinary_catheter_days INTEGER DEFAULT 0,
    ventilator_days INTEGER DEFAULT 0,
    admissions INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, location_code)
);

CREATE INDEX IF NOT EXISTS idx_denominators_daily_date ON denominators_daily(date);
CREATE INDEX IF NOT EXISTS idx_denominators_daily_location ON denominators_daily(location_code);

-- Monthly aggregated denominators (for NHSN submission)
CREATE TABLE IF NOT EXISTS denominators_monthly (
    id TEXT PRIMARY KEY,
    month TEXT NOT NULL,  -- YYYY-MM format
    location_code TEXT NOT NULL,
    location_type TEXT,
    patient_days INTEGER DEFAULT 0,
    central_line_days INTEGER DEFAULT 0,
    urinary_catheter_days INTEGER DEFAULT 0,
    ventilator_days INTEGER DEFAULT 0,
    admissions INTEGER DEFAULT 0,
    -- Utilization ratios (calculated)
    central_line_utilization REAL,  -- central_line_days / patient_days
    urinary_catheter_utilization REAL,
    ventilator_utilization REAL,
    submitted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(month, location_code)
);

CREATE INDEX IF NOT EXISTS idx_denominators_monthly_month ON denominators_monthly(month);
CREATE INDEX IF NOT EXISTS idx_denominators_monthly_location ON denominators_monthly(location_code);

-- ============================================================
-- Antibiotic Usage (AU) Reporting Tables
-- ============================================================

-- Monthly AU summary by location (for NHSN AU module)
CREATE TABLE IF NOT EXISTS au_monthly_summary (
    id TEXT PRIMARY KEY,
    reporting_month TEXT NOT NULL,  -- YYYY-MM format
    location_code TEXT NOT NULL,  -- NHSN location code
    location_type TEXT,  -- ICU, Ward, NICU, etc.
    patient_days INTEGER NOT NULL,
    admissions INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP,
    UNIQUE(reporting_month, location_code)
);

CREATE INDEX IF NOT EXISTS idx_au_summary_month ON au_monthly_summary(reporting_month);
CREATE INDEX IF NOT EXISTS idx_au_summary_location ON au_monthly_summary(location_code);

-- Antimicrobial usage aggregates by drug
CREATE TABLE IF NOT EXISTS au_antimicrobial_usage (
    id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    antimicrobial_code TEXT NOT NULL,  -- NHSN antimicrobial code
    antimicrobial_name TEXT NOT NULL,
    antimicrobial_class TEXT,  -- e.g., carbapenem, glycopeptide, fluoroquinolone
    route TEXT NOT NULL,  -- IV, PO, IM
    days_of_therapy INTEGER NOT NULL,  -- DOT
    defined_daily_doses REAL,  -- DDD (optional, WHO-based)
    doses_administered INTEGER,
    patients_treated INTEGER,  -- Number of unique patients
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (summary_id) REFERENCES au_monthly_summary(id)
);

CREATE INDEX IF NOT EXISTS idx_au_usage_summary ON au_antimicrobial_usage(summary_id);
CREATE INDEX IF NOT EXISTS idx_au_usage_antimicrobial ON au_antimicrobial_usage(antimicrobial_code);

-- Patient-level antimicrobial data (for drill-down and validation)
CREATE TABLE IF NOT EXISTS au_patient_level (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    antimicrobial_code TEXT NOT NULL,
    antimicrobial_name TEXT NOT NULL,
    route TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    total_doses INTEGER,
    days_of_therapy INTEGER,
    location_code TEXT,
    indication TEXT,  -- Documented indication if available
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_au_patient_mrn ON au_patient_level(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_au_patient_encounter ON au_patient_level(encounter_id);
CREATE INDEX IF NOT EXISTS idx_au_patient_antimicrobial ON au_patient_level(antimicrobial_code);
CREATE INDEX IF NOT EXISTS idx_au_patient_dates ON au_patient_level(start_date, end_date);

-- ============================================================
-- Antimicrobial Resistance (AR) Reporting Tables
-- ============================================================

-- Quarterly AR summary by location (for NHSN AR module)
CREATE TABLE IF NOT EXISTS ar_quarterly_summary (
    id TEXT PRIMARY KEY,
    reporting_quarter TEXT NOT NULL,  -- YYYY-Q# format (e.g., 2024-Q1)
    location_code TEXT NOT NULL,
    location_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP,
    UNIQUE(reporting_quarter, location_code)
);

CREATE INDEX IF NOT EXISTS idx_ar_summary_quarter ON ar_quarterly_summary(reporting_quarter);
CREATE INDEX IF NOT EXISTS idx_ar_summary_location ON ar_quarterly_summary(location_code);

-- Individual isolates for AR reporting
CREATE TABLE IF NOT EXISTS ar_isolates (
    id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    patient_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    specimen_date DATE NOT NULL,
    specimen_type TEXT NOT NULL,  -- Blood, Urine, Respiratory, Wound, etc.
    specimen_source TEXT,  -- More specific source
    organism_code TEXT NOT NULL,  -- NHSN organism code
    organism_name TEXT NOT NULL,
    location_code TEXT,
    is_first_isolate INTEGER DEFAULT 1,  -- First isolate per patient per quarter (NHSN dedup)
    is_hai_associated INTEGER DEFAULT 0,  -- Associated with an HAI event
    hai_event_id TEXT,  -- Link to nhsn_events if HAI-associated
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (summary_id) REFERENCES ar_quarterly_summary(id)
);

CREATE INDEX IF NOT EXISTS idx_ar_isolates_summary ON ar_isolates(summary_id);
CREATE INDEX IF NOT EXISTS idx_ar_isolates_patient ON ar_isolates(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_ar_isolates_organism ON ar_isolates(organism_code);
CREATE INDEX IF NOT EXISTS idx_ar_isolates_specimen_date ON ar_isolates(specimen_date);
CREATE INDEX IF NOT EXISTS idx_ar_isolates_first ON ar_isolates(is_first_isolate);

-- Susceptibility results for each isolate
CREATE TABLE IF NOT EXISTS ar_susceptibilities (
    id TEXT PRIMARY KEY,
    isolate_id TEXT NOT NULL,
    antimicrobial_code TEXT NOT NULL,  -- NHSN antimicrobial code
    antimicrobial_name TEXT NOT NULL,
    interpretation TEXT NOT NULL,  -- S, I, R, NS (non-susceptible)
    mic_value TEXT,  -- MIC if available (e.g., "<=0.5", ">8")
    mic_numeric REAL,  -- Numeric MIC for calculations
    disk_zone INTEGER,  -- Disk diffusion zone in mm
    testing_method TEXT,  -- MIC, Disk, Vitek, Phoenix, etc.
    breakpoint_source TEXT,  -- CLSI, EUCAST
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (isolate_id) REFERENCES ar_isolates(id)
);

CREATE INDEX IF NOT EXISTS idx_ar_suscept_isolate ON ar_susceptibilities(isolate_id);
CREATE INDEX IF NOT EXISTS idx_ar_suscept_antimicrobial ON ar_susceptibilities(antimicrobial_code);
CREATE INDEX IF NOT EXISTS idx_ar_suscept_interpretation ON ar_susceptibilities(interpretation);

-- Phenotype summary (aggregated resistance patterns)
CREATE TABLE IF NOT EXISTS ar_phenotype_summary (
    id TEXT PRIMARY KEY,
    summary_id TEXT NOT NULL,
    organism_code TEXT NOT NULL,
    organism_name TEXT NOT NULL,
    phenotype TEXT NOT NULL,  -- MRSA, MSSA, VRE, VSE, ESBL, CRE, CRPA, etc.
    total_isolates INTEGER NOT NULL,
    resistant_isolates INTEGER NOT NULL,
    percent_resistant REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (summary_id) REFERENCES ar_quarterly_summary(id)
);

CREATE INDEX IF NOT EXISTS idx_ar_phenotype_summary ON ar_phenotype_summary(summary_id);
CREATE INDEX IF NOT EXISTS idx_ar_phenotype_organism ON ar_phenotype_summary(organism_code);
CREATE INDEX IF NOT EXISTS idx_ar_phenotype_type ON ar_phenotype_summary(phenotype);

-- ============================================================
-- AU/AR Reporting Views
-- ============================================================

-- AU summary by antimicrobial class
CREATE VIEW IF NOT EXISTS au_usage_by_class AS
SELECT
    s.reporting_month,
    s.location_code,
    s.location_type,
    u.antimicrobial_class,
    SUM(u.days_of_therapy) as total_dot,
    SUM(u.defined_daily_doses) as total_ddd,
    SUM(u.patients_treated) as total_patients,
    s.patient_days,
    ROUND(1000.0 * SUM(u.days_of_therapy) / NULLIF(s.patient_days, 0), 2) as dot_per_1000_pd
FROM au_monthly_summary s
JOIN au_antimicrobial_usage u ON s.id = u.summary_id
GROUP BY s.reporting_month, s.location_code, u.antimicrobial_class;

-- AR resistance rates by organism
CREATE VIEW IF NOT EXISTS ar_resistance_rates AS
SELECT
    s.reporting_quarter,
    s.location_code,
    p.organism_name,
    p.phenotype,
    p.total_isolates,
    p.resistant_isolates,
    p.percent_resistant
FROM ar_quarterly_summary s
JOIN ar_phenotype_summary p ON s.id = p.summary_id
ORDER BY s.reporting_quarter DESC, p.organism_name;

-- Combined HAI rates with denominators
CREATE VIEW IF NOT EXISTS hai_rates_monthly AS
SELECT
    d.month,
    d.location_code,
    d.location_type,
    d.patient_days,
    d.central_line_days,
    d.urinary_catheter_days,
    d.ventilator_days,
    -- CLABSI
    (SELECT COUNT(*) FROM nhsn_events e
     WHERE e.hai_type = 'clabsi'
     AND strftime('%Y-%m', e.event_date) = d.month
     AND e.location_code = d.location_code) as clabsi_count,
    -- CAUTI
    (SELECT COUNT(*) FROM nhsn_events e
     WHERE e.hai_type = 'cauti'
     AND strftime('%Y-%m', e.event_date) = d.month
     AND e.location_code = d.location_code) as cauti_count,
    -- VAE
    (SELECT COUNT(*) FROM nhsn_events e
     WHERE e.hai_type = 'vae'
     AND strftime('%Y-%m', e.event_date) = d.month
     AND e.location_code = d.location_code) as vae_count,
    -- Rates per 1000 device days
    ROUND(1000.0 * (SELECT COUNT(*) FROM nhsn_events e
     WHERE e.hai_type = 'clabsi'
     AND strftime('%Y-%m', e.event_date) = d.month
     AND e.location_code = d.location_code) / NULLIF(d.central_line_days, 0), 2) as clabsi_rate,
    ROUND(1000.0 * (SELECT COUNT(*) FROM nhsn_events e
     WHERE e.hai_type = 'cauti'
     AND strftime('%Y-%m', e.event_date) = d.month
     AND e.location_code = d.location_code) / NULLIF(d.urinary_catheter_days, 0), 2) as cauti_rate,
    ROUND(1000.0 * (SELECT COUNT(*) FROM nhsn_events e
     WHERE e.hai_type = 'vae'
     AND strftime('%Y-%m', e.event_date) = d.month
     AND e.location_code = d.location_code) / NULLIF(d.ventilator_days, 0), 2) as vae_rate
FROM denominators_monthly d;
