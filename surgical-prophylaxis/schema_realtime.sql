-- Real-time surgical prophylaxis monitoring schema extensions
-- Extends the base schema with tables for real-time journey tracking

-- Surgical journey tracking (patient's path through surgical workflow)
CREATE TABLE IF NOT EXISTS surgical_journeys (
    journey_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    patient_mrn TEXT NOT NULL,
    patient_name TEXT,
    procedure_description TEXT,
    procedure_cpt_codes TEXT,  -- JSON array
    scheduled_time TEXT,       -- ISO timestamp
    current_state TEXT NOT NULL DEFAULT 'unknown',  -- LocationState enum value

    -- Prophylaxis status
    prophylaxis_indicated BOOLEAN,
    order_exists BOOLEAN DEFAULT FALSE,
    administered BOOLEAN DEFAULT FALSE,

    -- Alert tracking (which alerts have been sent for this journey)
    alert_t24_sent BOOLEAN DEFAULT FALSE,
    alert_t24_time TEXT,
    alert_t2_sent BOOLEAN DEFAULT FALSE,
    alert_t2_time TEXT,
    alert_t60_sent BOOLEAN DEFAULT FALSE,
    alert_t60_time TEXT,
    alert_t0_sent BOOLEAN DEFAULT FALSE,
    alert_t0_time TEXT,

    -- Journey status
    is_emergency BOOLEAN DEFAULT FALSE,
    already_on_therapeutic_abx BOOLEAN DEFAULT FALSE,
    excluded BOOLEAN DEFAULT FALSE,
    exclusion_reason TEXT,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,

    -- FHIR/HL7 references
    fhir_appointment_id TEXT,
    fhir_encounter_id TEXT,
    hl7_visit_number TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_journeys_patient_mrn ON surgical_journeys(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_journeys_scheduled_time ON surgical_journeys(scheduled_time);
CREATE INDEX IF NOT EXISTS idx_journeys_current_state ON surgical_journeys(current_state);
CREATE INDEX IF NOT EXISTS idx_journeys_case_id ON surgical_journeys(case_id);
CREATE INDEX IF NOT EXISTS idx_journeys_active ON surgical_journeys(completed_at) WHERE completed_at IS NULL;

-- Patient location history (from ADT messages)
CREATE TABLE IF NOT EXISTS patient_locations (
    location_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_mrn TEXT NOT NULL,
    journey_id TEXT REFERENCES surgical_journeys(journey_id),

    -- Location info
    location_code TEXT NOT NULL,      -- Raw location code from ADT
    location_description TEXT,
    location_state TEXT NOT NULL,     -- Mapped LocationState enum value

    -- Event details
    event_time TEXT NOT NULL,         -- When the location change occurred
    message_time TEXT,                -- When the message was received
    hl7_message_id TEXT,              -- Original HL7 message control ID

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for location queries
CREATE INDEX IF NOT EXISTS idx_locations_patient_mrn ON patient_locations(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_locations_journey_id ON patient_locations(journey_id);
CREATE INDEX IF NOT EXISTS idx_locations_event_time ON patient_locations(event_time);

-- Pre-op compliance check results
CREATE TABLE IF NOT EXISTS preop_checks (
    check_id INTEGER PRIMARY KEY AUTOINCREMENT,
    journey_id TEXT NOT NULL REFERENCES surgical_journeys(journey_id),

    -- Trigger info
    trigger_type TEXT NOT NULL,       -- 't24', 't2', 't60', 't0'
    trigger_time TEXT NOT NULL,

    -- Check results
    prophylaxis_indicated BOOLEAN,
    order_exists BOOLEAN,
    administered BOOLEAN,
    minutes_to_or INTEGER,

    -- Alert decision
    alert_required BOOLEAN NOT NULL,
    alert_severity TEXT,              -- 'info', 'warning', 'critical'
    recommendation TEXT,

    -- Alert reference (if sent)
    alert_id TEXT,                    -- Reference to common alert_store

    -- Additional info
    therapeutic_abx_active BOOLEAN DEFAULT FALSE,
    check_details TEXT,               -- JSON with additional details

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for preop checks
CREATE INDEX IF NOT EXISTS idx_preop_checks_journey_id ON preop_checks(journey_id);
CREATE INDEX IF NOT EXISTS idx_preop_checks_trigger_type ON preop_checks(trigger_type);
CREATE INDEX IF NOT EXISTS idx_preop_checks_alert_required ON preop_checks(alert_required);

-- Alert escalation tracking
CREATE TABLE IF NOT EXISTS alert_escalations (
    escalation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,           -- Reference to common alert_store
    journey_id TEXT REFERENCES surgical_journeys(journey_id),

    -- Escalation info
    escalation_level INTEGER DEFAULT 1,
    trigger_type TEXT NOT NULL,       -- Original trigger ('t24', 't2', 't60', 't0')
    recipient_role TEXT NOT NULL,     -- 'preop_rn', 'anesthesia', 'surgeon', 'asp'
    recipient_id TEXT,                -- Provider ID if known
    recipient_name TEXT,

    -- Delivery
    delivery_channel TEXT NOT NULL,   -- 'epic_chat', 'teams', 'page', 'dashboard'
    sent_at TEXT NOT NULL,
    delivery_status TEXT DEFAULT 'sent',  -- 'sent', 'delivered', 'failed'
    error_message TEXT,

    -- Response tracking
    response_at TEXT,
    response_action TEXT,             -- 'acknowledged', 'order_placed', 'override'
    response_by TEXT,
    response_notes TEXT,

    -- Next escalation
    next_escalation_at TEXT,          -- When to escalate if no response
    escalated BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for escalation tracking
CREATE INDEX IF NOT EXISTS idx_escalations_alert_id ON alert_escalations(alert_id);
CREATE INDEX IF NOT EXISTS idx_escalations_journey_id ON alert_escalations(journey_id);
CREATE INDEX IF NOT EXISTS idx_escalations_pending ON alert_escalations(next_escalation_at)
    WHERE response_at IS NULL AND escalated = FALSE;

-- Scheduled surgery queue (from FHIR Appointment polling)
CREATE TABLE IF NOT EXISTS scheduled_surgeries (
    schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL UNIQUE,
    patient_mrn TEXT NOT NULL,
    patient_name TEXT,

    -- Procedure info
    procedure_description TEXT,
    procedure_cpt_codes TEXT,         -- JSON array
    scheduled_time TEXT NOT NULL,
    estimated_duration_minutes INTEGER,
    or_location TEXT,

    -- Staff
    surgeon_id TEXT,
    surgeon_name TEXT,
    anesthesiologist_id TEXT,
    anesthesiologist_name TEXT,

    -- Prophylaxis status
    prophylaxis_indicated BOOLEAN,
    prophylaxis_requirements TEXT,    -- JSON with agent recommendations

    -- Processing status
    journey_created BOOLEAN DEFAULT FALSE,
    journey_id TEXT REFERENCES surgical_journeys(journey_id),

    -- Source tracking
    source TEXT NOT NULL,             -- 'fhir_appointment', 'hl7_orm', 'manual'
    fhir_appointment_id TEXT,
    hl7_message_id TEXT,

    -- Timestamps
    first_seen_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for scheduled surgeries
CREATE INDEX IF NOT EXISTS idx_scheduled_patient_mrn ON scheduled_surgeries(patient_mrn);
CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_surgeries(scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled_pending ON scheduled_surgeries(journey_created)
    WHERE journey_created = FALSE;

-- Epic Secure Chat message tracking
CREATE TABLE IF NOT EXISTS epic_chat_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id TEXT NOT NULL,
    journey_id TEXT REFERENCES surgical_journeys(journey_id),

    -- Message details
    fhir_communication_id TEXT,       -- ID from Epic
    recipient_provider_id TEXT NOT NULL,
    recipient_name TEXT,
    subject TEXT NOT NULL,
    message_body TEXT NOT NULL,

    -- Action links included
    action_links TEXT,                -- JSON array of deep links

    -- Status
    sent_at TEXT NOT NULL,
    delivery_status TEXT DEFAULT 'pending',
    error_message TEXT,

    -- Response
    read_at TEXT,
    responded_at TEXT,
    response_action TEXT,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for Epic chat
CREATE INDEX IF NOT EXISTS idx_epic_chat_alert_id ON epic_chat_messages(alert_id);
CREATE INDEX IF NOT EXISTS idx_epic_chat_journey_id ON epic_chat_messages(journey_id);
