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
    cl.decision,
    cl.confidence,
    cl.reasoning
FROM nhsn_reviews r
JOIN nhsn_candidates c ON r.candidate_id = c.id
LEFT JOIN nhsn_classifications cl ON r.classification_id = cl.id
WHERE r.reviewed = 0
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
