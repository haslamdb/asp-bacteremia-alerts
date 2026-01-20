# AEGIS Demo Workflow

This guide walks through a complete demonstration of the AEGIS system, showing how real-time clinical alerts are triggered when new patient data arrives.

> **Disclaimer:** All patient data used in this demo is simulated. No actual patient data exists in this repository.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Terminal with multiple tabs/windows (or tmux)

## Overview

The demo shows two alert scenarios:

1. **Bacteremia Alert** - Patient with positive blood culture lacking appropriate antibiotic coverage
2. **Antimicrobial Usage Alert** - Patient on broad-spectrum antibiotics exceeding the 72-hour threshold

---

## Step 1: Start the HAPI FHIR Server

The HAPI FHIR server stores patient data and serves as the data source for our monitors.

```bash
cd aegis/asp-bacteremia-alerts
docker-compose up -d
```

Verify it's running:
```bash
curl http://localhost:8081/fhir/metadata | head -20
```

You should see FHIR capability statement JSON.

---

## Step 2: Start the Flask Dashboard

The dashboard displays alerts and allows acknowledgment/resolution.

**Terminal 1:**
```bash
cd aegis/dashboard

# Install dependencies (first time only)
pip install -r requirements.txt

# Start the dashboard
python -m flask run --port 5000
```

Open in browser: **http://localhost:5000**

You should see the ASP Alerts dashboard with empty active alerts.

---

## Step 3: Configure Environment

Ensure both monitors are configured to use the local FHIR server.

```bash
# For bacteremia monitor
cd aegis/asp-bacteremia-alerts
cp .env.template .env
# Edit .env: FHIR_BASE_URL=http://localhost:8081/fhir

# For antimicrobial usage monitor
cd aegis/antimicrobial-usage-alerts
cp .env.template .env
# Edit .env: FHIR_BASE_URL=http://localhost:8081/fhir
```

---

## Step 4: Clear Existing Data (Optional)

If you have previous demo data, clear it:

```bash
# Clear FHIR server data (restart container)
cd aegis/asp-bacteremia-alerts
docker-compose down
docker-compose up -d

# Clear alert database
rm -f ~/.aegis/alerts.db
```

Refresh the dashboard - it should show no alerts.

---

## Step 5: Run the Monitors

Open two additional terminal windows to run the monitors.

**Terminal 2 - Bacteremia Monitor:**
```bash
cd aegis/asp-bacteremia-alerts
source venv/bin/activate  # if using virtualenv
python -m src.monitor
```

**Terminal 3 - Antimicrobial Usage Monitor:**
```bash
cd aegis/antimicrobial-usage-alerts
source venv/bin/activate  # if using virtualenv
python -m src.runner --once --verbose
```

Both monitors should report "No alerts" since there's no patient data yet.

---

## Step 6: Demo - CLABSI Candidate (NHSN Module)

The NHSN module uses LLM-assisted classification to identify CLABSI candidates. Demo scenarios include both true CLABSI and Not CLABSI cases with detailed clinical notes.

**Terminal 4:**
```bash
cd aegis

# Create one CLABSI + one random Not CLABSI scenario
python scripts/demo_clabsi.py

# Or create specific scenarios:
python scripts/demo_clabsi.py --scenario clabsi           # Clear CLABSI
python scripts/demo_clabsi.py --scenario mbi              # MBI-LCBI (Not CLABSI)
python scripts/demo_clabsi.py --scenario secondary-uti    # Secondary to UTI
python scripts/demo_clabsi.py --scenario secondary-pneumonia  # Secondary to pneumonia

# Create all scenario types
python scripts/demo_clabsi.py --all
```

**Run the NHSN monitor and classifier:**
```bash
cd nhsn-reporting
python -m src.runner --once
```

**View in dashboard:** https://alerts.aegis-asp.com:8444/hai-detection/

### CLABSI Demo Scenarios

| Scenario | Command | Organism | Key Evidence | Classification |
|----------|---------|----------|--------------|----------------|
| Clear CLABSI | `--scenario clabsi` | S. aureus | Line site infection, negative UA/CXR | **CLABSI** |
| MBI-LCBI | `--scenario mbi` | E. coli | BMT patient, ANC 0, Grade 3 mucositis | Not CLABSI - MBI |
| Secondary (UTI) | `--scenario secondary-uti` | E. coli | Same organism in blood + urine, pyelonephritis | Not CLABSI - Secondary |
| Secondary (PNA) | `--scenario secondary-pneumonia` | Pseudomonas | Same organism in blood + respiratory | Not CLABSI - Secondary |

