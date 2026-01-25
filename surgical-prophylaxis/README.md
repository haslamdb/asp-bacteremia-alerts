# AEGIS Surgical Antimicrobial Prophylaxis Module

Real-time monitoring of surgical antimicrobial prophylaxis compliance based on ASHP/IDSA/SHEA/SIS 2013 guidelines and local CCHMC protocols (v2024.2, September 2024).

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
