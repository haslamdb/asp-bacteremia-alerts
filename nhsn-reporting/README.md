# NHSN Reporting Module

Automated NHSN data aggregation and submission for AEGIS. This module handles NHSN reporting workflows including Antibiotic Use (AU), Antimicrobial Resistance (AR), and HAI event submission.

## Overview

The NHSN Reporting module provides:

1. **AU Reporting** - Antibiotic Usage tracking (Days of Therapy, DOT/1000 patient days)
2. **AR Reporting** - Antimicrobial Resistance phenotype detection and tracking
3. **HAI Submission** - CDA document generation and DIRECT protocol submission for confirmed HAIs
4. **Denominator Calculations** - Patient days, device days by location

> **Note:** HAI candidate detection (CLABSI, SSI screening) and IP review workflow have been moved to the **[hai-detection](../hai-detection/README.md)** module. This module receives confirmed HAI events for NHSN submission.

## Architecture

```
nhsn-reporting/
├── src/
│   ├── config.py                 # Environment configuration
│   ├── models.py                 # Domain models (NHSNEvent, AU/AR data)
│   ├── db.py                     # SQLite database operations
│   │
│   ├── data/                     # Data extraction
│   │   ├── au_extractor.py       # Antibiotic Usage extraction from Clarity
│   │   ├── ar_extractor.py       # Antimicrobial Resistance extraction
│   │   └── denominator.py        # Patient/device day calculations
│   │
│   ├── cda/                      # CDA document generation
│   │   └── generator.py          # HL7 CDA R2 HAI documents
│   │
│   └── direct/                   # NHSN submission
│       └── client.py             # DIRECT protocol HISP client
│
├── tests/
│   ├── test_au_extractor.py
│   └── test_ar_extractor.py
├── schema.sql                    # Database schema
├── .env.template                 # Configuration template
└── requirements.txt
```

## Quick Start

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

### Viewing Results

Results appear in the AEGIS dashboard:

1. Start the dashboard: `cd ../dashboard && flask run`
2. Visit http://localhost:5000/nhsn-reporting for AU/AR data and NHSN submission
3. Visit http://localhost:5000/hai-detection for HAI candidate review (separate module)

## Configuration

Copy `.env.template` to `.env` and configure:

| Setting | Default | Description |
|---------|---------|-------------|
| `NHSN_DB_PATH` | `~/.aegis/nhsn.db` | Database path (shared with hai-detection) |
| `CLARITY_CONNECTION_STRING` | | Epic Clarity database connection |
| `NHSN_FACILITY_ID` | | NHSN facility identifier |
| `NHSN_FACILITY_NAME` | | Hospital name for submissions |

## AU/AR Reporting

The NHSN Antibiotic Use (AU) and Antimicrobial Resistance (AR) module provides automated tracking and reporting of antimicrobial consumption and resistance patterns per CDC/NHSN methodology.

### Dashboard

Access AU/AR data through the NHSN Reporting dashboard at `/nhsn-reporting/`:

| Page | URL | Description |
|------|-----|-------------|
| **Dashboard** | `/nhsn-reporting/` | Overview with AU, AR, and HAI summaries |
| **AU Detail** | `/nhsn-reporting/au` | Days of therapy by location and antimicrobial |
| **AR Detail** | `/nhsn-reporting/ar` | Resistance phenotypes and rates by organism |
| **HAI Detail** | `/nhsn-reporting/hai` | Confirmed HAI events by type and location |
| **Denominators** | `/nhsn-reporting/denominators` | Patient days and device days by location |
| **Submission** | `/nhsn-reporting/submission` | Unified NHSN submission (AU, AR, HAI) |
| **Help** | `/nhsn-reporting/help` | Documentation and demo guide |

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
# Visit http://localhost:5000/nhsn-reporting/
```

The demo data generator creates:
- 6 months of antibiotic administrations across ICU/medical/surgical units
- Culture data with realistic resistance patterns (20-40% resistance rates)
- Patient days with device utilization (central lines, catheters, ventilators)
- NHSN-compliant location codes and antimicrobial categories

## NHSN Submission

The unified submission page at `/nhsn-reporting/submission` supports submission of AU, AR, and HAI data. Use the tabs to switch between data types.

### Submission Methods

#### 1. CSV Export (Manual Entry)

Export data as a CSV file for manual entry into the NHSN web application or CSV import:

1. Navigate to `/nhsn-reporting/submission` in the dashboard
2. Select the data type tab (AU, AR, or HAI)
3. Select the date range (monthly for AU, quarterly for AR/HAI)
4. Click "Export CSV" to download the data
5. Enter data manually into NHSN or use CSV import
6. Click "Mark as Submitted" to update the audit trail

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
sudo systemctl restart aegis
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

View the audit log on the submission page at `/nhsn-reporting/submission`.

## Denominator Calculations

The module calculates denominators required for NHSN rate calculations:

| Metric | Formula | Example |
|--------|---------|---------|
| **CLABSI Rate** | (CLABSI count / central line days) × 1,000 | 2 CLABSIs / 500 line days = 4.0 |
| **CAUTI Rate** | (CAUTI count / catheter days) × 1,000 | 1 CAUTI / 300 catheter days = 3.3 |
| **VAE Rate** | (VAE count / ventilator days) × 1,000 | 1 VAE / 200 vent days = 5.0 |

Data sources for denominators:
- Aggregate from FHIR DeviceUseStatement timing data
- Pull from Clarity flowsheet data (IP_FLWSHT_MEAS)
- Integration with existing line-day tracking system

## Related Modules

- **[hai-detection](../hai-detection/README.md)** - HAI candidate detection, LLM extraction, IP review workflow
- **common** - Shared utilities (alert store, channels)
- **dashboard** - Web interface

## Testing

```bash
cd nhsn-reporting
pytest tests/
```

## Roadmap

- [x] AU/AR reporting module with DOT, resistance phenotypes, denominators
- [x] AU/AR dashboard with detail views and export
- [x] NHSN CSV export
- [x] NHSN DIRECT protocol submission
- [x] CDA document generation
- [x] Unified submission page for AU, AR, HAI
- [ ] Epic SMART on FHIR integration
- [ ] Automated monthly/quarterly submission scheduling

## Related Documentation

- [CDC/NHSN AU/AR Protocol](https://www.cdc.gov/nhsn/pdfs/pscmanual/11pscaurcurrent.pdf)
- [NHSN CDA Submission Support Portal](https://www.cdc.gov/nhsn/cdaportal/importingdata.html)
- [HL7 CDA HAI Implementation Guide](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=20)
- [AEGIS Main Documentation](../README.md)
- [HAI Detection Module](../hai-detection/README.md)
