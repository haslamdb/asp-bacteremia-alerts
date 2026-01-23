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
