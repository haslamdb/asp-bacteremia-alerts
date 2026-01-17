# ASP Alerts

Antimicrobial Stewardship Program (ASP) clinical decision support and alerting system. This monorepo contains modules for real-time monitoring, alerting, and analytics to support antimicrobial stewardship activities.

## Architecture

```
asp-alerts/
├── common/                     # Shared notification infrastructure
│   └── channels/               # Email, SMS, Teams webhooks
├── asp-bacteremia-alerts/      # Blood culture coverage monitoring (active)
└── [future modules]            # See roadmap below
```

## Current Modules

### asp-bacteremia-alerts

Real-time monitoring of blood culture results with antibiotic coverage assessment. Alerts ASP team when patients have positive cultures without appropriate antimicrobial coverage.

**Features:**
- FHIR R4 integration (HAPI FHIR for dev, Epic for production)
- Coverage rules for common pathogens (MRSA, VRE, Pseudomonas, Candida, etc.)
- Gram stain-based empiric coverage recommendations
- Multi-channel alerts: Email, Microsoft Teams

**[Documentation →](asp-bacteremia-alerts/README.md)**

## Shared Infrastructure

### common/channels

Reusable notification channels for all ASP modules:

- **EmailChannel** - SMTP email with HTML/text support
- **TeamsWebhookChannel** - Microsoft Teams via Workflows/Power Automate

## Future Modules (Roadmap)

| Priority | Module | Description |
|----------|--------|-------------|
| High | **Automated Metrics** | Auto-generate DOT reports, benchmarks, and quality metrics with AI-written narrative summaries |
| High | **Guideline Adherence** | Monitor prescribing against fever/neutropenia and other guidelines; report concordance |
| High | **De-escalation Alerts** | 48-72 hour alerts for broad-spectrum antibiotics with culture results and specific recommendations |
| High | **Bug-Drug Mismatch** | Identify when organisms are not covered by current therapy; suggest alternatives |
| Medium | **Predictive Risk Models** | ML models to identify patients at high risk for resistant infections or C. diff |
| Medium | **Duration Optimization** | Evidence-based duration recommendations at approval with reassessment triggers |
| Low | **Automated Approvals** | AI pre-screening of antibiotic approval requests with auto-approval or ASP referral (Phase 2) |

## Quick Start

```bash
# Clone the repo
git clone https://github.com/haslamdb/asp-alerts.git
cd asp-alerts

# Set up bacteremia alerts module
cd asp-bacteremia-alerts
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.template .env
# Edit .env with your FHIR server and notification settings

# Start local FHIR server (for development)
docker-compose up -d

# Run the monitor
python -m src.monitor
```

## Configuration

Each module uses environment variables for configuration. Copy `.env.template` to `.env` and configure:

- **FHIR Server**: Local HAPI FHIR or Epic production
- **Email**: SMTP server credentials
- **Teams**: Workflows webhook URL

## Development

### Prerequisites

- Python 3.11+
- Docker (for local FHIR server)
- Access to Epic FHIR API (for production)

### Testing

```bash
# Set up test data in local FHIR server
python -m src.setup_test_data

# Run monitor once
python -m src.monitor

# Run continuous monitoring
python -m src.monitor --continuous
```

### Project Structure

```
asp-bacteremia-alerts/
├── src/
│   ├── alerters/          # Notification handlers
│   ├── config.py          # Environment configuration
│   ├── coverage_rules.py  # Antibiotic coverage logic
│   ├── fhir_client.py     # FHIR API client
│   ├── matcher.py         # Coverage assessment
│   ├── models.py          # Data models
│   └── monitor.py         # Main monitoring service
├── tests/                 # Unit tests
├── docs/                  # Documentation
└── docker-compose.yml     # Local FHIR server
```

## License

Internal use - Cincinnati Children's Hospital Medical Center

## Contact

ASP Informatics Team