### Classification Workflow

1. **CLABSI** - Confirmed central line-associated bloodstream infection
2. **Not CLABSI** - Rejected, not a CLABSI
3. **MBI-LCBI** - Mucosal Barrier Injury (neutropenia + mucositis + gut organism)
4. **Secondary** - BSI secondary to another infection (UTI, pneumonia, etc.)
5. **Needs More Info** - Requires additional review (stays in active list)

---

## Step 7: Demo - Blood Culture Alert

Now we'll add a patient with MRSA bacteremia but no vancomycin coverage.

**Terminal 4:**
```bash
cd aegis

# Create patient with MRSA blood culture, no appropriate antibiotic
python scripts/demo_blood_culture.py --organism mrsa
```

Expected output:
```
============================================================
DEMO BLOOD CULTURE SCENARIO
============================================================
Patient:     Demo Patient (MRN: DEMO1234)
Organism:    Methicillin resistant Staphylococcus aureus
Antibiotic:  None
Alert:       YES - should trigger alert
============================================================

Uploading to http://localhost:8081/fhir...
  ✓ Patient created
  ✓ Encounter created
  ✓ Observation created

✓ Demo patient created successfully!
```

**Trigger the alert:**

In Terminal 2 (bacteremia monitor), run:
```bash
python -m src.monitor
```

You should see:
```
======================================================================
BACTEREMIA COVERAGE ALERT
======================================================================
  Patient:     Demo Patient (DEMO1234)
  Organism:    Methicillin resistant Staphylococcus aureus
  Status:      INADEQUATE
  Recommend:   Add vancomycin or daptomycin for MRSA coverage
======================================================================
```

**Check the dashboard:**
- Refresh http://localhost:5000
- The alert should appear in the Active Alerts list
- Click on the alert to see details and resolution options

---

## Step 8: Demo - Antimicrobial Usage Alert

Now we'll add a patient who has been on meropenem for 5 days (exceeds 72h threshold).

**Terminal 4:**
```bash
# Create patient on meropenem for 5 days
python scripts/demo_antimicrobial_usage.py --antibiotic meropenem --days 5
```

Expected output:
```
============================================================
DEMO ANTIMICROBIAL USAGE SCENARIO
============================================================
Patient:     Usage Patient (MRN: USAGE5678)
Antibiotic:  Meropenem
Duration:    120 hours (5.0 days)
Threshold:   72 hours
Monitored:   Yes
Alert:       WARNING (120h >= 72h)
============================================================

✓ Demo patient created successfully!
```

**Trigger the alert:**

In Terminal 3 (usage monitor), run:
```bash
python -m src.runner --once --verbose
```

You should see the alert generated for prolonged meropenem use.

**Check the dashboard:**
- Refresh http://localhost:5000
- Both alerts should now appear
- The meropenem alert shows as WARNING severity

---

## Step 9: Demonstrate Alert Resolution

Show how alerts are managed through the dashboard.

1. **Click on an alert** to view details
2. **Acknowledge** - Mark as seen (stays in active list)
3. **Snooze 4h** - Temporarily suppress
4. **Resolve** - Close with reason:
   - Select resolution reason (e.g., "Discussed with Team")
   - Add notes explaining the action taken
   - Click "Resolve Alert"

The alert moves to the History tab with full audit trail.

---

## Interactive Demo Mode

For live demos, use interactive mode to let the audience choose scenarios:

```bash
# Blood culture - audience chooses organism and antibiotic
python scripts/demo_blood_culture.py --interactive

# Antimicrobial usage - audience chooses drug and duration
python scripts/demo_antimicrobial_usage.py --interactive
```

---

## Demo Scenarios Quick Reference

### Blood Culture Scenarios

| Command | Scenario | Alert? |
|---------|----------|--------|
| `--organism mrsa` | MRSA, no antibiotic | Yes |
| `--organism mrsa --antibiotic vancomycin` | MRSA with vancomycin | No |
| `--organism mrsa --antibiotic cefazolin` | MRSA with wrong antibiotic | Yes |
| `--organism pseudomonas` | Pseudomonas, no coverage | Yes |
| `--organism pseudomonas --antibiotic meropenem` | Pseudomonas with meropenem | No |
| `--organism candida` | Candida, no antifungal | Yes |

### Antimicrobial Usage Scenarios

