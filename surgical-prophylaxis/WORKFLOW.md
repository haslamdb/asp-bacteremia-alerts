# Surgical Prophylaxis Adherence Screening Workflow

## Overview

The Surgical Prophylaxis module performs **retrospective monitoring** of surgical cases to evaluate compliance with antibiotic prophylaxis guidelines. It queries the FHIR server for completed surgical procedures, evaluates each case against 7 bundle elements, and generates alerts for non-compliant cases.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SCREENING WORKFLOW                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. QUERY FHIR      2. BUILD CASE      3. EVALUATE       4. ALERT       │
│  ─────────────      ────────────       ────────────      ────────       │
│                                                                          │
│  Get surgical       Fetch patient      Check 7 bundle    Create alert   │
│  procedures from    weight, meds,      elements against  for non-       │
│  past 24-48 hours   allergies, times   CCHMC guidelines  compliant      │
│                                                                          │
│      │                   │                  │                 │         │
│      ▼                   ▼                  ▼                 ▼         │
│  ┌────────┐         ┌────────┐         ┌────────┐        ┌────────┐    │
│  │Procedure│   ───▶  │Surgical│   ───▶  │Evaluation│ ───▶ │  ASP   │    │
│  │ Resource│         │  Case  │         │ Result  │       │ Alert  │    │
│  └────────┘         └────────┘         └────────┘        └────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Running the Screener

### Command Line Options

```bash
cd /home/david/projects/aegis/surgical-prophylaxis

# Run once - evaluate past 24 hours, create alerts
python -m src.runner --once

# Dry run - evaluate but don't create alerts (good for testing)
python -m src.runner --once --dry-run

# Verbose output - see details for each case
python -m src.runner --once --verbose

# Look back 48 hours instead of 24
python -m src.runner --once --hours 48

# Combine options
python -m src.runner --once --hours 48 --verbose --dry-run
```

### Typical Output

```
INFO:src.monitor:Starting surgical prophylaxis monitor (looking back 24h)
INFO:src.monitor:Found 18 procedures to evaluate

  Case: proc-12345
  Status: COMPLIANT
  Score: 100.0% (7/7)
    ✓ Indication: Prophylaxis correctly given for colorectal procedure
    ✓ Agent Selection: Cefoxitin appropriate for colorectal
    ✓ Pre-op Timing: Administered 42 min before incision
    ✓ Dosing: 80 mg/kg (1600mg) appropriate for weight 40kg
    ✓ Redosing: No redosing needed (surgery <3h)
    ✓ Post-op Continuation: No post-op doses (appropriate)
    ✓ Duration: Discontinued at end of surgery

  Case: proc-12346
  Status: NON-COMPLIANT
  Score: 85.7% (6/7)
    ✓ Indication: Prophylaxis correctly given for cardiac procedure
    ✓ Agent Selection: Cefazolin appropriate for cardiac
    ✓ Pre-op Timing: Administered 35 min before incision
    ✓ Dosing: 120 mg/kg (2000mg) appropriate for weight 50kg
    ✓ Redosing: Redose given at 3.5 hours (appropriate)
    ✓ Post-op Continuation: Post-op dose given (allowed for cardiac)
    ✗ Duration: Prophylaxis continued for 72h (max allowed: 48h)
  Created alert a1b2c3d4-...

============================================================
SUMMARY
============================================================
Total cases evaluated: 18
  Compliant: 14
  Non-compliant: 3
  Excluded: 1
Average compliance score: 92.4%
```

---

## What Gets Evaluated

### The 7 Bundle Elements

| # | Element | What It Checks | Pass Criteria |
|---|---------|----------------|---------------|
| 1 | **Indication** | Was prophylaxis given/withheld appropriately? | Match procedure requirements |
| 2 | **Agent Selection** | Correct antibiotic for procedure + allergies? | First-line or valid alternative |
| 3 | **Pre-op Timing** | Given before incision in window? | ≤60 min (≤120 min vancomycin) |
| 4 | **Dosing** | Weight-based dose correct? | Within 10% of calculated dose |
| 5 | **Redosing** | Redose given for long surgery? | Per interval (Q3H cefazolin) |
| 6 | **Post-op Continuation** | Post-op doses appropriate? | Required/allowed/prohibited by procedure |
| 7 | **Duration** | Stopped within time limit? | ≤24h (≤48h cardiac) |

