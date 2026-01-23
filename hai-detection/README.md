# HAI Detection Module

Healthcare-Associated Infection (HAI) candidate detection, LLM-assisted classification, and IP review workflow.

## Overview

The HAI Detection module identifies potential HAIs from clinical data and assists Infection Preventionists (IPs) in classifying them. Currently supported HAI types:

- **CLABSI** - Central Line-Associated Bloodstream Infections
- **SSI** - Surgical Site Infections (Superficial, Deep, Organ/Space)

## Architecture

The system uses a four-stage workflow:

```
1. Rule-based Screening → 2. LLM Fact Extraction → 3. Rules Engine → 4. IP Review
```

1. **Rule-based screening** - Identifies candidates (BSI + line for CLABSI; procedure + infection signals for SSI)
2. **LLM fact extraction** - Extracts clinical facts from notes (symptoms, alternate sources, wound assessments)
3. **Rules engine** - Applies deterministic NHSN criteria to extracted facts
4. **IP Review** - ALL candidates go to IP for final decision

**Key principle**: The LLM extracts facts and provides a preliminary classification, but the Infection Preventionist always makes the final determination.

## Installation

```bash
cd hai-detection
pip install -r requirements.txt
```

## Usage

### Run HAI Detection

```bash
# Single detection cycle
cd /home/david/projects/aegis/hai-detection
python -m src.runner --once

# Full pipeline: detection + classification
python -m src.runner --full

# Dry run (no database writes)
python -m src.runner --full --dry-run

# Continuous monitoring mode
python -m src.runner
```

### View Statistics

```bash
python -m src.runner --stats
python -m src.runner --recent
```

## Project Structure

```
hai-detection/
├── src/
│   ├── __init__.py
│   ├── config.py         # Configuration
│   ├── db.py             # Database operations
│   ├── models.py         # Domain models
│   ├── monitor.py        # Main orchestrator
│   ├── runner.py         # CLI entry point
│   ├── candidates/       # Rule-based candidate detection
│   │   ├── base.py
│   │   ├── clabsi.py
│   │   └── ssi.py
│   ├── classifiers/      # LLM-assisted classification
│   │   ├── base.py
│   │   ├── clabsi_classifier.py
│   │   ├── clabsi_classifier_v2.py
│   │   └── ssi_classifier.py
│   ├── extraction/       # LLM fact extraction
│   │   ├── clabsi_extractor.py
│   │   └── ssi_extractor.py
│   ├── rules/            # NHSN criteria rules engines
│   │   ├── schemas.py
│   │   ├── clabsi_engine.py
│   │   ├── ssi_schemas.py
│   │   └── ssi_engine.py
│   ├── notes/            # Clinical note retrieval
│   │   ├── retriever.py
│   │   └── chunker.py
│   ├── llm/              # LLM backends
│   │   ├── factory.py
│   │   └── ollama.py
│   ├── review/           # IP review workflow
│   │   └── queue.py
│   ├── alerters/         # Notification channels
│   │   └── teams.py
│   └── data/             # Data sources
│       ├── factory.py
│       ├── fhir_source.py
│       └── clarity_source.py
├── prompts/              # LLM prompt templates
│   ├── clabsi_extraction_v1.txt
│   └── ssi_extraction_v1.txt
├── tests/
│   ├── test_candidates.py
│   ├── test_clabsi_rules.py
│   └── test_ssi_rules.py
├── schema.sql            # Database schema
├── requirements.txt
└── README.md
```

## Configuration

Configuration is read from environment variables or a `.env` file. Key settings:

```bash
# Data Sources
FHIR_BASE_URL=http://localhost:8081/fhir
CLARITY_CONNECTION_STRING=

# LLM Backend
LLM_BACKEND=ollama  # or 'claude'
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:70b

# Classification Thresholds
AUTO_CLASSIFY_THRESHOLD=0.85
IP_REVIEW_THRESHOLD=0.60

# CLABSI Criteria
MIN_DEVICE_DAYS=2
POST_REMOVAL_WINDOW_DAYS=1

# Database
HAI_DB_PATH=~/.aegis/nhsn.db

# Notifications
TEAMS_WEBHOOK_URL=
HAI_NOTIFICATION_EMAIL=
```

## Database

The module uses a SQLite database shared with the NHSN Reporting module. HAI detection tables:

- `hai_candidates` - Detected HAI candidates
- `hai_classifications` - LLM classification results
- `hai_reviews` - IP review decisions
- `hai_llm_audit` - LLM call audit log
- `ssi_procedures` - Tracked surgical procedures
- `ssi_candidate_details` - SSI-specific candidate data

## Integration with Dashboard

Access the HAI Detection dashboard at: `/hai-detection/`

The dashboard provides:
- Active cases awaiting IP review
- Case history (confirmed/rejected)
- Reports and analytics
- LLM override statistics

## Related Modules

- **nhsn-reporting** - NHSN submission, AU/AR data extraction
- **common** - Shared utilities (alert store, channels)
- **dashboard** - Web interface

## Testing

```bash
cd hai-detection
pytest tests/
```
