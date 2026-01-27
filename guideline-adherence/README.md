# AEGIS Guideline Adherence Monitoring

Real-time monitoring of evidence-based clinical guideline bundles with automated alerts for deviations and compliance tracking for quality improvement.

## Overview

The Guideline Adherence module provides:

1. **Trigger Detection** - Automatically detects when patients match bundle criteria (diagnoses, orders, labs)
2. **Real-time Monitoring** - Checks active patient episodes for bundle element completion
3. **GUIDELINE_DEVIATION Alerts** - Creates alerts when bundle elements are not met within time windows
4. **Compliance Metrics** - Tracks aggregate adherence rates for QI dashboards and Joint Commission reporting

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
| **Febrile Infant (AAP 2021)** | `febrile_infant_2024` | 14 | UA, blood cx, inflammatory markers, LP (age-stratified), HSV risk, safe discharge |
| **Neonatal HSV** | `neonatal_hsv_2024` | 11 | CSF/blood PCR, surface cultures, LFTs, acyclovir dosing, ID consult |
| **C. diff Testing** | `cdiff_testing_2024` | 8 | Diagnostic stewardship criteria (age, symptoms, risk factors) |

## Bundle Trigger System

The module automatically detects when to start monitoring a patient based on configured triggers:

### Trigger Types

| Trigger Type | Description | Example |
|--------------|-------------|---------|
| **Diagnosis** | New ICD-10 code added | A41.9 (Sepsis) → Sepsis bundle |
| **Medication** | Specific medication ordered | Acyclovir in neonate → HSV bundle |
| **Lab Order** | Specific lab test ordered | C. diff PCR ordered → C. diff Testing bundle |
| **Vital Sign** | Abnormal vital detected | Temp ≥38°C in infant → Febrile Infant bundle |

### Configured Triggers

| Bundle | Trigger Type | Trigger Codes |
|--------|--------------|---------------|
| Sepsis | Diagnosis | A41%, A40%, R65.2%, P36% |
| Sepsis | Lab | Lactate (LOINC 2524-7) |
| Febrile Infant | Diagnosis | R50%, P81.9 (age 8-60d) |
| Neonatal HSV | Diagnosis | P35.2, B00% (age ≤21d) |
| Neonatal HSV | Medication | Acyclovir ordered |
| Neonatal HSV | Lab | HSV PCR (LOINC 16955-7, 49986-3) |
| C. diff Testing | Lab | C. diff toxin/PCR/GDH |
| CAP | Diagnosis | J13-J18 |
| UTI | Diagnosis | N39.0, N10, N30% |

## Febrile Infant Bundle (AAP 2021 + CCHMC)

The Febrile Infant bundle implements the AAP Clinical Practice Guideline for evaluation of well-appearing febrile infants 8-60 days old with CCHMC enhancements.

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

### HSV Risk Integration (CCHMC Enhancement)

For infants 0-28 days, HSV risk factors are automatically detected:
- Maternal HSV history
- Scalp electrode use
- Vesicular rash
- Seizures
- CSF pleocytosis
- Elevated LFTs (>3x ULN)

If risk factors present → Acyclovir administration is tracked as a required element.

### Safe Discharge Checklist (CCHMC Enhancement)

For infants being discharged home, tracks 5 safety elements:
1. Follow-up within 24h arranged
2. Working phone number documented
3. Reliable transportation confirmed
4. Parent education completed
5. Return precautions verbalized

## Neonatal HSV Bundle (CCHMC 2024)

Comprehensive monitoring for suspected HSV in neonates ≤21 days.

### Elements (11 total)

| Element | Time Window | Required |
|---------|-------------|----------|
| CSF HSV PCR | 4h | Yes |
| Surface cultures (SEM) | 4h | Yes |
| Blood HSV PCR | 4h | Yes |
| LFTs obtained | 4h | Yes |
| Acyclovir started | 1h | Yes |
| Acyclovir 60mg/kg/day Q8H | 24h | Yes |
| ID consult | 24h | Yes |
| Ophthalmology (if ocular) | 48h | Conditional |
| Neuroimaging (if CNS) | 48h | Conditional |
| Treatment duration | End of therapy | Yes |
| Suppressive therapy follow-up | Discharge | Yes |

### Classification-Based Treatment Duration

| HSV Classification | Treatment Duration |
|-------------------|-------------------|
| SEM (Skin, Eye, Mouth) | 14 days |
| CNS disease | 21 days |
| Disseminated | 21 days |

