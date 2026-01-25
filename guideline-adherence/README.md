# AEGIS Guideline Adherence Monitoring

Real-time monitoring of evidence-based clinical guideline bundles with automated alerts for deviations and compliance tracking for quality improvement.

## Overview

The Guideline Adherence module provides:

1. **Real-time Monitoring** - Checks active patient episodes every 15 minutes for bundle element completion
2. **GUIDELINE_DEVIATION Alerts** - Creates alerts in ASP Alerts queue when bundle elements are not met within time windows
3. **Compliance Metrics** - Tracks aggregate adherence rates for QI dashboards and Joint Commission reporting

### Key Distinction from Antibiotic Indications

| Aspect | Antibiotic Indications | Guideline Adherence |
|--------|------------------------|---------------------|
| **Question** | "Is this order justified?" | "Did we follow the full pathway?" |
| **Timing** | Real-time (per order) | Real-time monitoring with time windows |
| **Scope** | Antibiotic orders only | Full care bundle (cultures, labs, imaging, consults, antibiotics) |
| **Alert Trigger** | No documented indication | Bundle element not completed within time window |
| **Output** | ASP alert for review | ASP alert + compliance metrics dashboard |

## Available Guideline Bundles

| Bundle | ID | Elements | Key Metrics |
|--------|-----|----------|-------------|
| **Pediatric Sepsis** | `sepsis_peds_2024` | 6 | Blood culture, lactate, ABX ≤1h, fluids, reassessment |
| **Pediatric CAP** | `cap_peds_2024` | 6 | CXR, SpO2, empiric choice, duration ≤7d |
| **Febrile Neutropenia** | `fn_peds_2024` | 6 | Cultures, ABX ≤1h, risk stratification |
| **Surgical Prophylaxis** | `surgical_prophy_2024` | 5 | Agent selection, timing ≤60min, duration ≤24h |
| **Pediatric UTI** | `uti_peds_2024` | 7 | UA, culture, empiric choice, imaging |
| **SSTI/Cellulitis** | `ssti_peds_2024` | 6 | Margins marked, MRSA coverage, I&D if needed |
| **Febrile Infant (AAP 2021)** | `febrile_infant_2024` | 12 | UA, blood cx, inflammatory markers, LP (age-stratified), HSV |

## Febrile Infant Bundle (AAP 2021)

The Febrile Infant bundle implements the AAP Clinical Practice Guideline for evaluation of well-appearing febrile infants 8-60 days old. It features:

### Age-Stratified Requirements

| Age Group | LP Required | Antibiotics | Disposition |
|-----------|-------------|-------------|-------------|
| 8-21 days | Yes (all) | Yes - parenteral | Admit all |
| 22-28 days, IMs abnormal | Yes | Yes - parenteral | Admit |
| 22-28 days, IMs normal | Consider | Consider | Home with close f/u acceptable |
| 29-60 days, IMs abnormal | Consider | Yes | Varies |
| 29-60 days, IMs normal | Not required | If UTI only | Home observation acceptable |

### Inflammatory Marker Thresholds (Abnormal)

- Procalcitonin > 0.5 ng/mL
- ANC > 4,000/μL
- CRP > 2.0 mg/dL

### Bundle Elements

| Element | Time Window | Required |
|---------|-------------|----------|
| Urinalysis obtained | 2h | Yes |
| Blood culture obtained | 2h | Yes |
| Inflammatory markers (ANC, CRP) | 2h | Yes |
| Procalcitonin (29-60 days) | 2h | Recommended |
| LP (8-21 days) | 2h | Yes |
| LP (22-28 days, IMs abnormal) | 2h | Yes |
| Parenteral antibiotics (8-21 days) | 1h | Yes |
| Parenteral antibiotics (22-28d, IMs abnormal) | 1h | Yes |
| HSV risk assessment (8-28 days) | 4h | Yes |
| Hospital admission (age/risk stratified) | - | Yes |
| Safe discharge checklist | - | Recommended |

## Installation

```bash
cd guideline-adherence

# Install dependencies
pip install -r requirements.txt

# Initialize database
python -c "from guideline_src.adherence_db import AdherenceDatabase; AdherenceDatabase()"
```

## Usage

### CLI Commands

```bash
# Run monitor once (check all active episodes)
python -m src.runner --once

# Run for specific bundle only
python -m src.runner --once --bundle sepsis_peds_2024

# Run febrile infant bundle
python -m src.runner --once --bundle febrile_infant_2024

# Dry run (no alerts created)
python -m src.runner --once --dry-run --verbose

# Run as daemon (every 15 minutes)
python -m src.runner --daemon --interval 15
```

### Cron Setup

```bash
# Add to crontab for automatic monitoring every 15 minutes
*/15 * * * * cd /home/david/projects/aegis/guideline-adherence && \
    python -m src.runner --once >> /var/log/aegis/guideline-adherence.log 2>&1
```

