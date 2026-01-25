# AEGIS Surgical Antimicrobial Prophylaxis Module

Real-time monitoring of surgical antimicrobial prophylaxis compliance based on ASHP/IDSA/SHEA/SIS 2013 guidelines and local CCHMC protocols.

## Overview

The Surgical Prophylaxis module evaluates surgical cases for adherence to evidence-based prophylaxis guidelines, tracking six key bundle elements:

1. **Indication Appropriate** - Prophylaxis given (or withheld) appropriately for the procedure
2. **Agent Selection** - Correct antibiotic(s) for the procedure type and patient allergies
3. **Timing** - Administered within 60 min of incision (120 min for vancomycin)
4. **Weight-Based Dosing** - Appropriate dose for patient weight
5. **Intraoperative Redosing** - Redose given for prolonged surgery (>4h for cefazolin)
6. **Timely Discontinuation** - Stopped within 24h (48h for cardiac)

## Features

- **Retrospective Monitoring**: Evaluate completed cases for compliance metrics
- **Alert Generation**: Create alerts for non-compliant cases via ASP Alerts queue
- **Compliance Dashboard**: Track bundle and element-level compliance over time
- **CPT-Based Evaluation**: Automatically determine prophylaxis requirements from CPT codes
- **Allergy-Aware**: Recommend alternative agents for beta-lactam allergies
- **MRSA Screening**: Consider vancomycin addition for colonized patients

## Quick Start

```bash
cd /home/david/projects/aegis/surgical-prophylaxis

# Run once (evaluate recent cases)
python -m src.runner --once --verbose

# Dry run (no alerts)
python -m src.runner --once --dry-run

# Look back 48 hours
python -m src.runner --once --hours 48
```

## Module Structure

```
surgical-prophylaxis/
├── src/
│   ├── __init__.py
│   ├── config.py           # Configuration, guidelines loading
│   ├── models.py           # Data classes (SurgicalCase, Evaluation, etc.)
│   ├── evaluator.py        # Core compliance evaluation logic
│   ├── database.py         # SQLite database operations
│   ├── fhir_client.py      # FHIR data access
│   ├── monitor.py          # Main monitor class
│   └── runner.py           # CLI entry point
├── data/
│   └── cchmc_surgical_prophylaxis_guidelines.json
├── schema.sql              # Database schema
├── SURGICAL_PROPHYLAXIS_IMPLEMENTATION_PLAN.md
└── README.md
```

## Procedure Coverage (55+ CPT codes)

| Specialty | Example Procedures | Primary Agent |
|-----------|-------------------|---------------|
| **Cardiac** | VSD repair, valve replacement, CABG | Cefazolin |
| **Thoracic** | Lobectomy, pneumonectomy | Cefazolin |
| **Hepatobiliary** | Cholecystectomy, liver transplant | Cefazolin, Pip-tazo |
| **Colorectal** | Colectomy, appendectomy | Cefazolin + Metronidazole |
| **GU** | Pyeloplasty, nephrectomy | Cefazolin |
| **Orthopedic** | Arthroplasty, spinal fusion, ORIF | Cefazolin |
| **Neurosurgery** | Craniotomy, VP shunt | Cefazolin, Vancomycin |
| **Vascular** | Endarterectomy, bypass | Cefazolin |

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
| Cardiac | Cefazolin | Vancomycin, Clindamycin |
| Colorectal | Cefazolin + Metronidazole | Clindamycin + Gentamicin |
| Orthopedic | Cefazolin | Vancomycin, Clindamycin |
| Neurosurgery (VP shunt) | Cefazolin + Vancomycin | Vancomycin |
| ENT (clean) | None | None |

### 3. Timing

| Antibiotic | Window |
|------------|--------|
| Cefazolin, Clindamycin | 60 min before incision |
| Vancomycin, Fluoroquinolones | 120 min before incision |

### 4. Weight-Based Dosing

| Agent | Pediatric | Adult | High-Weight (>120kg) |
|-------|-----------|-------|----------------------|
| Cefazolin | 30 mg/kg (max 2g) | 2g | 3g |
| Vancomycin | 15 mg/kg (max 2g) | 15 mg/kg (max 2g) | 15 mg/kg |
| Clindamycin | 10 mg/kg (max 900mg) | 900mg | 900mg |

### 5. Redosing Intervals

| Agent | Interval |
|-------|----------|
| Cefazolin | 4 hours |
| Cefoxitin, Ampicillin-Sulbactam | 2 hours |
| Clindamycin | 6 hours |
| Vancomycin, Metronidazole | Not typically needed |

### 6. Duration Limits

| Procedure Type | Maximum Duration |
|----------------|------------------|
| Cardiac surgery | 48 hours |
| All others | 24 hours |

## Alert Types

Alerts are created in the ASP Alerts queue with type `surgical_prophylaxis`:

- **Critical**: Missing prophylaxis for indicated procedure, antibiotics given after incision
- **Warning**: Wrong agent, timing outside window, incorrect dosing
- **Info**: Prolonged duration, missing redosing

## Configuration

### Environment Variables

```bash
FHIR_BASE_URL=http://localhost:8081/fhir    # FHIR server URL
ALERT_DB_PATH=~/.aegis/alerts.db            # Alert database path
FHIR_AUTH_TOKEN=xxx                          # Optional auth token
```

### Guidelines JSON

The module loads prophylaxis requirements from `data/cchmc_surgical_prophylaxis_guidelines.json`, which includes:

- Procedure categories with CPT codes
- First-line and alternative agents
- Dosing tables
- Redosing intervals
- Duration limits

## Database Schema

See `schema.sql` for the complete schema. Key tables:

- `surgical_cases` - Surgical case information
- `prophylaxis_evaluations` - Compliance evaluation results
- `prophylaxis_alerts` - Alert tracking
- `prophylaxis_orders` - Medication orders
- `prophylaxis_administrations` - Medication administrations
- `compliance_metrics` - Aggregated metrics

## Integration with AEGIS

The module integrates with:

- **Common Alert Store**: Alerts appear in ASP Alerts dashboard
- **Dashboard**: Compliance metrics visible at `/surgical-prophylaxis/`
- **Teams Notifications**: Alerts can trigger Teams webhooks

## Exclusion Criteria

Cases are excluded from compliance measurement if:

- Emergency surgery (timing may not be achievable)
- Patient already on therapeutic antibiotics
- Documented active infection
- Incomplete data

## References

1. ASHP/IDSA/SHEA/SIS. Clinical Practice Guidelines for Antimicrobial Prophylaxis in Surgery. 2013.
2. Bratzler DW, et al. Clinical practice guidelines for antimicrobial prophylaxis in surgery. Am J Health Syst Pharm. 2013.
3. Joint Commission MM.09.01.01 - Antimicrobial Stewardship Standard
4. CMS SCIP Measures

## Phase 2 (Future)

- Real-time pre-operative alerting
- Integration with OR scheduling
- SSI outcome correlation
- NSQIP reporting