## C. diff Testing Appropriateness Bundle (CCHMC 2024)

Diagnostic stewardship bundle to ensure C. diff testing criteria are met before ordering.

### Appropriateness Criteria

| Criterion | Requirement |
|-----------|-------------|
| Age | ≥3 years (or exception documented) |
| Symptoms | ≥3 liquid stools in 24 hours |
| No laxatives | Not given within 48 hours |
| No enteral contrast | Not given within 48 hours |
| No tube feed changes | Not changed within 48 hours |
| No active GI bleed | Documented |
| Risk factor present | Antibiotics, hospitalization, PPI, gastrostomy, or chronic disease |
| Symptom duration | ≥48 hours if low-risk patient |

### Appropriateness Classification

- **Appropriate**: All criteria met
- **Potentially Inappropriate**: 1-2 concerns
- **Inappropriate**: 3+ concerns or major exclusion

## Installation

```bash
cd guideline-adherence

# Install dependencies
pip install -r requirements.txt

# Initialize database
python -c "from guideline_src.episode_db import EpisodeDB; EpisodeDB()"
```

## Usage

### CLI Commands

```bash
# List available bundles
python -m guideline_src.runner --list-bundles

# === TRIGGER MONITORING (detect new patients) ===

# Poll once for new triggers
python -m guideline_src.runner --trigger --once

# Poll continuously (every 60 seconds)
python -m guideline_src.runner --trigger --daemon --interval 60

# Show monitoring status
python -m guideline_src.runner --trigger --status

# Use real FHIR connection
python -m guideline_src.runner --trigger --daemon --use-fhir

# === EPISODE MONITORING (check deadlines, create alerts) ===

# Check all active episodes for overdue elements
python -m guideline_src.runner --episodes --once

# Run as daemon (every 5 minutes)
python -m guideline_src.runner --episodes --daemon --interval 5

# Show episode status (active episodes, pending elements, alerts)
python -m guideline_src.runner --episodes --status

# Verbose output
python -m guideline_src.runner --episodes --once --verbose

# === ADHERENCE CHECKING (verify element completion via FHIR) ===

# Check all active episodes once
python -m guideline_src.runner --once

# Dry run (no alerts created)
python -m guideline_src.runner --once --dry-run --verbose

# Check specific bundle only
python -m guideline_src.runner --once --bundle febrile_infant_2024

# Run as daemon (every 15 minutes)
python -m guideline_src.runner --daemon --interval 15
```

### Cron Setup

```bash
# Trigger monitoring - poll for new patients every minute
* * * * * cd /home/david/projects/aegis/guideline-adherence && \
    python -m guideline_src.runner --trigger --once --use-fhir >> /var/log/aegis/trigger-monitor.log 2>&1

# Episode monitoring - check for overdue elements every 5 minutes
*/5 * * * * cd /home/david/projects/aegis/guideline-adherence && \
    python -m guideline_src.runner --episodes --once >> /var/log/aegis/episode-monitor.log 2>&1

# Adherence checking - verify element completion every 15 minutes
*/15 * * * * cd /home/david/projects/aegis/guideline-adherence && \
    python -m guideline_src.runner --once >> /var/log/aegis/guideline-adherence.log 2>&1
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
export ENABLED_BUNDLES=sepsis_peds_2024,febrile_infant_2024,neonatal_hsv_2024
```

## Architecture

The system operates in three modes:

```
FHIR Server (Conditions, Medications, Labs, Vitals)
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│    MODE 1: BUNDLE TRIGGER MONITOR (--trigger)           │
│  - Polls for new diagnoses, orders, labs, vitals        │
│  - Matches to bundle triggers                           │
│  - Creates episodes when criteria met                   │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              EPISODE DATABASE                            │
│  - bundle_episodes: Active monitoring episodes          │
│  - bundle_element_results: Element status tracking      │
│  - bundle_alerts: Generated alerts                      │
└─────────────────────┬───────────────────────────────────┘
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
┌─────────────────────┐  ┌───────────────────────────────┐
│ MODE 2: EPISODE     │  │ MODE 3: ADHERENCE MONITOR     │
│ MONITOR (--episodes)│  │         (--once)              │
│ - Checks deadlines  │  │ - Verifies completion via FHIR│
│ - Creates alerts    │  │ - Uses specialized checkers   │
│ - Assigns severity  │  │ - Calculates adherence %      │
└─────────┬───────────┘  └──────────────┬────────────────┘
          │                             │
          └───────────┬─────────────────┘
                      ▼
              ┌───────┴───────┐
              ▼               ▼
         Compliant      Non-Compliant
              │               │
              │               ▼
              │        ASP Alert (GUIDELINE_DEVIATION)
              │        → CRITICAL for ABX/acyclovir delays
              │        → WARNING for other elements
              │        → Teams notification
              │
              └───────┬───────┘
                      ▼
            Dashboard (/guideline-adherence/)
            → Compliance % by bundle/element
            → Trends over time
            → Active episodes
            → Episode detail view
```