| Command | Duration | Alert Level |
|---------|----------|-------------|
| `--antibiotic meropenem --days 2` | 48h | None |
| `--antibiotic meropenem --days 4` | 96h | WARNING |
| `--antibiotic vancomycin --days 7` | 168h | CRITICAL |
| `--antibiotic ceftriaxone --days 5` | 120h | None (not monitored) |

---

## Troubleshooting

### FHIR server not responding
```bash
# Check if container is running
docker ps | grep hapi

# Restart if needed
cd asp-bacteremia-alerts
docker-compose down && docker-compose up -d
```

### Monitor not finding patients
```bash
# Verify data was uploaded
curl "http://localhost:8081/fhir/Patient?_count=5" | python -m json.tool
```

### Dashboard not showing alerts
- Check that monitors ran successfully
- Verify `ALERT_DB_PATH` is consistent across components
- Check browser console for JavaScript errors

### Teams notifications not sending
```bash
# Test webhook directly
python -c "from common.channels.teams import test_webhook; test_webhook('YOUR_WEBHOOK_URL')"
```

---

## Remote Access / Production Deployment

If you need to access the dashboard remotely (e.g., from a laptop at work connecting to a home server), there are several options:

### Option A: SSH Tunnel (Quick, Secure)

From your remote machine:
```bash
ssh -L 5000:localhost:5000 -L 8081:localhost:8081 user@your-server-ip
```
Then access `http://localhost:5000` in your browser. This tunnels both the dashboard and FHIR server.

### Option B: Production Deployment with Domain + SSL

For a proper demo accessible from anywhere, deploy with nginx and SSL.

**1. Run the setup script:**
```bash
cd aegis/dashboard/deploy
./setup_production.sh your-domain.com
```

**2. Set up SSL certificate:**
```bash
# If port 80 is accessible:
./setup_ssl.sh your-domain.com your-email@example.com

# If port 80 is blocked (use DNS challenge):
./setup_ssl_dns.sh your-domain.com your-email@example.com
```

**3. Configure your router:**
- Forward external port 443 → internal port 443 (HTTPS)
- Forward external port 8081 → internal port 8081 (FHIR, if needed externally)

**4. Update DNS:**
- Add an A record pointing your domain to your external IP

**Deployment files:**
- `dashboard/deploy/aegis.service` - Systemd service (runs on port 8082)
- `dashboard/deploy/nginx-aegis-local.conf` - Local/internal nginx config
- `dashboard/deploy/nginx-aegis-external.conf` - External nginx config with SSL
- `dashboard/deploy/setup_production.sh` - Automated setup script
- `dashboard/deploy/setup_ssl.sh` - Let's Encrypt setup (HTTP challenge)
- `dashboard/deploy/setup_ssl_dns.sh` - Let's Encrypt setup (DNS challenge)

**Service management:**
```bash
sudo systemctl status aegis    # Check status
sudo systemctl restart aegis   # Restart
sudo journalctl -u aegis -f    # View logs
```

---

## Cleanup

After the demo:

```bash
# Stop the FHIR server
cd asp-bacteremia-alerts
docker-compose down

# Clear alert database
rm -f ~/.aegis/alerts.db

# Stop Flask (Ctrl+C in Terminal 1)
```

---

## Architecture Diagram

```
┌─────────────────┐     ┌─────────────────┐
│  Demo Scripts   │────▶│  HAPI FHIR      │
│  (add patients) │     │  Server :8081   │
└─────────────────┘     └────────┬────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
          ┌─────────────────┐       ┌─────────────────┐
          │   Bacteremia    │       │  Antimicrobial  │
          │    Monitor      │       │  Usage Monitor  │
          └────────┬────────┘       └────────┬────────┘
                   │                         │
                   └──────────┬──────────────┘
                              ▼
                    ┌─────────────────┐
                    │   Alert Store   │
                    │   (SQLite)      │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
     │  Dashboard   │ │    Teams     │ │    Email     │
     │  :5000       │ │   Webhook    │ │    SMTP      │
     └──────────────┘ └──────────────┘ └──────────────┘
```

---

## Tips for a Successful Demo

1. **Pre-load some data** - Have a few patients already in the system to show the dashboard isn't empty
2. **Use interactive mode** - Let the audience choose scenarios
3. **Show the audit trail** - Resolve an alert and show the history
4. **Explain the clinical context** - Why MRSA needs vancomycin, why we track meropenem duration
5. **Show Teams integration** - If configured, show how alerts appear in Teams with action buttons
