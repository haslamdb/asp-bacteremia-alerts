# NHSN HAI Reporting Module

Automated NHSN Healthcare-Associated Infection (HAI) detection and classification for asp-alerts. This module uses rule-based screening combined with LLM-assisted extraction and deterministic NHSN rules to identify CLABSI (Central Line-Associated Bloodstream Infection) candidates and route them through an IP review workflow.

## Overview

The NHSN reporting module implements a four-stage workflow that separates **fact extraction** (LLM) from **classification logic** (rules engine):

1. **Rule-Based Screening** - Identifies HAI candidates based on NHSN criteria (BSI + central line + timing requirements)
2. **LLM Extraction** - Extracts clinical facts from notes (symptoms, alternate sources, MBI factors)
3. **Rules Engine** - Applies deterministic NHSN criteria to extracted facts
4. **IP Review** - ALL candidates routed to Infection Prevention for final decision (LLM provides classification and confidence, IP confirms or rejects)

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
│   LLM Extraction    │  Extract from notes:
│  (Ollama llama3.1)  │  - Symptoms (fever, WBC, etc.)
└─────────────────────┘  - Alternate infection sources
         │               - MBI factors (mucositis, neutropenia)
         │               - Line assessment findings
    ClinicalExtraction   - Contamination signals
         │
         ▼
┌─────────────────────┐
│    Rules Engine     │  Apply NHSN decision tree:
│   (Deterministic)   │  1. Basic eligibility
└─────────────────────┘  2. MBI-LCBI check
         │               3. Secondary BSI check
         │               4. Contamination check
         │               5. Default to CLABSI
         │
         ▼
┌─────────────────────┐
│    IP Review        │  ALL candidates reviewed by IP
│  (Human Decision)   │  LLM provides classification + confidence
└─────────────────────┘  IP makes final confirm/reject decision
         │
         ▼