### Environment Variables

```bash
# FHIR server
export FHIR_BASE_URL=http://localhost:8081/fhir

# Epic FHIR (if configured)
export EPIC_FHIR_BASE_URL=https://your-epic-instance/FHIR/R4
export EPIC_CLIENT_ID=your-client-id
export EPIC_PRIVATE_KEY_PATH=/path/to/private.key

# Database paths
export GUIDELINE_ADHERENCE_DB_PATH=/path/to/guideline_adherence.db
export ALERT_DB_PATH=/path/to/alerts.db

# Enabled bundles (comma-separated)
export ENABLED_BUNDLES=sepsis_peds_2024,febrile_infant_2024
```

## Architecture

```
Patient Episode (FHIR: Conditions, Meds, Labs, Vitals)
         │
         ▼
GuidelineAdherenceMonitor (real-time, every 15 min)
         │
    ┌────┴────┐
    │         │
    ▼         ▼
Compliant   Non-Compliant (element NOT_MET)
    │             │
    │             ▼
    │      ASP Alert (GUIDELINE_DEVIATION)
    │      → Teams notification
    │      → Resolve/Override workflow
    │
    └──────┬──────┘
           ▼
   GuidelineAdherenceDB (all assessments)
           │
           ▼
   /guideline-adherence/ Dashboard
   → Compliance % by bundle/element
   → Trends over time
   → Drill-down to episodes
```

## Module Structure

```
guideline-adherence/
├── src/
│   ├── __init__.py
│   ├── config.py                 # Configuration with LOINC codes, thresholds
│   ├── models.py                 # GuidelineMonitorResult, ElementCheckResult
│   ├── fhir_client.py            # Extended FHIR client (vitals, MedicationAdmin)
│   ├── monitor.py                # GuidelineAdherenceMonitor class
│   ├── adherence_db.py           # SQLite for tracking episodes
│   ├── checkers/
│   │   ├── __init__.py
│   │   ├── base.py               # ElementChecker ABC
│   │   ├── lab_checker.py        # Blood culture, lactate, inflammatory markers
│   │   ├── medication_checker.py # Antibiotic timing, fluid bolus
│   │   ├── note_checker.py       # Reassessment documentation
│   │   └── febrile_infant_checker.py  # Age-stratified febrile infant logic
│   └── runner.py                 # CLI entry point
├── guideline_adherence.py        # Bundle definitions (GUIDELINE_BUNDLES)
├── febrile_infant_guideline.py   # Original CCHMC febrile infant evaluator
└── tests/
```

## Alert Content

GUIDELINE_DEVIATION alerts appear in ASP Alerts and include:

- **Bundle Info**: Which guideline bundle triggered the alert
- **Element Details**: Specific element that was not met
- **Time Window**: Required completion timeframe and when it expired
- **Recommendation**: Suggested action for ASP team
- **Overall Adherence**: Current compliance percentage for this episode

Example alert:
```
Guideline Deviation: Antibiotics within 1 hour
Pediatric Sepsis Bundle: Broad-spectrum antibiotics not administered within 1 hour of sepsis recognition.
Time window: 1h (expired at 2024-01-24T11:00:00)
Overall adherence: 50%
```

## Dashboard Features

Access the dashboard at `/guideline-adherence/`

### Compliance Metrics
- Overall compliance rate by bundle
- Element-level compliance breakdown
- Trend over time (7/30/90 days)
- Active episodes being monitored

### Episode Detail View
- Element timeline with status indicators
- Completion timestamps and values
- Deviation history and alerts
- Bundle reference information

## Joint Commission (JC) Compliance

This module supports MM.09.01.01 EP 18-19 compliance by:

- Implementing evidence-based guidelines for infectious disease treatment
- Real-time monitoring of antimicrobial stewardship protocols
- Generating aggregate compliance metrics for quality improvement
- Providing drill-down capability to individual episodes
- Documenting interventions through the alert resolution workflow

## References

1. **Surviving Sepsis Campaign.** International Guidelines for Management of Sepsis and Septic Shock. 2021.

2. **AAP Clinical Practice Guideline.** Evaluation and Management of Well-Appearing Febrile Infants 8 to 60 Days Old. Pediatrics. August 2021.

3. **Bradley JS, et al.** The Management of Community-Acquired Pneumonia in Infants and Children Older Than 3 Months of Age: PIDS and IDSA. Clin Infect Dis. 2011.

4. **The Joint Commission.** MM.09.01.01 - Antimicrobial Stewardship Standard. Effective January 1, 2023.

5. **CMS.** Severe Sepsis and Septic Shock Early Management Bundle (SEP-1).

---

## License

Internal use only - Cincinnati Children's Hospital Medical Center