### Exclusion Criteria

Cases are excluded from compliance measurement (not counted as failures) if:

- **Emergency surgery** - timing may not be achievable
- **Therapeutic antibiotics** - patient already on treatment for infection
- **Documented active infection** - prophylaxis not applicable
- **Incomplete data** - missing critical data elements

---

## Data Flow

### 1. Query FHIR Server

The monitor queries the FHIR server for `Procedure` resources with:
- Status: `completed`
- Date range: past 24-48 hours
- Category: surgical procedures

```python
# Internal query (simplified)
procedures = fhir_client.get_surgical_procedures(
    date_from=datetime.now() - timedelta(hours=24),
    date_to=datetime.now()
)
```

### 2. Build Surgical Case

For each procedure, the monitor fetches additional data:

| Data Element | FHIR Resource | Purpose |
|--------------|---------------|---------|
| Patient weight | `Observation` | Weight-based dosing check |
| Allergies | `AllergyIntolerance` | Agent selection (alternatives) |
| Medication orders | `MedicationRequest` | Prophylaxis orders |
| Administrations | `MedicationAdministration` | Timing, actual doses given |
| Incision time | `Procedure.performedPeriod.start` | Pre-op timing calculation |
| Surgery end | `Procedure.performedPeriod.end` | Duration calculation |

### 3. Evaluate Against Guidelines

The evaluator:
1. Looks up CPT code in `cchmc_surgical_prophylaxis_guidelines.json`
2. Determines procedure requirements (agent, duration, post-op needs)
3. Checks each bundle element
4. Calculates compliance score (% elements met)

### 4. Create Alerts

For non-compliant cases, alerts are created with severity based on the violation:

| Severity | Trigger |
|----------|---------|
| **Critical** | Missing prophylaxis when indicated, antibiotics given AFTER incision |
| **Warning** | Wrong agent, timing outside window, incorrect dosing |
| **Info** | Prolonged duration, missing redosing |

---

## Where Alerts Appear

### ASP Alerts Dashboard

Alerts appear in the AEGIS ASP Alerts dashboard at `/asp-alerts/`:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ASP Alerts                                    [Filter: Surgical Ppx ▼]  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│ ⚠️  Surgical Prophylaxis: Duration                          2 hours ago │
│     MRN: 123456 | Laparoscopic Appendectomy                             │
│     6/7 elements met. Issues: Duration                                  │
│     [View Details]  [Acknowledge]  [Resolve]                            │
│                                                                          │
│ 🔴 Surgical Prophylaxis: Indication                        4 hours ago  │
│     MRN: 234567 | Spinal Fusion with Instrumentation                    │
│     0/7 elements met. Issues: No prophylaxis given                      │
│     [View Details]  [Acknowledge]  [Resolve]                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Alert Detail View

Clicking an alert shows:
- Patient information
- Procedure details (CPT, description, times)
- Compliance scorecard (7 elements)
- What was given vs. what was expected
- Recommendations

---

## Scheduled Execution

### Cron Setup (Production)

Add to crontab for automated screening:

```bash
# Run surgical prophylaxis screening every 4 hours
0 */4 * * * cd /home/david/projects/aegis/surgical-prophylaxis && python -m src.runner --once --hours 6 >> /var/log/aegis/surgical-prophylaxis.log 2>&1

# Run daily summary at 6 AM
0 6 * * * cd /home/david/projects/aegis/surgical-prophylaxis && python -m src.runner --once --hours 24 --verbose >> /var/log/aegis/surgical-prophylaxis-daily.log 2>&1
```

### Systemd Timer (Alternative)