┌─────────────────────┐
│    NHSN Events      │  Confirmed HAIs ready for submission
└─────────────────────┘
```

### Why Separate Extraction from Classification?

The key architectural principle: **The LLM extracts FACTS, the rules engine applies LOGIC.**

| Component | Role | Characteristics |
|-----------|------|-----------------|
| LLM Extraction | "What is documented?" | Reads notes, extracts structured clinical data |
| Rules Engine | "What does NHSN say?" | Applies deterministic criteria, fully auditable |

This separation provides:
- **Transparency**: Every classification decision can be traced to specific rules
- **Auditability**: IP can see exactly which criteria triggered the classification
- **Maintainability**: NHSN criteria updates only require rule changes, not prompt engineering
- **Testability**: Rules can be unit tested independently of LLM behavior

## Features

- **CLABSI Detection** - Rule-based screening per CDC/NHSN criteria
- **Note Processing** - Retrieves clinical notes from FHIR or Clarity
- **LLM Classification** - Local Ollama inference (PHI-safe, no BAA required)
- **IP Review Workflow** - ALL candidates go to IP for final decision; LLM provides classification + confidence as decision support
- **IP Review Dashboard** - Web interface showing pending reviews, confirmed HAI, and confirmed not-HAI counts
- **Audit Trail** - Full logging of all classifications, IP decisions, and override tracking
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
│   │   ├── denominator.py        # Central line days calculation
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
│   ├── extraction/               # LLM-based fact extraction (NEW)
│   │   └── clabsi_extractor.py   # Extracts clinical facts from notes
│   │
│   ├── rules/                    # Deterministic NHSN rules (NEW)
│   │   ├── schemas.py            # ClinicalExtraction, StructuredCaseData
│   │   ├── nhsn_criteria.py      # NHSN reference data (organisms, thresholds)
│   │   └── clabsi_engine.py      # NHSN decision tree implementation
│   │
│   ├── classifiers/              # Classification orchestration
│   │   ├── base.py               # BaseHAIClassifier ABC
│   │   ├── clabsi_classifier.py  # Legacy: LLM-only classification
│   │   └── clabsi_classifier_v2.py # NEW: Extraction + Rules architecture
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
│   ├── clabsi_v1.txt             # Classification prompt (legacy)
│   └── clabsi_extraction_v1.txt  # Extraction prompt (current)
├── mock_clarity/                 # Mock Clarity database for development
├── scripts/
│   ├── generate_nhsn_test_data.py  # FHIR test data generator
│   └── test_mock_clarity.py      # Mock Clarity integration tests
├── tests/
│   └── test_clabsi_rules.py      # Rules engine unit tests
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
| `MIN_DEVICE_DAYS` | `2` | Minimum device days for CLABSI eligibility |
| `POLL_INTERVAL` | `300` | Seconds between monitoring cycles |

> **Note:** All candidates are routed to IP review regardless of LLM confidence. The confidence score is displayed to IP as decision support but does not affect routing.

## CLABSI Detection Criteria

The module implements NHSN CLABSI surveillance criteria:

1. **Eligible BSI** - Positive blood culture with recognized pathogen
2. **Central Line Present** - Active central venous catheter (CVC, PICC, etc.)
3. **Device Days** - Line in place for ≥2 calendar days before culture
4. **Timing Window** - Culture collected while line in place or ≤1 day after removal
5. **No Alternative Source** - LLM analyzes notes to rule out other infection sources

### Common Contaminant Handling

For common skin contaminants (CoNS, Corynebacterium, Bacillus, etc.), the module requires two positive cultures from separate draws per NHSN criteria. Single contaminant cultures are automatically excluded.

## Classification Pipeline

Classification uses a two-stage pipeline: **LLM Extraction** followed by **Rules Engine**.

### Stage 1: LLM Extraction

The LLM (`llama3.1:70b` via Ollama) reads clinical notes and extracts structured facts:

```python
ClinicalExtraction:
  alternate_infection_sites: [...]  # Pneumonia, UTI, SSTI, etc.
  symptoms:                         # Fever, WBC, hypotension
  mbi_factors:                      # Mucositis, neutropenia, HSCT status
  line_assessment:                  # Exit site findings, line suspicion
  contamination:                    # Signals team treated as contaminant
  documentation_quality:            # poor/limited/adequate/detailed
