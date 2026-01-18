# NHSN HAI Reporting Module

Automated NHSN Healthcare-Associated Infection (HAI) detection and classification for asp-alerts. This module uses rule-based screening combined with LLM-assisted classification to identify CLABSI (Central Line-Associated Bloodstream Infection) candidates and route them through an IP review workflow.

## Overview

The NHSN reporting module implements a three-stage workflow:

1. **Rule-Based Screening** - Identifies HAI candidates based on NHSN criteria (BSI + central line + timing requirements)
2. **LLM Classification** - Uses local Ollama LLM to analyze clinical notes for source attribution
3. **IP Review** - Routes uncertain cases to Infection Prevention for human review

```
Blood Culture (positive)
         │
         ▼
┌─────────────────────┐
│  Rule-Based Screen  │  Check: Central line present? Device days ≥2?
└─────────────────────┘  BSI within eligibility window?
         │
    Candidates
         │
         ▼
┌─────────────────────┐
│  LLM Classification │  Analyze notes for:
│      (Ollama)       │  - Alternative source of infection
└─────────────────────┘  - NHSN criteria match
         │
         ├── Confidence ≥85% ──► Auto-classify
         │
         ├── Confidence 60-85% ─► IP Review Queue
         │
         └── Confidence <60% ──► Manual Review
         │
         ▼
┌─────────────────────┐
│    NHSN Events      │  Confirmed HAIs ready for submission
└─────────────────────┘
```

## Features

- **CLABSI Detection** - Rule-based screening per CDC/NHSN criteria
- **Note Processing** - Retrieves clinical notes from FHIR or Clarity
- **LLM Classification** - Local Ollama inference (PHI-safe, no BAA required)
- **Confidence-Based Triage** - Automatic routing based on classification confidence
- **IP Review Dashboard** - Web interface for reviewing uncertain cases
- **Audit Trail** - Full logging of all classifications and decisions
- **FHIR + Clarity Support** - Abstraction layer for multiple EHR data sources

## Quick Start

### Prerequisites

- Python 3.11+
- Running FHIR server (HAPI FHIR for dev, Epic for production)
- Ollama with llama3.1:70b model (or configured alternative)

### Installation

```bash
cd nhsn-reporting

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.template .env
# Edit .env with your settings

# Initialize database
python -c "from src.db import NHSNDatabase; NHSNDatabase().init_db()"
```

### Running the Monitor

```bash
# Dry run (detect candidates, no LLM classification)
python -m src.runner --dry-run

# Run once (full pipeline with classification)
python -m src.runner --once

# Continuous monitoring
python -m src.runner
```

### Viewing Results

Results appear in the main ASP Alerts dashboard:

1. Start the dashboard: `cd ../dashboard && flask run`
2. Visit http://localhost:5000/nhsn
3. View candidates, classifications, and pending reviews

## Architecture

```
nhsn-reporting/
├── src/
│   ├── config.py                 # Environment configuration
│   ├── models.py                 # Domain models (HAICandidate, Classification, etc.)
│   ├── db.py                     # SQLite database operations
│   ├── monitor.py                # Main orchestration service
│   ├── runner.py                 # CLI entry point
│   │
│   ├── data/                     # Data access abstraction
│   │   ├── base.py               # Abstract base classes
│   │   ├── fhir_source.py        # FHIR R4 queries
│   │   ├── clarity_source.py     # Epic Clarity SQL
│   │   └── factory.py            # Source selection
│   │
│   ├── candidates/               # Rule-based detection
│   │   ├── base.py               # BaseCandidateDetector ABC
│   │   └── clabsi.py             # CLABSI criteria validation
│   │
│   ├── notes/                    # Clinical note processing
│   │   ├── retriever.py          # Unified note retrieval
│   │   ├── chunker.py            # Section extraction (A/P, ID consults)
│   │   └── deduplicator.py       # Copy-forward detection
│   │
│   ├── classifiers/              # LLM classification
│   │   ├── base.py               # BaseHAIClassifier ABC
│   │   ├── clabsi_classifier.py  # CLABSI prompts and logic
│   │   └── schemas.py            # Output validation schemas
│   │
│   ├── llm/                      # LLM backend abstraction
│   │   ├── base.py               # BaseLLMClient ABC
│   │   ├── ollama.py             # Local Ollama inference
│   │   ├── claude.py             # Claude API (requires BAA)
│   │   └── factory.py            # Backend selection
│   │
│   ├── review/                   # Human-in-the-loop workflow
│   │   ├── triage.py             # Confidence-based routing
│   │   └── queue.py              # Review queue management
│   │
│   └── alerters/                 # Notifications
│       └── teams.py              # Teams alerts for pending reviews
│
├── prompts/                      # Version-controlled prompt templates
│   └── clabsi_v1.txt
├── scripts/
│   └── generate_nhsn_test_data.py  # Test data generator
├── schema.sql                    # Database schema
├── .env.template                 # Configuration template
└── requirements.txt
```

