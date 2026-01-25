<p align="center">
  <img src="aegis-logo.png" alt="AEGIS Logo" width="400">
</p>

# AEGIS

**Automated Evaluation and Guidance for Infection Surveillance**

AEGIS is an intelligent clinical decision support platform for Antimicrobial Stewardship (ASP) and Infection Prevention (IP) teams. By integrating real-time EHR data from FHIR and Clarity with machine learning and AI, AEGIS aims to:

- **Detect** healthcare-associated infections (HAIs) in real-time using automated surveillance
- **Alert** on serious infections with inadequate antimicrobial coverage
- **Predict** infection risk using ML models to enable proactive prevention
- **Monitor** antimicrobial usage patterns and alert on opportunities for optimization
- **Report** to NHSN with automated HAI classification, antibiotic usage (AU), and antimicrobial resistance (AR) reporting
- **Reduce** manual chart review burden through AI-assisted clinical extraction

Our vision is to shift infection prevention from reactive detection to proactive risk assessment—identifying high-risk patients before infections occur and providing actionable guidance to clinicians at the point of care.

> **Disclaimer:** All patient data in this repository is **simulated** and was generated using [Synthea](https://github.com/synthetichealth/synthea) or custom test data generators. **No actual patient data exists in this repository.** Any resemblance to real patients is coincidental.

> **Epic Compatibility:** AEGIS is built against synthetic data that mirrors the structure of Epic's FHIR R4 API and Clarity data warehouse. This design allows the codebase to be readily deployed against live Epic environments with minimal configuration changes.

## Live Demo

**AEGIS Landing Page:** [https://aegis-asp.com](https://aegis-asp.com)

The landing page provides access to four main sections:

| Section | URL | Description |
|---------|-----|-------------|
| **ASP Alerts** | [/asp-alerts/](https://aegis-asp.com/asp-alerts/) | Antimicrobial stewardship alerts (bacteremia, usage monitoring) |
| **HAI Detection** | [/hai-detection/](https://aegis-asp.com/hai-detection/) | CLABSI and SSI candidate screening and IP review workflow |
| **NHSN Reporting** | [/nhsn-reporting/](https://aegis-asp.com/nhsn-reporting/) | AU, AR, and HAI data aggregation with NHSN submission |
| **Dashboards** | [/dashboards/](https://aegis-asp.com/dashboards/) | Analytics dashboards (coming soon) |

The demo environment includes synthetic patient data for testing alert, HAI detection, and AU/AR reporting workflows.

## Architecture

```
aegis/
├── common/                         # Shared infrastructure
│   ├── channels/                   # Email, Teams webhooks
│   └── alert_store/                # Persistent alert tracking (SQLite)
├── dashboard/                      # Web dashboard for alert management
├── asp-bacteremia-alerts/          # Blood culture coverage monitoring
├── antimicrobial-usage-alerts/     # Broad-spectrum usage monitoring
├── guideline-adherence/            # Real-time guideline bundle monitoring
├── surgical-prophylaxis/           # Surgical prophylaxis compliance
├── hai-detection/                  # HAI candidate detection, LLM extraction, IP review
├── nhsn-reporting/                 # AU/AR reporting, NHSN submission
├── scripts/                        # Demo and utility scripts
└── docs/                           # Documentation
```

## Current Modules

### asp-bacteremia-alerts

Real-time monitoring of blood culture results with antibiotic coverage assessment. Alerts ASP team when patients have positive cultures without appropriate antimicrobial coverage.

**Features:**
- FHIR R4 integration (HAPI FHIR for dev, Epic for production)
- Coverage rules for common pathogens (MRSA, VRE, Pseudomonas, Candida, etc.)
- Gram stain-based empiric coverage recommendations
- Multi-channel alerts: Email, Microsoft Teams with action buttons
- **Clinical data links** - Direct access to culture susceptibilities and patient medications from alerts

**Clinical Data Pages:**
| Page | URL | Description |
|------|-----|-------------|
| Culture Results | `/asp-alerts/culture/{id}` | Organism with susceptibility panel (S/I/R, MIC values) |
| Patient Medications | `/asp-alerts/patient/{id}/medications` | Current antibiotic orders |

**[Documentation →](asp-bacteremia-alerts/README.md)**

### antimicrobial-usage-alerts

Monitors antimicrobial usage patterns including broad-spectrum duration and antibiotic indication documentation. Provides two monitoring capabilities:

**Broad-Spectrum Duration Monitoring:**
- Alerts when meropenem, vancomycin, or other monitored antibiotics exceed configurable thresholds (default 72 hours)
- Severity escalation (warning at threshold, critical at 2x threshold)

**Antibiotic Indication Monitoring:**
- Validates documented indications for antibiotic orders using ICD-10 classification (Chua et al.)
- LLM extraction from clinical notes when ICD-10 codes are inconclusive
- Notes take priority over ICD-10 codes (codes may be stale or inaccurate)
- Only "Never appropriate" (N) classifications generate ASP alerts
- Supports nightly batch runs via cron

**Features:**
- Duration-based alerting for broad-spectrum antibiotics
- Two-track indication classification: ICD-10 codes + LLM note extraction
- Configurable thresholds and monitored medications
- Teams alerts with acknowledge/snooze buttons
- Override tracking for pharmacist disagreements

**[Documentation →](antimicrobial-usage-alerts/README.md)**

### guideline-adherence

Real-time monitoring of evidence-based clinical guideline bundles. Generates **GUIDELINE_DEVIATION** alerts when bundle elements are not completed within their time windows, and tracks aggregate compliance metrics for quality improvement and Joint Commission reporting.

**Supported Bundles (7):**
| Bundle | Elements | Key Metrics |
|--------|----------|-------------|
| **Pediatric Sepsis (CMS SEP-1)** | 6 | Blood culture, lactate, ABX ≤1h, fluids, reassessment |
| **Febrile Infant (AAP 2021)** | 12 | UA, blood cx, inflammatory markers, LP (age-stratified) |
| **Pediatric CAP** | 6 | CXR, SpO2, empiric choice, duration ≤7d |
| **Febrile Neutropenia** | 6 | Cultures, ABX ≤1h, risk stratification |
| **Surgical Prophylaxis** | 5 | Agent selection, timing ≤60min, duration ≤24h |
| **Pediatric UTI** | 7 | UA, culture, empiric choice, imaging |
| **SSTI/Cellulitis** | 6 | Margins marked, MRSA coverage, I&D if needed |

**Features:**
- Age-stratified logic for Febrile Infant bundle (8-21d, 22-28d, 29-60d per AAP 2021)
- Inflammatory marker threshold evaluation (PCT, ANC, CRP)
- FHIR-based real-time monitoring
- Integration with ASP Alerts queue
- Compliance metrics dashboard

**[Documentation →](guideline-adherence/README.md)**

### surgical-prophylaxis

Automated monitoring of surgical antimicrobial prophylaxis compliance following ASHP/IDSA/SHEA/SIS guidelines. Evaluates surgical cases against a 6-element bundle and generates **SURGICAL_PROPHYLAXIS** alerts for non-compliant cases.

**Bundle Elements (6):**
| Element | Description | Threshold |
|---------|-------------|-----------|
| **Indication** | Prophylaxis given/withheld appropriately | Per CPT code |
| **Agent Selection** | Correct antibiotic for procedure | Per guidelines |
| **Timing** | Administered before incision | ≤60 min (120 for vanco) |
| **Dosing** | Weight-based dosing | ±10% of calculated |
| **Redosing** | Intraop redose for long surgery | Per interval (4h cefazolin) |
| **Discontinuation** | Stopped after surgery | ≤24h (48h cardiac) |

**Features:**
- CPT code-based procedure identification (55+ procedures, 11 categories)
- Allergy-aware agent selection (beta-lactam alternatives)
- MRSA colonization screening integration
- Pediatric and adult dosing tables
- Integration with ASP Alerts queue

**Future Enhancements:**
- Real-time pre-operative alerting via Epic Secure Chat
- Alert when patient arrives in OR without prophylaxis
- SSI outcome correlation

**[Documentation →](surgical-prophylaxis/README.md)**

### hai-detection

Healthcare-Associated Infection (HAI) candidate detection, LLM-assisted classification, and IP review workflow. Uses rule-based screening combined with LLM fact extraction and deterministic NHSN rules to identify HAI candidates.

**Features:**
- **CLABSI detection** per CDC/NHSN surveillance criteria
- **SSI detection** with Superficial, Deep, and Organ/Space classification
- Clinical note retrieval from FHIR or Clarity
- Local Ollama LLM extraction (PHI-safe, no BAA required)
- **LLM extracts facts, rules apply logic** - Separation ensures auditability
- Dashboard integration for IP review workflow
- Common contaminant handling (requires 2 positive cultures)
- Override tracking for LLM quality assessment

**[Documentation →](hai-detection/README.md)**

### nhsn-reporting

NHSN data aggregation and submission including Antibiotic Use (AU), Antimicrobial Resistance (AR), and HAI event submission. Receives confirmed HAI events from hai-detection for NHSN reporting.

**Features:**
- Days of Therapy (DOT) tracking by antimicrobial category and location
- Antimicrobial resistance phenotype detection (MRSA, VRE, ESBL, CRE, CRPA)
- First-isolate rule deduplication per NHSN methodology
- Denominator calculations (patient days, device days, utilization ratios)
- **NHSN Submission** - Export CSV or submit directly via DIRECT protocol
- **CDA Document Generation** - HL7 CDA R2 compliant documents for automated submission
- Dashboard at `/nhsn-reporting/` with detail views and CSV export

**[Documentation →](nhsn-reporting/README.md)**

### dashboard

Web-based dashboard providing a unified interface for all AEGIS modules. The landing page at `/` provides navigation to four main sections:

**Sections:**
- **ASP Alerts** (`/asp-alerts/`) - Antimicrobial stewardship alert management
- **HAI Detection** (`/hai-detection/`) - CLABSI and SSI candidate screening and IP review workflow
- **NHSN Reporting** (`/nhsn-reporting/`) - AU, AR, and HAI data aggregation with NHSN submission
- **Guideline Adherence** (`/guideline-adherence/`) - Bundle compliance monitoring and metrics
- **Surgical Prophylaxis** (`/surgical-prophylaxis/`) - Surgical prophylaxis compliance (coming soon)
- **Dashboards** (`/dashboards/`) - Analytics dashboards (coming soon)

**Features:**
- Active and historical alert views with filtering
- Acknowledge, snooze, and resolve actions
- Resolution tracking with reasons and notes
- **Clinical Data Pages** - Culture results with susceptibilities, patient medication lists
- **Reports & Analytics** - Alert volume, resolution times, resolution breakdown
- **HAI Detection** - IP review workflow with LLM-assisted classification
- **NHSN Reporting** - Unified submission page for AU, AR, and HAI data
- **Help pages** - Interactive guides for each module
- Audit trail for compliance
- Teams button callbacks
- CCHMC-branded color scheme
- Auto-refresh on active alerts page

**[Documentation →](dashboard/README.md)** | **[Demo Workflow →](docs/demo-workflow.md)**

## HAI Monitoring and NHSN Reporting

The `hai-detection` and `nhsn-reporting` modules together provide automated surveillance for Healthcare-Associated Infections (HAIs) as defined by the CDC's National Healthcare Safety Network (NHSN). This supports both real-time infection detection and quarterly reporting requirements.

### What is NHSN?

The [National Healthcare Safety Network (NHSN)](https://www.cdc.gov/nhsn/) is the CDC's system for tracking healthcare-associated infections. Hospitals are required to report HAI data for:
- **CMS Quality Reporting** - Affects hospital reimbursement and public quality scores
- **State Mandates** - Many states require HAI reporting by law
- **Accreditation** - Joint Commission and other bodies require HAI surveillance
- **Internal Quality Improvement** - Benchmarking against national rates

### Supported HAI Types

| HAI Type | Status | Description |
|----------|--------|-------------|
| **CLABSI** | Implemented | Central Line-Associated Bloodstream Infection |
| **SSI** | Implemented | Surgical Site Infection (Superficial, Deep, Organ/Space) |
| **CAUTI** | Planned | Catheter-Associated Urinary Tract Infection |
| **VAE** | Planned | Ventilator-Associated Events |

### How It Works

```
                         EHR Data Sources
                    ┌──────────┴──────────┐
                    │                     │
              FHIR Server            Clarity DB
            (Real-time data)      (Aggregate data)
                    │                     │
                    ▼                     ▼
           ┌────────────────┐    ┌────────────────┐
           │  HAI Detection │    │  Denominators  │
           │  (BSI + Device │    │  (Line days,   │
           │   + Timing)    │    │   Census days) │
           └────────────────┘    └────────────────┘
                    │                     │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │   LLM Extraction   │  Extract clinical facts
                    │  (Ollama llama3.1) │  from notes (local, PHI-safe)
                    └────────────────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │    Rules Engine    │  Apply NHSN criteria
                    │   (Deterministic)  │  (fully auditable)
                    └────────────────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │    IP Review       │  Human-in-the-loop
                    │   (Dashboard)      │  final confirmation
                    └────────────────────┘
                               │
                               ▼
                    ┌────────────────────┐
                    │  NHSN Submission   │  CSV export or
                    │                    │  DIRECT protocol
                    └────────────────────┘
```

### Key Design Principles

1. **LLM extracts FACTS, rules apply LOGIC** - The LLM reads clinical notes to extract structured data (symptoms, alternate sources, line assessments). A deterministic rules engine then applies NHSN criteria. This separation ensures auditability and maintainability.

2. **Human-in-the-loop** - All HAI candidates are routed to Infection Prevention (IP) for final review. The LLM provides classification and confidence as decision support, but humans make the final call.

3. **PHI-safe inference** - Uses local Ollama with llama3.1 for all LLM operations. No PHI leaves your infrastructure; no BAA required with external AI providers.

4. **Hybrid data architecture** - FHIR for real-time HAI detection (blood cultures, devices, notes), Clarity for aggregate denominator calculations (line days, patient days by unit).

### NHSN Rate Calculations

HAI rates are calculated per NHSN methodology:

| Metric | Formula | Example |
|--------|---------|---------|
| **CLABSI Rate** | (CLABSI count / central line days) × 1,000 | 2 CLABSIs / 500 line days = 4.0 |
| **CAUTI Rate** | (CAUTI count / catheter days) × 1,000 | 1 CAUTI / 300 catheter days = 3.3 |
| **VAE Rate** | (VAE count / ventilator days) × 1,000 | 1 VAE / 200 vent days = 5.0 |

The `DenominatorCalculator` class aggregates device days and patient days from Clarity flowsheet data, broken down by department and month for NHSN location mapping.

### Submission Options

- **CSV Export** - Download confirmed HAIs for manual entry into NHSN web application
- **DIRECT Protocol** - Automated submission via HISP (Health Information Service Provider) using HL7 CDA R2 documents

See [hai-detection/README.md](hai-detection/README.md) for HAI detection documentation and [nhsn-reporting/README.md](nhsn-reporting/README.md) for submission and AU/AR documentation.

## AU/AR Reporting

The `nhsn-reporting` module provides NHSN Antibiotic Use (AU) and Antimicrobial Resistance (AR) reporting per CDC methodology.

### Antibiotic Usage (AU)

Tracks antimicrobial consumption by location:

| Metric | Description |
|--------|-------------|
| **Days of Therapy (DOT)** | Number of days a patient receives an antimicrobial agent |
| **DOT/1000 Patient Days** | Rate normalized to patient census for benchmarking |

Data is aggregated by NHSN antimicrobial category (carbapenems, 3rd gen cephalosporins, etc.) and location code.

### Antimicrobial Resistance (AR)

Tracks resistance patterns using the **first-isolate rule**:

- One isolate per patient per organism per quarter
- Prevents overweighting from repeat cultures
- Phenotype detection: MRSA, VRE, ESBL, CRE, CRPA

### Dashboard

Access NHSN Reporting at `/nhsn-reporting/`:

| Page | Description |
|------|-------------|
| **Dashboard** | Overview with AU, AR, and HAI summaries for current period |
| **AU Detail** | DOT by location and antimicrobial with drill-down |
| **AR Detail** | Resistance phenotypes and rates by organism |
| **HAI Detail** | Confirmed HAI events by type and location |
| **Denominators** | Patient days and device days by location |
| **Submission** | Unified NHSN submission for AU, AR, and HAI data |
| **Help** | Documentation and demo data guide |

### Demo Data

Generate realistic demo data:

```bash
cd nhsn-reporting
python scripts/generate_demo_data.py

# View in dashboard
cd ../dashboard && flask run
# Visit http://localhost:5000/nhsn-reporting/
```

See [nhsn-reporting/README.md](nhsn-reporting/README.md#auar-reporting-module) for complete AU/AR documentation.

## Shared Infrastructure

### common/channels

Reusable notification channels for all ASP modules:

- **EmailChannel** - SMTP email with HTML/text support
- **TeamsWebhookChannel** - Microsoft Teams via Workflows/Power Automate with action buttons

### common/alert_store

SQLite-backed persistent storage for alert lifecycle management:

- **Deduplication** - Prevents re-alerting on the same source (culture, order)
- **Status tracking** - Pending, Sent, Acknowledged, Snoozed, Resolved
- **Resolution reasons** - Track how alerts were handled (Changed Therapy, Discussed with Team, etc.)
- **Analytics** - Alert volume, response times, resolution breakdown
- **Audit trail** - Full history of alert actions for compliance

## Quick Start

```bash
# Clone the repo
git clone https://github.com/haslamdb/aegis.git
cd aegis

# Set up a Python virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies for the module you want to use
pip install -r asp-bacteremia-alerts/requirements.txt
# or
pip install -r antimicrobial-usage-alerts/requirements.txt
# or
pip install -r dashboard/requirements.txt

# Configure environment
cp asp-bacteremia-alerts/.env.template asp-bacteremia-alerts/.env
# Edit .env with your FHIR server and notification settings

# Start local FHIR server (for development)
cd asp-bacteremia-alerts
docker-compose up -d

# Run the monitor
python -m src.monitor
```

### Running the Dashboard

```bash
cd asp-alerts/dashboard
pip install -r requirements.txt

# Copy and configure environment
cp .env.template .env

# Run the dashboard (development)
flask run

# Visit http://localhost:5000
```

For production deployment, see [docs/demo-workflow.md](docs/demo-workflow.md#remote-access--production-deployment).

## Demo Workflow

Generate test alerts using the demo scripts:

```bash
# Create a patient with MRSA bacteremia (should trigger alert)
python scripts/demo_blood_culture.py --organism mrsa

# Create a patient on meropenem for 5 days (exceeds 72h threshold)
python scripts/demo_antimicrobial_usage.py --antibiotic meropenem --days 5

# Create CLABSI candidates for HAI detection
python scripts/demo_clabsi.py --all

# Create SSI candidates for HAI detection
python scripts/demo_ssi.py --all

# Run monitors to detect and send alerts
cd asp-bacteremia-alerts && python -m src.monitor
cd antimicrobial-usage-alerts && python -m src.runner --once

# Run HAI detection (CLABSI + SSI)
cd hai-detection && python -m src.runner --full
```

See [docs/demo-workflow.md](docs/demo-workflow.md) for complete walkthrough.

## Configuration

Each module uses environment variables for configuration. Copy `.env.template` to `.env` and configure:

| Setting | Description |
|---------|-------------|
| `FHIR_BASE_URL` | Local HAPI FHIR or Epic production URL |
| `TEAMS_WEBHOOK_URL` | Microsoft Teams Workflows webhook |
| `SMTP_SERVER` | SMTP server for email alerts |
| `DASHBOARD_BASE_URL` | URL for dashboard (used in Teams buttons) |
| `DASHBOARD_API_KEY` | API key for dashboard authentication |
| `ALERT_DB_PATH` | Path to SQLite database (default: ~/.aegis/alerts.db) |

## Future Modules (Roadmap)

| Priority | Module | Description |
|----------|--------|-------------|
| High | **Natural Language Query Interface** | Allow ASP/IPC users to query data in plain English (e.g., "Show E. coli resistance in urine isolates over 10 years"). Uses Claude API with BAA for SQL generation; PHI stays on-premises |
| High | **Interactive Analytics Dashboards** | Plotly-based interactive charts for resistance trends, antibiotic usage patterns, HAI rates over time. Drill-down capability, date range selection, export to PDF/PNG |
| High | **Automated Metrics** | Auto-generate DOT reports, benchmarks, and quality metrics with AI-written narrative summaries |
| High | **Bug-Drug Mismatch** | Identify when organisms are not covered by current therapy; suggest alternatives |
| High | **Real-Time Pre-Op Alerting** | Alert surgical team via Epic Secure Chat when patient arrives in OR without prophylaxis |
| Medium | **Predictive Risk Models** | ML models to identify patients at high risk for resistant infections or C. diff |
| Medium | **Duration Optimization** | Evidence-based duration recommendations at approval with reassessment triggers |
| Low | **Automated Approvals** | AI pre-screening of antibiotic approval requests with auto-approval or ASP referral |

**Recently Implemented:**
- ✅ **Guideline Adherence** - Real-time bundle monitoring with 7 guidelines including Febrile Infant (AAP 2021)
- ✅ **Surgical Prophylaxis** - 6-element compliance monitoring with CPT-based evaluation

## Development

### Prerequisites

- Python 3.11+
- Docker (for local FHIR server)
- Access to Epic FHIR API (for production)

### Testing

```bash
# Generate test patient data
python scripts/generate_pediatric_data.py --count 10

# Run bacteremia monitor once
cd asp-bacteremia-alerts
python -m src.monitor

# Run usage monitor with dry-run
cd antimicrobial-usage-alerts
python -m src.runner --once --dry-run

# Check dashboard shows alerts
cd dashboard
flask run
```

### Project Structure

```
aegis/
├── common/
│   ├── channels/              # Notification channels
│   │   ├── email.py
│   │   └── teams.py
│   └── alert_store/           # Persistent alert storage
│       ├── models.py
│       ├── store.py
│       └── schema.sql
├── dashboard/
│   ├── app.py                 # Flask application
│   ├── routes/                # API and view routes
│   ├── templates/             # Jinja2 templates
│   ├── static/                # CSS
│   └── deploy/                # Production deployment configs
├── asp-bacteremia-alerts/
│   └── src/
│       ├── alerters/          # Notification handlers
│       ├── monitor.py         # Main monitoring service
│       └── coverage_rules.py  # Antibiotic coverage logic
├── antimicrobial-usage-alerts/
│   └── src/
│       ├── alerters/          # Notification handlers
│       ├── monitor.py         # Usage monitoring service
│       └── runner.py          # CLI entry point
├── guideline-adherence/
│   └── src/
│       ├── checkers/          # Element checkers (lab, medication, note)
│       ├── monitor.py         # Guideline adherence monitor
│       ├── fhir_client.py     # FHIR data access
│       └── runner.py          # CLI entry point
├── surgical-prophylaxis/
│   └── src/
│       ├── evaluator.py       # 6-element bundle evaluation
│       ├── monitor.py         # Prophylaxis compliance monitor
│       ├── fhir_client.py     # FHIR data access
│       └── runner.py          # CLI entry point
├── hai-detection/
│   └── src/
│       ├── candidates/        # Rule-based HAI detection (CLABSI, SSI)
│       ├── classifiers/       # LLM classification
│       ├── extraction/        # LLM fact extraction (CLABSI, SSI)
│       ├── rules/             # NHSN rules engines (CLABSI, SSI)
│       ├── data/              # FHIR/Clarity data access
│       ├── llm/               # Ollama/Claude backends
│       ├── notes/             # Clinical note processing
│       ├── review/            # IP review workflow
│       └── monitor.py         # Main orchestration service
├── nhsn-reporting/
│   └── src/
│       ├── data/              # AU/AR data extraction
│       ├── cda/               # CDA document generation
│       └── direct/            # NHSN DIRECT protocol submission
├── scripts/                   # Demo and utility scripts
│   ├── demo_blood_culture.py
│   ├── demo_antimicrobial_usage.py
│   ├── demo_clabsi.py         # CLABSI candidate generator
│   ├── demo_ssi.py            # SSI candidate generator
│   └── generate_pediatric_data.py
└── docs/                      # Documentation
    └── demo-workflow.md       # Complete demo guide
```

## License

Internal use - Cincinnati Children's Hospital Medical Center

## Contact

ASP Informatics Team
