# AEGIS Surgical Antimicrobial Prophylaxis Module

Real-time and retrospective monitoring of surgical antimicrobial prophylaxis compliance based on ASHP/IDSA/SHEA/SIS 2013 guidelines and local CCHMC protocols (v2024.2, September 2024).

## Overview

The Surgical Prophylaxis module evaluates surgical cases for adherence to evidence-based prophylaxis guidelines, tracking seven key bundle elements:

1. **Indication Appropriate** - Prophylaxis given (or withheld) appropriately for the procedure
2. **Agent Selection** - Correct antibiotic(s) for the procedure type and patient allergies
3. **Pre-op Timing** - Administered within 60 min of incision (120 min for vancomycin)
4. **Weight-Based Dosing** - Appropriate dose for patient weight
5. **Intraoperative Redosing** - Redose given for prolonged surgery (Q3H for cefazolin)
6. **Post-op Continuation** - Appropriate post-operative prophylaxis when required (or stopped when not)
7. **Timely Discontinuation** - Stopped within 24h (48h for cardiac)

## Features

### Retrospective Monitoring
- Evaluate completed cases for compliance metrics
- Alert generation for non-compliant cases via ASP Alerts queue
- Compliance dashboard for tracking bundle and element-level compliance
- CPT-based evaluation with automatic determination of prophylaxis requirements

### Real-Time Pre-Operative Alerting (NEW)
- Track patients through surgical workflow before incision
- Proactive alerts at T-24h, T-2h, T-60m, and T-0 (OR entry)
- HL7 ADT integration for location-based triggers
- FHIR Appointment polling for schedule awareness
- Automatic escalation to anesthesia, surgeon, and ASP
- Epic Secure Chat and Teams integration

---

## Quick Start

### Retrospective Monitoring

```bash
cd /home/david/projects/aegis/surgical-prophylaxis

# Run once (evaluate recent cases)
python -m src.runner --once --verbose

# Dry run (no alerts)
python -m src.runner --once --dry-run

# Look back 48 hours
python -m src.runner --once --hours 48
```

### Real-Time Monitoring Service

```bash
# Start real-time monitoring service
python -m src.realtime.service

# With debug logging
python -m src.realtime.service --debug
```

---

## Module Structure

```
surgical-prophylaxis/
├── src/
│   ├── __init__.py
│   ├── config.py              # Configuration, guidelines loading
│   ├── models.py              # Data classes (SurgicalCase, Evaluation, etc.)
│   ├── evaluator.py           # Core compliance evaluation logic
│   ├── database.py            # SQLite database operations
│   ├── fhir_client.py         # FHIR data access
│   ├── monitor.py             # Retrospective monitor class
│   ├── runner.py              # CLI entry point
│   └── realtime/              # Real-time monitoring (NEW)
│       ├── __init__.py
│       ├── hl7_parser.py      # HL7 v2.x message parsing
│       ├── hl7_listener.py    # MLLP server for ADT/ORM
│       ├── location_tracker.py # Patient location state machine
│       ├── schedule_monitor.py # FHIR Appointment polling
│       ├── preop_checker.py   # Real-time compliance checking
│       ├── escalation_engine.py # Time-based alert routing
│       ├── state_manager.py   # Journey coordination
│       ├── epic_chat.py       # Epic Secure Chat integration
│       └── service.py         # Main orchestrator
├── data/
│   └── cchmc_surgical_prophylaxis_guidelines.json
├── schema.sql                 # Retrospective database schema
├── schema_realtime.sql        # Real-time monitoring schema (NEW)
└── README.md
```

---

## Real-Time Monitoring

### Data Sources

| Source | Purpose | Availability |
|--------|---------|--------------|
| **FHIR Appointment** | OR schedule (primary) | Poll every 15 min |
| **HL7 ADT A02** | Patient location tracking | Real-time via MLLP |
| **HL7 ORM O01** | OR scheduling (backup) | Real-time via MLLP |
| **FHIR MedicationRequest** | Prophylaxis orders | Poll every 5 min |
| **FHIR MedicationAdministration** | Actual doses given | Poll every 5 min |