## Module Structure

```
guideline-adherence/
├── guideline_src/
│   ├── __init__.py
│   ├── config.py                 # Configuration with LOINC codes, thresholds
│   ├── models.py                 # GuidelineMonitorResult, ElementCheckResult
│   ├── fhir_client.py            # Extended FHIR client
│   ├── monitor.py                # GuidelineAdherenceMonitor (Mode 3)
│   ├── bundle_monitor.py         # BundleTriggerMonitor (Mode 1)
│   ├── episode_monitor.py        # EpisodeAdherenceMonitor (Mode 2)
│   ├── adherence_db.py           # Legacy adherence database
│   ├── episode_db.py             # Episode tracking database
│   ├── checkers/
│   │   ├── __init__.py
│   │   ├── base.py               # ElementChecker ABC
│   │   ├── lab_checker.py        # Blood culture, lactate, inflammatory markers
│   │   ├── medication_checker.py # Antibiotic timing, fluid bolus
│   │   ├── note_checker.py       # Reassessment documentation
│   │   ├── febrile_infant_checker.py  # Age-stratified febrile infant logic
│   │   ├── hsv_checker.py        # Neonatal HSV bundle
│   │   └── cdiff_testing_checker.py   # C. diff testing stewardship
│   └── runner.py                 # CLI entry point (all three modes)
├── guideline_adherence.py        # Bundle definitions (GUIDELINE_BUNDLES)
├── demo_patients.py              # Demo patient scenarios for testing
├── schema.sql                    # Database schema
└── tests/
```

## Database Schema

### Tables

| Table | Purpose |
|-------|---------|
| `bundle_episodes` | Active monitoring episodes per patient/bundle |
| `bundle_element_results` | Status of each element within an episode |
| `bundle_alerts` | Alerts generated for overdue/not met elements |
| `bundle_triggers` | Configuration for what triggers each bundle |
| `monitor_state` | Last poll time for incremental polling |

### Views

| View | Purpose |
|------|---------|
| `v_active_episodes` | Active episodes with element summary |
| `v_pending_elements` | Elements that need attention (with urgency) |
| `v_active_alerts` | Active alerts sorted by severity |
| `v_adherence_summary` | Adherence statistics by bundle (last 30 days) |

## Alert Content

GUIDELINE_DEVIATION alerts appear in ASP Alerts and include:

- **Bundle Info**: Which guideline bundle triggered the alert
- **Element Details**: Specific element that was not met
- **Time Window**: Required completion timeframe and when it expired
- **Recommendation**: Suggested action for ASP team
- **Overall Adherence**: Current compliance percentage for this episode

Example alert:
```
Guideline Deviation: Acyclovir started
Neonatal HSV Bundle: IV acyclovir not initiated within 1 hour of HSV suspicion.
Time window: 1h (expired at 2024-01-24T11:00:00)
HSV risk factors: maternal hsv, csf pleocytosis
Overall adherence: 45%
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

### Monitoring Status
- Active episodes by bundle
- Pending elements with urgency
- Active alerts by severity
- Adherence summary statistics

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

3. **Kimberlin DW.** Neonatal herpes simplex infection. Clin Microbiol Rev. 2004.

4. **IDSA/SHEA.** Clinical Practice Guidelines for Clostridium difficile Infection. 2018.

5. **CCHMC Pocket Docs.** Bugs & Drugs Guidelines, Neonatal HSV Algorithm, C. diff Testing Algorithm. 2024.

6. **Bradley JS, et al.** The Management of Community-Acquired Pneumonia in Infants and Children Older Than 3 Months of Age: PIDS and IDSA. Clin Infect Dis. 2011.

7. **The Joint Commission.** MM.09.01.01 - Antimicrobial Stewardship Standard. Effective January 1, 2023.

8. **CMS.** Severe Sepsis and Septic Shock Early Management Bundle (SEP-1).

---

## License

Internal use only - Cincinnati Children's Hospital Medical Center