```

The LLM is NOT making a classification decision - only answering factual questions about what is documented in the notes.

### Stage 2: Rules Engine

The rules engine applies deterministic NHSN criteria:

1. **Basic Eligibility** - Line present ≥2 days, not POA
2. **MBI-LCBI Check** - Eligible organism + eligible patient + mucosal injury
3. **Secondary BSI Check** - Same organism at another documented site
4. **Contamination Check** - Single culture with common commensal
5. **Default to CLABSI** - If no exclusions apply

Each step produces auditable reasoning that IP can review.

### Classification Outputs

| Classification | Meaning |
|----------------|---------|
| `CLABSI` | Central line-associated BSI (reportable HAI) |
| `MBI_LCBI` | Mucosal barrier injury LCBI (not CLABSI, separate category) |
| `SECONDARY_BSI` | BSI secondary to infection at another site |
| `CONTAMINATION` | Likely contamination (single commensal culture) |
| `NOT_ELIGIBLE` | Doesn't meet basic eligibility (line days, timing) |

### IP Review Workflow

**All classified candidates go to IP review.** The LLM provides a classification and confidence score as decision support, but IP always makes the final determination. This ensures:
- Human oversight on all HAI determinations
- Consistent application of clinical judgment
- Override tracking for LLM quality assessment

When IP submits a final decision (Confirmed HAI or Confirmed Not HAI), any prior incomplete reviews (e.g., "needs more info") are automatically superseded.

**IP Decision Options:**
- **Confirmed** - CLABSI confirmed, will be reported to NHSN
- **Not CLABSI** - Rejected (secondary source, MBI-LCBI, contamination, etc.)
- **Needs More Info** - Keep in queue for additional review (does not close the case)

## Dashboard Integration

The module integrates with the ASP Alerts dashboard at `/nhsn`:

**Dashboard Stats:**
- **Pending Review** (primary) - Cases awaiting IP decision
- **Confirmed HAI** - CLABSI cases confirmed by IP
- **Confirmed Not HAI** - Cases rejected by IP (secondary source, MBI-LCBI, etc.)
- **NHSN Events** - Events ready for NHSN submission

**Pages:**
- `/nhsn` - Overview with stats and recent activity
- `/nhsn/reviews` - IP Review Queue (primary workflow)
- `/nhsn/candidates` - All active candidates
- `/nhsn/history` - Resolved cases (confirmed and rejected)
- `/nhsn/reports` - Analytics and LLM quality metrics
- `/nhsn/submission` - NHSN reporting (CSV export or DIRECT protocol)

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

## Synthetic Patient Data Generation (Synthea)

For realistic synthetic patient data with device information (central lines, urinary catheters, ventilators), use Synthea with our custom modules. This creates FHIR data for real-time HAI detection and syncs to Clarity for denominator calculations.

### Prerequisites

- Java 11+ (for Synthea)
- Synthea JAR at `../tools/synthea/synthea-with-dependencies.jar`
- Custom modules in `../tools/synthea/modules/`

### Custom Synthea Modules

We provide three custom modules that generate device data needed for HAI detection:

| Module | Probability | Device Types | Dwell Time |
|--------|-------------|--------------|------------|
| `central_line.json` | 30% | CVC, PICC, Tunneled catheter | 3-21 days |
| `urinary_catheter.json` | 25% | Foley catheter | 2-14 days |
| `mechanical_ventilation.json` | 15% | ETT, Ventilator, Tracheostomy | 2-14+ days |

### Step 1: Generate Synthea FHIR Data

```bash
cd ../tools/synthea

# Generate 50 patients from Massachusetts
java -jar synthea-with-dependencies.jar \
    -c synthea.properties \
    -d modules \
    -p 50 \
    Massachusetts

# Output goes to ./output/fhir/
```

**Command Options:**
- `-c synthea.properties` - Use our custom configuration
- `-d modules` - Load custom device modules
- `-p 50` - Generate 50 patients
- `Massachusetts` - State for demographic data (use any US state)

**Filter by Age:**
```bash
# Adults only (18-85)
java -jar synthea-with-dependencies.jar -c synthea.properties -d modules -p 50 -a 18-85 Massachusetts

# Pediatric (1-17)
java -jar synthea-with-dependencies.jar -c synthea.properties -d modules -p 50 -a 1-17 Massachusetts

# Neonates (0-1)
java -jar synthea-with-dependencies.jar -c synthea.properties -d modules -p 20 -a 0-1 Massachusetts
```

**Filter by Gender:**
```bash
java -jar synthea-with-dependencies.jar -c synthea.properties -d modules -p 50 -g F Massachusetts  # Female only
java -jar synthea-with-dependencies.jar -c synthea.properties -d modules -p 50 -g M Massachusetts  # Male only
```

### Step 2: Sync to Clarity Database

After generating FHIR data, sync to the mock Clarity database to enable denominator calculations with matching patient MRNs:

```bash
cd nhsn-reporting

# Sync Synthea output to Clarity
python scripts/synthea_to_clarity.py \
    --fhir-dir ../tools/synthea/output/fhir \
    --db-path mock_clarity.db

# Clear existing and re-import
python scripts/synthea_to_clarity.py \
    --fhir-dir ../tools/synthea/output/fhir \
    --db-path mock_clarity.db \
    --clear-existing
