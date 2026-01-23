-- NHSN Reporting Module Database Schema
-- SQLite schema for NHSN submission and AU/AR reporting

-- Note: HAI candidate detection tables (hai_candidates, hai_classifications, hai_reviews)
-- are defined in the hai-detection module schema. Both modules use the same database.

-- ============================================================
-- NHSN Event Tables (Confirmed HAIs for Submission)
-- ============================================================

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_date ON nhsn_events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_reported ON nhsn_events(reported);
CREATE INDEX IF NOT EXISTS idx_events_hai_type ON nhsn_events(hai_type);

-- NHSN Submission Audit Log
CREATE TABLE IF NOT EXISTS nhsn_submission_audit (
    id TEXT PRIMARY KEY,
    submission_date TIMESTAMP NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    event_count INTEGER NOT NULL,
    events_submitted TEXT,  -- JSON array of event IDs
    method TEXT NOT NULL,  -- 'direct', 'manual', 'cda_export'
    status TEXT NOT NULL,  -- 'pending', 'success', 'failed'
    error_message TEXT,
    submitted_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_submission_date ON nhsn_submission_audit(submission_date);
CREATE INDEX IF NOT EXISTS idx_submission_status ON nhsn_submission_audit(status);

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
