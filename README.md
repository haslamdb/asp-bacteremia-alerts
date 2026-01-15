# ASP Bacteremia Alerts

Antimicrobial Stewardship Program (ASP) clinical decision support tool that monitors blood culture results and alerts when patients may have inadequate antibiotic coverage.

## Features

- **FHIR-native**: Queries blood cultures and medications via HL7 FHIR R4 API
- **Dual-environment**: Develop locally with HAPI FHIR, deploy to Epic with zero code changes
- **Clinical rules engine**: Extensible organism/antibiotic coverage matching
- **Pluggable alerting**: Console, email, SMS (extensible)
- **Comprehensive test suite**: Unit tests and integration test scenarios

## Quick Start

```bash
# Start local FHIR server
docker compose up -d

# Set up Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Load test data
python -m src.setup_test_data

# Run monitor
python -m src.monitor
```

## Example Output

```
======================================================================
BACTEREMIA COVERAGE ALERT
======================================================================
  Patient:     Alice Johnson (TEST001)
  Location:    Unknown
  Organism:    MRSA - Methicillin resistant Staphylococcus aureus
  Current Abx: Cefazolin 2g IV
  Status:      INADEQUATE
  Recommend:   Add vancomycin or daptomycin for MRSA coverage
======================================================================
```

## Project Structure

```
asp-bacteremia-alerts/
├── docker-compose.yml      # HAPI FHIR server
├── requirements.txt        # Python dependencies
├── .env                    # Environment configuration
│
├── src/
│   ├── config.py           # Configuration management
│   ├── fhir_client.py      # FHIR API abstraction (HAPI/Epic)
│   ├── models.py           # Domain models
│   ├── coverage_rules.py   # Clinical knowledge base
│   ├── matcher.py          # Coverage assessment logic
│   ├── monitor.py          # Main monitoring service
│   ├── setup_test_data.py  # Test scenario generator
│   └── alerters/           # Alert delivery plugins
│
├── tests/                  # Unit tests
├── docs/                   # Documentation
└── keys/                   # OAuth keys (gitignored)
```

## Supported Organisms (Pilot)

| Category | Examples | Key Antibiotics |
|----------|----------|-----------------|
| MRSA | Methicillin-resistant S. aureus | Vancomycin, Daptomycin |
| VRE | Vancomycin-resistant Enterococcus | Daptomycin, Linezolid |
| Pseudomonas | P. aeruginosa | Cefepime, Pip-tazo, Meropenem |
| Candida | C. albicans, C. glabrata | Micafungin, Fluconazole |
| Gram-negative | E. coli, Klebsiella | Ceftriaxone, Cefepime |

See [docs/clinical-rules.md](docs/clinical-rules.md) for complete coverage rules.

## Notifications

Alerts are routed by severity:

| Severity | Organisms | Channels |
|----------|-----------|----------|
| **CRITICAL** | MRSA, VRE, Pseudomonas, Candida | Console + Email + SMS |
| **WARNING** | Other gram-negatives | Console + Email |

See [docs/notifications.md](docs/notifications.md) for setup details.

## Configuration

Copy `.env.template` to `.env` and configure:

```bash
# Local development (default)
FHIR_BASE_URL=http://localhost:8081/fhir

# Epic production
EPIC_FHIR_BASE_URL=https://epicfhir.your-hospital.org/api/FHIR/R4
EPIC_CLIENT_ID=your-client-id
EPIC_PRIVATE_KEY_PATH=./keys/epic_private.pem

# Email alerts
SMTP_SERVER=smtp.hospital.org
ALERT_EMAIL_TO=asp-team@hospital.org

# SMS alerts (Twilio)
TWILIO_ACCOUNT_SID=ACxxxx
TWILIO_AUTH_TOKEN=xxxx
TWILIO_FROM_NUMBER=+15135551234
ALERT_SMS_TO_NUMBERS=+15135559876
```

## Documentation

- [Architecture](docs/architecture.md) - System design and components
- [Setup Guide](docs/setup.md) - Installation and configuration
- [Clinical Rules](docs/clinical-rules.md) - Coverage logic documentation
- [Notifications](docs/notifications.md) - Email and SMS alert setup

## Development

```bash
# Run tests
pytest tests/ -v

# Run monitor in continuous mode
python -m src.monitor --continuous

# Check FHIR server status
curl http://localhost:8081/fhir/metadata
```

## Switching to Production

1. Obtain Epic FHIR credentials from your IT department
2. Place private key in `keys/epic_private.pem`
3. Update `.env` with Epic configuration
4. Run - the system automatically uses Epic when configured

## Requirements

- Python 3.11+
- Docker (for local FHIR server)
- Epic FHIR API access (for production)

## License

MIT

## Disclaimer

This software is for research and development purposes. Clinical decision support tools require validation and approval before use in patient care. The coverage rules are simplified and should be reviewed by infectious disease specialists before clinical deployment.