### Alert Trigger Points

| Trigger | Timing | Primary Recipient | Escalation |
|---------|--------|-------------------|------------|
| T-24h | Surgery scheduled | Pre-op Pharmacy | None (informational) |
| T-2h | Patient in pre-op | Pre-op RN | Anesthesia (30 min) |
| T-60m | Approaching OR | Anesthesiologist | Surgeon (15 min) |
| T-0 | Entering OR | Anesthesia + Surgeon | ASP Critical (5 min) |

### Patient Location State Machine

```
UNKNOWN ─→ INPATIENT ─→ PRE_OP_HOLDING ─→ OR_SUITE ─→ PACU ─→ DISCHARGED
                            │                │
                            └── triggers ────┴── triggers
                                T-2h check       T-0 CRITICAL check
```

### Delivery Channels

1. **Epic Secure Chat** - Direct InBasket messages with action links
2. **Microsoft Teams** - Webhook notifications (fallback)
3. **Dashboard** - ASP Alerts queue for review
4. **Pager** - Critical T-0 alerts (if configured)

### Configuration

```bash
# HL7 Listener
HL7_ENABLED=true
HL7_LISTENER_HOST=0.0.0.0
HL7_LISTENER_PORT=2575

# FHIR Polling
FHIR_SCHEDULE_POLL_INTERVAL=15   # minutes
FHIR_PROPHYLAXIS_POLL_INTERVAL=5  # minutes
FHIR_LOOKAHEAD_HOURS=48

# Epic Secure Chat
EPIC_CHAT_ENABLED=true
EPIC_CHAT_CLIENT_ID=your-client-id
EPIC_CHAT_PRIVATE_KEY_PATH=/path/to/key.pem
EPIC_FHIR_BASE_URL=https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4

# Teams Fallback
TEAMS_SURGICAL_PROPHYLAXIS_WEBHOOK=https://...
TEAMS_FALLBACK_ENABLED=true

# Location Patterns (comma-separated)
LOCATION_PREOP_PATTERNS=PREOP,PHOLD,PRE-OP,SURG PREP,SDS,ASC
LOCATION_OR_PATTERNS=OR,OPER,SURG SUITE,THEATER,CATH LAB
LOCATION_PACU_PATTERNS=PACU,RECOVERY,POST ANES

# Alert Thresholds
ALERT_T24_ENABLED=true
ALERT_T2_ENABLED=true
ALERT_T60_ENABLED=true
ALERT_T0_ENABLED=true

# Escalation Delays (minutes)
ESCALATION_PREOP_DELAY=30
ESCALATION_T60_DELAY=15
ESCALATION_T0_DELAY=5
```

---

## Procedure Coverage (310+ CPT codes)

| Specialty | Example Procedures | Primary Agent | Post-op |
|-----------|-------------------|---------------|---------|
| **Cardiac** | VSD repair, valve replacement, CABG | Cefazolin | Optional (up to 48h) |
| **Thoracic** | Lobectomy, VATS | Cefazolin | No |
| **General Surgery** | Appendectomy, colectomy, hernia | Cefoxitin or Ceftriaxone+Metro | Perforated appy: 24h |
| **Hepatobiliary** | Cholecystectomy (high-risk/open) | Cefazolin | No |
| **Urology** | Pyeloplasty, nephrectomy | Cefazolin | No |
| **Orthopedic** | Spinal fusion, ORIF | Cefazolin | No |
| **Neurosurgery** | Craniotomy, VP shunt | Cefazolin | No |
| **ENT** | Cochlear implant, LTP, FESS | Ampicillin-sulbactam | No |
| **Plastics** | Cleft lip/palate, craniosynostosis | Cefazolin or Amp-sulbactam | No |

---

## Bundle Elements

### 1. Indication Appropriate

