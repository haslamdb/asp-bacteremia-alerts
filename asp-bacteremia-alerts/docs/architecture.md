# Architecture

## Overview

The ASP Bacteremia Alerts system monitors blood culture results via FHIR API and checks whether patients have adequate antibiotic coverage for identified organisms. When coverage gaps are detected, alerts are generated for the antimicrobial stewardship team.

## System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                     ASP Bacteremia Alerts                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │              │    │              │    │              │       │
│  │ FHIR Client  │───▶│   Monitor    │───▶│   Alerter    │       │
│  │              │    │              │    │              │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│         │                   │                                    │
│         │                   ▼                                    │
│         │           ┌──────────────┐                            │
│         │           │   Matcher    │                            │
│         │           └──────────────┘                            │
│         │                   │                                    │
│         │                   ▼                                    │
│         │           ┌──────────────┐                            │
│         │           │  Coverage    │                            │
│         │           │   Rules      │                            │
│         │           └──────────────┘                            │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────┐                                               │
│  │  HAPI FHIR   │  (Development)                                │
│  │    Server    │                                               │
│  └──────────────┘                                               │
│         or                                                       │
│  ┌──────────────┐                                               │
│  │  Epic FHIR   │  (Production)                                 │
│  │     API      │                                               │
│  └──────────────┘                                               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### FHIR Client (`src/fhir_client.py`)

Abstraction layer that provides a unified interface for FHIR operations. Supports two backends:

- **HAPIFHIRClient**: For local development against HAPI FHIR server (no authentication)
- **EpicFHIRClient**: For production use with Epic's FHIR API (OAuth 2.0 JWT bearer flow)

The `get_fhir_client()` factory function automatically selects the appropriate client based on environment configuration.

Key methods:
- `get_recent_blood_cultures()` - Query DiagnosticReports with LOINC code 600-7
- `get_active_medication_requests()` - Get active antibiotic orders for a patient
- `get_patient()` - Retrieve patient demographics

### Monitor (`src/monitor.py`)

The main orchestration component that:
1. Polls FHIR server for new blood culture results
2. Parses FHIR resources into domain models
3. Retrieves active antibiotics for each patient
4. Invokes the matcher to assess coverage
5. Generates alerts for inadequate coverage

Supports both single-run and continuous monitoring modes.

### Matcher (`src/matcher.py`)

Core business logic that:
1. Categorizes organisms from culture results
2. Extracts RxNorm codes from antibiotic orders
3. Compares current antibiotics against coverage rules
4. Returns a `CoverageAssessment` with status and recommendations

### Coverage Rules (`src/coverage_rules.py`)

Clinical knowledge base encoding:
- Organism categories (MRSA, VRE, Pseudomonas, Candida, etc.)
- Which antibiotics provide adequate coverage for each organism
- Which antibiotics are known to be inadequate
- Recommended actions for coverage gaps

Uses RxNorm codes for medication matching.

### Alerters (`src/alerters/`)

Pluggable alert delivery:
- **ConsoleAlerter**: Prints to stdout (development/testing)
- **EmailAlerter**: Sends email notifications
- **TeamsAlerter**: Sends Microsoft Teams notifications with action buttons

### Models (`src/models.py`)

Domain models using Python dataclasses:
- `Patient` - Patient demographics
- `Antibiotic` - Active antibiotic order
- `CultureResult` - Blood culture result
- `CoverageAssessment` - Result of coverage analysis
- `Alert` - Generated alert

## Data Flow

1. **Poll**: Monitor queries FHIR for recent DiagnosticReports (blood cultures)
2. **Parse**: FHIR resources converted to domain models
3. **Enrich**: For each culture, fetch patient info and active medications
4. **Categorize**: Organism text parsed to determine category (MRSA, Pseudomonas, etc.)
5. **Match**: Current antibiotics compared against coverage rules
6. **Assess**: Coverage status determined (adequate/inadequate/unknown)
7. **Alert**: If inadequate, generate alert with recommendation

## FHIR Resources Used

| Resource | Purpose | Key Fields |
|----------|---------|------------|
| DiagnosticReport | Blood culture results | code (LOINC 600-7), conclusion, conclusionCode, subject |
| Patient | Patient demographics | identifier (MRN), name, birthDate |
| MedicationRequest | Active antibiotic orders | medicationCodeableConcept (RxNorm), status, subject |

## Configuration

Environment variables (`.env`):

```bash
# Local development
FHIR_BASE_URL=http://localhost:8081/fhir

# Epic production
EPIC_FHIR_BASE_URL=https://epicfhir.example.org/api/FHIR/R4
EPIC_CLIENT_ID=your-client-id
EPIC_PRIVATE_KEY_PATH=./keys/epic_private.pem

# Monitoring
POLL_INTERVAL=300  # seconds
```

## Switching Between Environments

The system automatically uses Epic when `EPIC_FHIR_BASE_URL` is set:

```python
def get_fhir_client() -> FHIRClient:
    if config.is_epic_configured():
        return EpicFHIRClient()
    else:
        return HAPIFHIRClient()
```

No code changes required - just update environment variables.

## Security Considerations

- Private keys for Epic OAuth stored in `keys/` directory (gitignored)
- No PHI stored locally - all data remains in FHIR server
- Token refresh handled automatically with 60-second buffer
- HTTPS enforced for production Epic endpoints