## Configuration

Copy `.env.template` to `.env` and configure:

| Setting | Default | Description |
|---------|---------|-------------|
| `NOTE_SOURCE` | `fhir` | Data source: `fhir`, `clarity`, or `both` |
| `FHIR_BASE_URL` | `http://localhost:8081/fhir` | FHIR server endpoint |
| `LLM_BACKEND` | `ollama` | LLM backend: `ollama` or `claude` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `llama3.1:70b` | Model for classification |
| `AUTO_CLASSIFY_THRESHOLD` | `0.85` | Confidence above which to auto-confirm HAI |
| `IP_REVIEW_THRESHOLD` | `0.60` | Confidence below which requires manual review |
| `MIN_DEVICE_DAYS` | `2` | Minimum device days for CLABSI eligibility |
| `POLL_INTERVAL` | `300` | Seconds between monitoring cycles |

## CLABSI Detection Criteria

The module implements NHSN CLABSI surveillance criteria:

1. **Eligible BSI** - Positive blood culture with recognized pathogen
2. **Central Line Present** - Active central venous catheter (CVC, PICC, etc.)
3. **Device Days** - Line in place for ≥2 calendar days before culture
4. **Timing Window** - Culture collected while line in place or ≤1 day after removal
5. **No Alternative Source** - LLM analyzes notes to rule out other infection sources

### Common Contaminant Handling

For common skin contaminants (CoNS, Corynebacterium, Bacillus, etc.), the module requires two positive cultures from separate draws per NHSN criteria. Single contaminant cultures are automatically excluded.

## LLM Classification

The LLM analyzes clinical notes to determine:

- **Is there an alternative source?** (UTI, pneumonia, surgical site, etc.)
- **Does evidence support CLABSI?** (Line-related sepsis documentation, ID notes)
- **Is this MBI-LCBI?** (Mucosal barrier injury LCBI)

### Confidence Scoring

| Confidence | Action |
|------------|--------|
| ≥85% HAI | Auto-confirm, create NHSN event |
| 60-85% | Route to IP review queue |
| <60% | Route to manual review (complex case) |

## Dashboard Integration

The module integrates with the ASP Alerts dashboard:

- `/nhsn` - NHSN module overview
- `/nhsn/candidates` - All detected candidates
- `/nhsn/pending-review` - Cases awaiting IP review
- `/nhsn/events` - Confirmed NHSN events

## Test Data Generation

Generate realistic test scenarios for development:

```bash
cd scripts

# Generate all 9 test scenarios
python generate_nhsn_test_data.py

# Load to FHIR server
python generate_nhsn_test_data.py  # Uploads automatically
```

### Test Scenarios

1. **Clear CLABSI** - CoNS x2, central line 5 days, no alternative source
2. **Alternative Source (UTI)** - E. coli with documented UTI
3. **Alternative Source (Pneumonia)** - Pseudomonas with VAP documentation
4. **Line < 2 Days** - Central line only 1 day at culture (excluded)
5. **PICC Line CLABSI** - Staph aureus, PICC 4 days
6. **Single Contaminant** - Single CoNS culture (excluded, needs 2)
7. **Post-Removal** - CLABSI 1 day after line removal (within window)
8. **GI Source** - Enterococcus with documented colitis
9. **MBI-LCBI** - Strep viridans during mucositis (special category)