| Scenario | Compliant? |
|----------|------------|
| Prophylaxis given for procedure that requires it | ✓ |
| Prophylaxis withheld for procedure that doesn't require it | ✓ |
| Prophylaxis NOT given for procedure that requires it | ✗ |
| Prophylaxis given for procedure that doesn't require it | ✗ |

### 2. Agent Selection

| Procedure Type | First-Line | Alternative (β-lactam allergy) |
|----------------|------------|--------------------------------|
| Cardiac | Cefazolin | Clindamycin |
| Colorectal/Small Bowel | Cefoxitin | Clindamycin + Gentamicin |
| Appendectomy | Ceftriaxone + Metronidazole | Clindamycin + Gentamicin |
| Orthopedic | Cefazolin | Clindamycin or Vancomycin |
| Neurosurgery | Cefazolin | Clindamycin or Vancomycin |
| ENT | Ampicillin-sulbactam | Clindamycin |
| Hernia/Pectus | Cefazolin | Clindamycin |

**Note:** Cefazolin is safe to give to patients with ANY severity of penicillin allergy per current cross-reactivity evidence.

### 3. Pre-op Timing

Only checks doses given **before incision**. Post-operative and intra-operative doses are evaluated separately.

| Antibiotic | Window Before Incision |
|------------|------------------------|
| Cefazolin, Cefoxitin, Clindamycin | 60 min |
| Vancomycin, Fluoroquinolones | 120 min |

### 4. Weight-Based Dosing

| Agent | Dose | Max | High-Weight (>100kg) |
|-------|------|-----|----------------------|
| Cefazolin | 40 mg/kg | 2g | 3g |
| Cefoxitin | 40 mg/kg | 2g | 2g |
| Ceftriaxone | 50 mg/kg | 2g | 2g |
| Vancomycin | 15 mg/kg | Consult Pharmacy | - |
| Clindamycin | 10 mg/kg | 900mg | 900mg |
| Metronidazole | 15 mg/kg (30 mg/kg for appy) | 1000mg (1500mg) | - |
| Gentamicin | 4.5 mg/kg | 160mg (<40kg) / 360mg (≥40kg) | - |

### 5. Redosing Intervals (Intra-op)

Intervals based on normal GFR (>60). Extend intervals for renal impairment.

| Agent | Interval |
|-------|----------|
| Cefazolin | Q3H |
| Cefoxitin | Q3H |
| Ceftriaxone | Q12H |
| Ampicillin-sulbactam | Q2H |
| Piperacillin-tazobactam | Q2H |
| Clindamycin | Q6H |
| Vancomycin | Q8H |
| Metronidazole | Q12H |

### 6. Post-op Continuation

| Procedure Type | Post-op Required? | Duration |
|----------------|-------------------|----------|
| Perforated appendectomy | **Yes** | 24h Q24H |
| Cardiac surgery | Optional | Up to 48h |
| All other procedures | **No** | Stop after surgery |

### 7. Duration Limits

| Procedure Type | Maximum Duration |
|----------------|------------------|
| Cardiac surgery | 48 hours |
| All others | 24 hours |

---

## Alert Types

Alerts are created in the ASP Alerts queue with type `surgical_prophylaxis`:

### Retrospective Alerts
- **Critical**: Missing prophylaxis for indicated procedure, antibiotics given after incision
- **Warning**: Wrong agent, timing outside window, incorrect dosing
- **Info**: Prolonged duration, missing redosing

### Real-Time Alerts
- **Critical (T-0)**: Patient entering OR without prophylaxis - immediate action required
- **Warning (T-2h/T-60m)**: Prophylaxis not ordered, surgery approaching
- **Info (T-24h)**: Surgery scheduled tomorrow, consider ordering prophylaxis

---

## Database Schema

### Retrospective Tables (`schema.sql`)

- `surgical_cases` - Surgical case information
- `prophylaxis_evaluations` - Compliance evaluation results
- `prophylaxis_alerts` - Alert tracking
- `prophylaxis_orders` - Medication orders
- `prophylaxis_administrations` - Medication administrations
- `compliance_metrics` - Aggregated metrics

