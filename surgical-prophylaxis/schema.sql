-- Surgical Prophylaxis Module Database Schema
-- SQLite implementation for tracking evaluations and alerts

-- Surgical cases table
CREATE TABLE IF NOT EXISTS surgical_cases (
    case_id TEXT PRIMARY KEY,
    patient_mrn TEXT NOT NULL,
    encounter_id TEXT NOT NULL,

    -- Procedure info
    primary_cpt TEXT,
    all_cpt_codes TEXT,  -- JSON array
    procedure_description TEXT,
    procedure_category TEXT,
    surgeon_id TEXT,
    surgeon_name TEXT,
    location TEXT,

    -- Timing
    scheduled_or_time TIMESTAMP,
    actual_incision_time TIMESTAMP,
    surgery_end_time TIMESTAMP,

    -- Patient factors
    patient_weight_kg REAL,
    patient_age_years REAL,
    has_beta_lactam_allergy BOOLEAN DEFAULT FALSE,
    mrsa_colonized BOOLEAN DEFAULT FALSE,
    allergies TEXT,  -- JSON array

    -- Exclusion flags
    is_emergency BOOLEAN DEFAULT FALSE,
    already_on_therapeutic_antibiotics BOOLEAN DEFAULT FALSE,
    documented_infection BOOLEAN DEFAULT FALSE,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prophylaxis evaluations table
CREATE TABLE IF NOT EXISTS prophylaxis_evaluations (
    evaluation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES surgical_cases(case_id),
    evaluation_time TIMESTAMP NOT NULL,

    -- Element compliance (status values: 'met', 'not_met', 'pending', 'n/a', 'unable')
    indication_status TEXT,
    indication_details TEXT,
    agent_status TEXT,
    agent_details TEXT,
    timing_status TEXT,
    timing_details TEXT,
    dosing_status TEXT,
    dosing_details TEXT,
    redosing_status TEXT,
    redosing_details TEXT,
    discontinuation_status TEXT,
    discontinuation_details TEXT,

    -- Summary
    bundle_compliant BOOLEAN,
    compliance_score REAL,
    elements_met INTEGER,
    elements_total INTEGER,

    -- Flags and recommendations (JSON arrays)
    flags TEXT,
    recommendations TEXT,

    -- Exclusion tracking
    excluded BOOLEAN DEFAULT FALSE,
    exclusion_reason TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Prophylaxis alerts table
CREATE TABLE IF NOT EXISTS prophylaxis_alerts (
    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES surgical_cases(case_id),
    evaluation_id INTEGER REFERENCES prophylaxis_evaluations(evaluation_id),

    alert_type TEXT NOT NULL,  -- 'missing_order', 'timing_risk', 'agent_mismatch', 'prolonged_duration', etc.
    alert_severity TEXT NOT NULL,  -- 'high', 'medium', 'low'
    alert_message TEXT,
    element_name TEXT,  -- Which element triggered the alert

    -- Timing
    alert_time TIMESTAMP NOT NULL,
    response_time TIMESTAMP,

    -- Response
    response_action TEXT,  -- 'acknowledged', 'overridden', 'corrected', 'resolved'
    override_reason TEXT,
    responder_id TEXT,
    responder_name TEXT,

    -- Outcome
    prophylaxis_ultimately_given BOOLEAN,
    timing_ultimately_appropriate BOOLEAN,

    -- Integration
    external_alert_id TEXT,  -- Reference to alert in common alert_store

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Medication orders for prophylaxis
CREATE TABLE IF NOT EXISTS prophylaxis_orders (
    order_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES surgical_cases(case_id),
    medication_name TEXT NOT NULL,
    dose_mg REAL,
    route TEXT,
    ordered_time TIMESTAMP NOT NULL,
    frequency TEXT,
    duration_hours REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Medication administrations for prophylaxis
CREATE TABLE IF NOT EXISTS prophylaxis_administrations (
    admin_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES surgical_cases(case_id),
    order_id TEXT REFERENCES prophylaxis_orders(order_id),
    medication_name TEXT NOT NULL,
    dose_mg REAL,
    route TEXT,
    admin_time TIMESTAMP NOT NULL,
    infusion_end_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Compliance metrics aggregates (for dashboard)
CREATE TABLE IF NOT EXISTS compliance_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    period_type TEXT NOT NULL,  -- 'daily', 'weekly', 'monthly', 'quarterly'

    -- Filter dimensions (NULL = all)
    procedure_category TEXT,
    surgeon_id TEXT,
    location TEXT,

    -- Counts
    total_cases INTEGER,
    excluded_cases INTEGER,

    -- Bundle compliance
    bundle_compliant_count INTEGER,
    bundle_compliance_rate REAL,

    -- Element-level compliance
    indication_met_count INTEGER,
    indication_rate REAL,
    agent_met_count INTEGER,
    agent_rate REAL,
    timing_met_count INTEGER,
    timing_rate REAL,
    dosing_met_count INTEGER,
    dosing_rate REAL,
    redosing_met_count INTEGER,
    redosing_rate REAL,
    discontinuation_met_count INTEGER,
    discontinuation_rate REAL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_cases_encounter ON surgical_cases(encounter_id);
CREATE INDEX IF NOT EXISTS idx_cases_mrn ON surgical_cases(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_cases_scheduled ON surgical_cases(scheduled_or_time);
CREATE INDEX IF NOT EXISTS idx_cases_category ON surgical_cases(procedure_category);

CREATE INDEX IF NOT EXISTS idx_evals_case ON prophylaxis_evaluations(case_id);
CREATE INDEX IF NOT EXISTS idx_evals_time ON prophylaxis_evaluations(evaluation_time);
CREATE INDEX IF NOT EXISTS idx_evals_compliant ON prophylaxis_evaluations(bundle_compliant);

CREATE INDEX IF NOT EXISTS idx_alerts_case ON prophylaxis_alerts(case_id);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON prophylaxis_alerts(alert_time);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON prophylaxis_alerts(alert_severity);

CREATE INDEX IF NOT EXISTS idx_orders_case ON prophylaxis_orders(case_id);
CREATE INDEX IF NOT EXISTS idx_admins_case ON prophylaxis_administrations(case_id);

CREATE INDEX IF NOT EXISTS idx_metrics_period ON compliance_metrics(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_metrics_category ON compliance_metrics(procedure_category);