```ini
# /etc/systemd/system/aegis-surgical-prophylaxis.timer
[Unit]
Description=AEGIS Surgical Prophylaxis Monitor

[Timer]
OnCalendar=*:0/4:00
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Interpreting Results

### Compliance Score

- **100%** - All applicable elements met (bundle compliant)
- **85-99%** - Minor issues (e.g., duration slightly over)
- **70-84%** - Multiple issues need attention
- **<70%** - Significant gaps in compliance

### Common Issues and Actions

| Issue | Typical Cause | Action |
|-------|---------------|--------|
| Duration >24h | Prophylaxis not stopped after surgery | Education, automatic stop orders |
| Timing >60 min | Pre-op delays, late ordering | Earlier pharmacy verification |
| Wrong agent | Unfamiliarity with guidelines | Order set updates |
| Missing redosing | Long surgery without reminder | Intra-op alerts (Phase 2) |
| No prophylaxis | Order missed | Pre-op checklist |

---

## Database and Reporting

### Local Database

Evaluations are stored in `~/.aegis/surgical_prophylaxis.db`:

```sql
-- Key tables
surgical_cases        -- Case information (MRN, procedure, times)
prophylaxis_evaluations  -- Evaluation results (7 elements, score)
prophylaxis_alerts    -- Alert tracking (created, acknowledged, resolved)
compliance_metrics    -- Aggregated daily/weekly/monthly metrics
```

### Querying Metrics

```bash
# Open database
sqlite3 ~/.aegis/surgical_prophylaxis.db

# Compliance by month
SELECT
    strftime('%Y-%m', evaluation_time) as month,
    COUNT(*) as cases,
    SUM(bundle_compliant) as compliant,
    ROUND(100.0 * SUM(bundle_compliant) / COUNT(*), 1) as rate
FROM prophylaxis_evaluations
WHERE excluded = 0
GROUP BY 1
ORDER BY 1;

# Non-compliant by element
SELECT
    'indication' as element,
    SUM(CASE WHEN indication_appropriate = 0 THEN 1 ELSE 0 END) as failures
FROM prophylaxis_evaluations
WHERE excluded = 0
UNION ALL
SELECT 'agent', SUM(CASE WHEN agent_appropriate = 0 THEN 1 ELSE 0 END)
FROM prophylaxis_evaluations WHERE excluded = 0
-- ... etc for each element
```

---

## Troubleshooting

### No Procedures Found

```
INFO:src.monitor:Found 0 procedures to evaluate
```

Check:
1. FHIR server is running: `curl http://localhost:8081/fhir/metadata`
2. Procedures exist in date range: expand `--hours`
3. Procedure status is `completed` (not `in-progress`)

### FHIR Connection Error

```
ERROR: Connection refused to http://localhost:8081/fhir
```

Check:
1. FHIR server is running
2. `FHIR_BASE_URL` environment variable is correct

### Unknown CPT Code

```
  - Indication: Unable to assess - CPT 99999 not in guidelines
```

This is expected for procedures not in `cchmc_surgical_prophylaxis_guidelines.json`. Case will be marked as excluded.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `FHIR_BASE_URL` | `http://localhost:8081/fhir` | FHIR server URL |
| `ALERT_DB_PATH` | `~/.aegis/alerts.db` | Alert database path |

### Guidelines File

Prophylaxis requirements are loaded from:
```
surgical-prophylaxis/data/cchmc_surgical_prophylaxis_guidelines.json
```

This includes 310+ CPT codes with procedure-specific:
- First-line and alternative agents
- Dosing (mg/kg, max dose)
- Redosing intervals
- Duration limits
- Post-op continuation requirements

---

## Next Steps (Phase 2)

The current implementation is **retrospective** (after-the-fact). Future enhancements include:

1. **Real-time pre-op alerting** - Alert when patient arrives in pre-op without prophylaxis order
2. **Intraoperative redosing alerts** - Remind anesthesia to redose during long surgeries
3. **Epic Secure Chat integration** - Deliver alerts directly to providers
4. **SSI outcome correlation** - Link prophylaxis compliance to infection rates

See `FUTURE_ENHANCEMENTS.md` for details.