### Real-Time Tables (`schema_realtime.sql`)

- `surgical_journeys` - Patient journey through surgical workflow
- `patient_locations` - Location history from ADT messages
- `preop_checks` - Pre-op compliance check results
- `alert_escalations` - Escalation tracking
- `scheduled_surgeries` - Upcoming surgery queue
- `epic_chat_messages` - Epic Secure Chat tracking

---

## Integration with AEGIS

The module integrates with:

- **Common Alert Store**: Alerts appear in ASP Alerts dashboard
- **Dashboard**: Compliance metrics visible at `/surgical-prophylaxis/`
- **Teams Notifications**: Alerts can trigger Teams webhooks
- **Epic Secure Chat**: Direct provider messaging with order links

---

## Exclusion Criteria

Cases are excluded from compliance measurement if:

- Emergency surgery (timing may not be achievable)
- Patient already on therapeutic antibiotics
- Documented active infection
- Incomplete data

---

## Testing

### Unit Tests

```bash
cd surgical-prophylaxis
python -m pytest tests/

# Specific test files
python -m pytest tests/test_location_tracker.py
python -m pytest tests/test_preop_checker.py
python -m pytest tests/test_escalation.py
```

### Integration Test (Real-Time)

```bash
# Start real-time service
python -m src.realtime.service --debug

# In another terminal - send mock ADT message
python -c "
import asyncio
from src.realtime.hl7_listener import HL7TestClient

async def test():
    client = HL7TestClient('localhost', 2575)
    ack = await client.send_adt_a02(
        patient_mrn='12345',
        patient_name='DOE^JOHN',
        current_location='PREOP-01',
    )
    print(f'ACK: {ack}')

asyncio.run(test())
"
```

### Manual Verification

1. Check Teams channel receives test alert
2. Verify dashboard shows active surgical journeys
3. Confirm escalation fires after timeout
4. Test Epic Secure Chat (when credentials available)

---

## Troubleshooting

### HL7 Listener Not Receiving Messages

1. Check port 2575 is open: `netstat -tlnp | grep 2575`
2. Verify `HL7_ENABLED=true` in environment
3. Check firewall rules allow inbound TCP on the port
4. Test with `telnet localhost 2575`

### FHIR Polling Not Working

1. Verify `FHIR_BASE_URL` is correct
2. Check `FHIR_AUTH_TOKEN` if authentication required
3. Test FHIR connection: `curl $FHIR_BASE_URL/metadata`

### Epic Chat Authentication Failing

1. Verify private key path exists and is readable
2. Check client ID is correct
3. Confirm token endpoint URL
4. Check JWT library is installed: `pip install pyjwt`

### Alerts Not Escalating

1. Check escalation monitor is running (see service logs)
2. Verify escalation delays in config
3. Check alert_escalations table for pending records

---

## References

1. ASHP/IDSA/SHEA/SIS. Clinical Practice Guidelines for Antimicrobial Prophylaxis in Surgery. 2013.
2. Bratzler DW, et al. Clinical practice guidelines for antimicrobial prophylaxis in surgery. Am J Health Syst Pharm. 2013.
3. Joint Commission MM.09.01.01 - Antimicrobial Stewardship Standard
4. CMS SCIP Measures

---

## Changelog

### v2.0.0 (January 2025)
- **Added**: Real-time pre-operative alerting system
- **Added**: HL7 MLLP listener for ADT/ORM messages
- **Added**: Patient location state machine
- **Added**: FHIR Appointment schedule polling
- **Added**: Escalation engine with automatic escalation
- **Added**: Epic Secure Chat integration
- **Added**: Teams webhook fallback
- **Added**: Real-time database schema

### v1.0.0 (September 2024)
- Initial release with retrospective monitoring
- Bundle compliance evaluation (7 elements)
- FHIR integration for surgical cases
- Alert generation and dashboard