```

**What the sync does:**
1. Reads all FHIR bundles from Synthea output
2. Extracts patient MRNs, encounters, and device placements
3. Maps SNOMED device codes to Clarity flowsheet IDs
4. Creates daily flowsheet measurements for device presence
5. Assigns encounters to NHSN locations based on encounter type

### Step 3: Load FHIR Data to Server

Load the generated FHIR bundles to your FHIR server for real-time HAI detection:

```bash
# Load to local HAPI FHIR
for f in ../tools/synthea/output/fhir/*.json; do
    curl -X POST "http://localhost:8081/fhir" \
        -H "Content-Type: application/fhir+json" \
        -d @"$f"
done
```

### Architecture: FHIR + Clarity Integration

The hybrid approach uses:
- **FHIR** for real-time HAI detection (blood cultures, device data, clinical notes)
- **Clarity** for aggregate denominator calculations (line days, patient days by unit)

```
                    Synthea Generator
                           │
                           ▼
                    FHIR Bundles (.json)
                     ┌─────┴─────┐
                     │           │
                     ▼           ▼
              FHIR Server    synthea_to_clarity.py
                     │           │
                     ▼           ▼
            Real-time HAI   Clarity Database
             Detection     (Denominators)
                     │           │
                     └─────┬─────┘
                           │
                           ▼
                    NHSN Rate Calculation
                    (HAI count / device days)
```

**Key benefit:** Patient MRNs match between FHIR and Clarity, allowing correlation of detected HAIs with denominator data for rate calculations.

### Example: Full Workflow

```bash
# 1. Generate patients
cd ../tools/synthea
java -jar synthea-with-dependencies.jar -c synthea.properties -d modules -p 100 Massachusetts

# 2. Sync to Clarity
cd ../nhsn-reporting
python scripts/synthea_to_clarity.py \
    --fhir-dir ../tools/synthea/output/fhir \
    --db-path mock_clarity.db \
    --clear-existing

# 3. Load to FHIR server
for f in ../tools/synthea/output/fhir/*.json; do
    curl -X POST "http://localhost:8081/fhir" \
        -H "Content-Type: application/fhir+json" \
        -d @"$f" 2>/dev/null
done

# 4. Run HAI detection
python -m src.runner --once

# 5. Calculate rates
python -c "
from src.data.denominator import DenominatorCalculator
calc = DenominatorCalculator('mock_clarity.db')
print(calc.get_denominator_summary('2024-01-01', '2024-12-31'))
"
```

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

## AU/AR Reporting Module

The NHSN Antibiotic Use (AU) and Antimicrobial Resistance (AR) module provides automated tracking and reporting of antimicrobial consumption and resistance patterns per CDC/NHSN methodology.

### Dashboard

Access the AU/AR dashboard at `/au-ar/` with the following pages:

| Page | URL | Description |
|------|-----|-------------|
| **Dashboard** | `/au-ar/` | Overview with AU, AR, and denominator summaries |
| **AU Detail** | `/au-ar/au` | Days of therapy by location and antimicrobial |
| **AR Detail** | `/au-ar/ar` | Resistance phenotypes and rates by organism |
| **Denominators** | `/au-ar/denominators` | Patient days and device days by location |
| **Submission** | `/au-ar/submission` | NHSN export (CSV or CDA) |
| **Help** | `/au-ar/help` | Documentation and demo guide |

### Antibiotic Usage (AU)

Tracks antimicrobial consumption metrics:

- **Days of Therapy (DOT)**: Number of days a patient receives an antimicrobial
- **DOT/1000 Patient Days**: Rate normalized to patient census
- **Defined Daily Doses (DDD)**: WHO-standardized dose metrics (optional)

Data is aggregated by:
- NHSN antimicrobial category (e.g., 3rd gen cephalosporins, carbapenems)
- NHSN location code (e.g., IN:ACUTE:PEDS:M/S)
- Month/Year

### Antimicrobial Resistance (AR)

Tracks resistance patterns using the **first-isolate rule**:

- Only one isolate per patient per organism per quarter
- Prevents overweighting from repeat cultures
- Matches NHSN deduplication methodology

**Phenotype Detection:**
| Phenotype | Organisms | Antibiotics Tested |
|-----------|-----------|-------------------|
| MRSA | S. aureus | Oxacillin/Cefoxitin |
| VRE | E. faecalis, E. faecium | Vancomycin |
| ESBL | E. coli, K. pneumoniae | 3rd gen cephalosporins |
| CRE | Enterobacterales | Carbapenems |
| CRPA | P. aeruginosa | Carbapenems |

### Data Sources

AU/AR data is extracted from Epic Clarity:

| Data Element | Clarity Tables | Description |
|--------------|----------------|-------------|
| Antimicrobial admin | `MAR_ADMIN_INFO` | Medication administration records |
| Orders | `ORDER_MED` | Antibiotic orders with NHSN codes |
| Cultures | `ORDER_RESULTS`, `ORDER_SENSITIVITY` | Culture results and susceptibilities |
| Patient days | `PAT_ENC_HSP`, `IP_FLWSHT_MEAS` | Census by location |

### Demo Data Generation

Generate realistic demo data with the mock Clarity database:

```bash
cd nhsn-reporting

# Generate demo data for 2024-2025
python scripts/generate_demo_data.py

# View in dashboard
cd ../dashboard && flask run
# Visit http://localhost:5000/au-ar/
```

The demo data generator creates:
- 6 months of antibiotic administrations across ICU/medical/surgical units
- Culture data with realistic resistance patterns (20-40% resistance rates)
- Patient days with device utilization (central lines, catheters, ventilators)
- NHSN-compliant location codes and antimicrobial categories

### NHSN Submission

Export AU/AR data for NHSN submission:

1. **CSV Export**: Download monthly data for manual entry
2. **CDA Generation**: HL7 CDA documents for automated submission

Navigate to `/au-ar/submission` to access export options.

## Roadmap

- [x] CLABSI detection and classification
- [x] LLM extraction + rules engine architecture
- [x] IP review workflow (all candidates routed to IP)
- [x] Override tracking for LLM quality assessment
- [x] Source attribution for evidence (note type, date, author)
- [x] NHSN CSV export
- [x] NHSN DIRECT protocol submission
- [x] CDA document generation
- [x] Reports and analytics dashboard
- [x] Stats reset with each NHSN submission
- [x] AU/AR reporting module with DOT, resistance phenotypes, denominators
- [x] AU/AR dashboard with detail views and export
- [ ] CAUTI detection (catheter-associated UTI)
- [ ] SSI detection (surgical site infection)
- [ ] VAE detection (ventilator-associated event)
- [ ] Epic SMART on FHIR integration

## Future Work

### CLABSI Rate Denominator ([#1](https://github.com/haslamdb/asp-alerts/issues/1))

Central line days aggregation needed for CLABSI rate calculation:
- **Formula**: CLABSI Rate = (CLABSI count / central line days) × 1,000
- **Data Source**: FHIR DeviceUseStatement (already captured for candidate detection)
- **Implementation**: `src/data/denominator.py`

Options for line day tracking:
- Aggregate from FHIR DeviceUseStatement timing data
- Pull from Clarity flowsheet data (IP_FLWSHT_MEAS)
- Manual entry on Submission page
- Integration with existing line-day tracking system

### ~~Clarity Integration for AU/AR Reporting~~ ✅ Implemented

See **AU/AR Reporting** section below. The AU/AR module is now fully implemented with:
- Antibiotic Usage (AU) reporting with DOT/1000 patient days
- Antimicrobial Resistance (AR) reporting with first-isolate rule
- Denominator calculations from Clarity flowsheet data
- Dashboard integration at `/au-ar/`

## Related Documentation

- [CDC/NHSN CLABSI Protocol](https://www.cdc.gov/nhsn/pdfs/pscmanual/4psc_clabscurrent.pdf)
- [NHSN CDA Submission Support Portal](https://www.cdc.gov/nhsn/cdaportal/importingdata.html)
- [HL7 CDA HAI Implementation Guide](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=20)
- [asp-alerts Main Documentation](../README.md)
- [Dashboard Documentation](../dashboard/README.md)
