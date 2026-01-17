-- Alert storage schema for ASP Alerts
-- SQLite database for persistent alert tracking

-- Main alerts table
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    severity TEXT NOT NULL DEFAULT 'warning',

    -- Patient information
    patient_id TEXT,
    patient_mrn TEXT,
    patient_name TEXT,

    -- Alert content
    title TEXT,
    summary TEXT,
    content TEXT,  -- JSON blob for additional data

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    acknowledged_at TIMESTAMP,
    acknowledged_by TEXT,
    resolved_at TIMESTAMP,
    resolved_by TEXT,
    resolution_reason TEXT,  -- How the alert was handled
    snoozed_until TIMESTAMP,

    -- Notes for follow-up
    notes TEXT,

    -- Ensure we don't duplicate alerts for the same source
    UNIQUE(alert_type, source_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
CREATE INDEX IF NOT EXISTS idx_alerts_type ON alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_patient_mrn ON alerts(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_type_source ON alerts(alert_type, source_id);

-- Audit trail for compliance
CREATE TABLE IF NOT EXISTS alert_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    action TEXT NOT NULL,
    performed_by TEXT,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details TEXT,

    FOREIGN KEY (alert_id) REFERENCES alerts(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_alert_id ON alert_audit(alert_id);
CREATE INDEX IF NOT EXISTS idx_audit_performed_at ON alert_audit(performed_at);