## NHSN Submission

The module supports two methods for submitting confirmed HAI events to NHSN:

### 1. CSV Export (Manual Entry)

Export confirmed events as a CSV file for manual entry into the NHSN web application or CSV import:

1. Navigate to `/nhsn/submission` in the dashboard
2. Select the date range (quarterly reporting periods)
3. Click "Export CSV" to download the data
4. Enter events manually into NHSN or use CSV import
5. Click "Mark as Submitted" to update the audit trail

### 2. DIRECT Protocol (Automated Submission)

Submit events directly to NHSN using the DIRECT secure messaging protocol. This generates HL7 CDA R2 compliant documents and sends them via your HISP (Health Information Service Provider).

#### DIRECT Configuration

Add these settings to your `.env` file:

```env
# Facility Info
NHSN_FACILITY_ID=your_facility_id
NHSN_FACILITY_NAME=Your Hospital Name

# HISP Settings (from your HISP provider)
NHSN_HISP_SMTP_SERVER=smtp.yourhisp.com
NHSN_HISP_SMTP_PORT=587
NHSN_HISP_SMTP_USERNAME=your_username
NHSN_HISP_SMTP_PASSWORD=your_password
NHSN_HISP_USE_TLS=true

# DIRECT Addresses
NHSN_SENDER_DIRECT_ADDRESS=yourorg@direct.yourhisp.com
NHSN_DIRECT_ADDRESS=nhsn_address_from_nhsn_application

# Optional: S/MIME Certificates (if required by HISP)
NHSN_SENDER_CERT_PATH=/path/to/your-cert.pem
NHSN_SENDER_KEY_PATH=/path/to/your-key.pem
```

#### Steps to Enable DIRECT Submission

1. **Get HISP Account**: Contact a Health Information Service Provider (e.g., [RosettaHealth](https://rosettahealth.com)) or another DIRECT-compliant HISP
2. **Sign up in NHSN**: Enable DIRECT submission in the NHSN application to get your NHSN DIRECT address
3. **Configure credentials**: Add the HISP settings above to your `.env` file
4. **Test connection**: Use the "Test Connection" button on the submission page to verify connectivity

Restart the service for changes to take effect:
```bash
sudo systemctl restart asp-alerts
```

### CDA Document Generation

The module generates HL7 CDA R2 compliant documents for BSI events based on the [HL7 Implementation Guide for NHSN HAI Reports](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=20). Documents include:

- Patient demographics (ID, DOB, gender)
- Event details (date, type, location)
- Pathogen information
- Device days
- Facility information

### Submission Audit Trail

All submissions (CSV exports, DIRECT submissions, manual marking) are logged with:
- Timestamp
- User/preparer name
- Date range covered
- Number of events
- Submission method and notes

View the audit log on the submission page at `/nhsn/submission`.

## Roadmap

- [x] CLABSI detection and classification
- [x] NHSN CSV export
- [x] NHSN DIRECT protocol submission
- [x] CDA document generation
- [x] Reports and analytics dashboard
- [ ] **Denominator data for rate calculation** - Central line days and/or patient days needed for CLABSI rate (CLABSIs per 1,000 central line days). Options:
  - Pull from Clarity flowsheet data (IP_FLWSHT_MEAS) where nurses document daily line presence
  - FHIR DeviceUseStatement with timing data (if reliably populated)
  - Manual entry on Submission page
  - Integration with existing line-day tracking system
  - *TODO: Determine how CCHMC currently tracks central line days*
- [ ] CAUTI detection (catheter-associated UTI)
- [ ] SSI detection (surgical site infection)
- [ ] VAE detection (ventilator-associated event)
- [ ] Epic SMART on FHIR integration

## Related Documentation

- [CDC/NHSN CLABSI Protocol](https://www.cdc.gov/nhsn/pdfs/pscmanual/4psc_clabscurrent.pdf)
- [NHSN CDA Submission Support Portal](https://www.cdc.gov/nhsn/cdaportal/importingdata.html)
- [HL7 CDA HAI Implementation Guide](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=20)
- [asp-alerts Main Documentation](../README.md)
- [Dashboard Documentation](../dashboard/README.md)
