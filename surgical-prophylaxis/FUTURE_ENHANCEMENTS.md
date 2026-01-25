# Surgical Prophylaxis Module - Future Enhancements

## Overview

This document outlines planned enhancements for the Surgical Prophylaxis module beyond the current Phase 1 (retrospective monitoring) implementation.

---

## Priority 1: Actual CCHMC Guidelines

**Status:** Pending - Awaiting Guidelines

### Current State
The module currently uses a **sample/dummy guidelines file** (`data/cchmc_surgical_prophylaxis_guidelines.json`) created for development purposes. This file includes realistic procedure categories and CPT codes but should NOT be used for clinical decisions.

### Required Action
1. Obtain official CCHMC Surgical Antimicrobial Prophylaxis Guidelines from:
   - Antimicrobial Stewardship Program
   - Department of Surgery
   - Pharmacy and Therapeutics Committee

2. Guidelines should include:
   - Procedure-specific antibiotic recommendations
   - CPT code mappings for each procedure
   - Dosing tables (pediatric, adult, weight-based)
   - Allergy alternatives
   - Duration limits by procedure type
   - MRSA screening protocols
   - Special populations (neonates, transplant, immunocompromised)

3. Update `data/cchmc_surgical_prophylaxis_guidelines.json` with official content

4. Review and validate CPT code mappings with surgical scheduling

### Contacts
- [ ] ASP Pharmacist: _______________
- [ ] Surgery Quality Officer: _______________
- [ ] P&T Committee: _______________

---

## Priority 2: Real-Time Pre-Operative Alerting

**Status:** Planning

### Use Case
Alert surgical team when a patient arrives in pre-op or OR **without appropriate prophylaxis**, allowing intervention before incision.

### Clinical Value
- Prevent SSIs by ensuring timely prophylaxis
- Catch missing orders before it's too late
- More valuable than retrospective "you missed it" alerts

### Trigger Points

| Event | Timing | Alert Escalation |
|-------|--------|------------------|
| Surgery scheduled | T-24h | Passive notification to pre-op pharmacy |
| Patient arrives in pre-op | T-2h | Alert to pre-op nurse |
| 60 min before scheduled OR time | T-60m | Alert to anesthesiologist |
| 30 min before scheduled OR time | T-30m | Escalate to OR charge nurse + ASP |
| Patient enters OR | T-0 | Critical alert if still missing |

### Data Requirements

#### Real-Time Feeds
- **HL7 ADT A02** - Patient transfer/location updates
- **HL7 ORM** - OR scheduling messages
- **Epic ADT feed** - Patient tracking board updates

#### FHIR Polling Alternative
If HL7 feeds unavailable, poll:
- `Location` - Patient current location
- `Appointment` - OR schedule
- `MedicationRequest` - Prophylaxis orders
- `MedicationAdministration` - Actual administrations

### Alert Logic

```
┌─────────────────────────────────────────────────────────────┐
│              PRE-OPERATIVE ALERT DECISION TREE              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Patient location update received (pre-op/OR)               │
│         │                                                   │
│         ▼                                                   │
│  ┌─────────────────┐                                        │
│  │ Scheduled       │                                        │
│  │ procedure?      │──── NO ────▶ No action                │
│  └────────┬────────┘                                        │
│           │ YES                                             │
│           ▼                                                 │
│  ┌─────────────────┐                                        │
│  │ Prophylaxis     │                                        │
│  │ indicated?      │──── NO ────▶ No action                │
│  └────────┬────────┘                                        │
│           │ YES                                             │
│           ▼                                                 │
│  ┌─────────────────┐                                        │
│  │ Order exists?   │──── NO ────▶ ALERT: No order          │
│  └────────┬────────┘                                        │
│           │ YES                                             │
│           ▼                                                 │
│  ┌─────────────────┐                                        │
│  │ Administered?   │──── NO ────▶ ALERT: Not yet given     │
│  └────────┬────────┘                                        │
│           │ YES                                             │
│           ▼                                                 │
│  ┌─────────────────┐                                        │
│  │ Timing OK?      │──── NO ────▶ ALERT: May be too early  │
│  └────────┬────────┘                                        │
│           │ YES                                             │
│           ▼                                                 │
│       ✓ Compliant                                           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Implementation Components

```
surgical-prophylaxis/
├── src/
│   ├── realtime/
│   │   ├── __init__.py
│   │   ├── hl7_listener.py      # HL7 ADT message handler
│   │   ├── location_monitor.py  # Patient location tracking
│   │   ├── preop_checker.py     # Pre-incision compliance check
│   │   └── escalation.py        # Alert escalation logic
│   └── ...
```

---

## Priority 3: Epic Secure Chat Integration

**Status:** Planning

### Use Case
Deliver real-time alerts directly to surgical team members via Epic Secure Chat, with actionable buttons to order prophylaxis.

### Epic APIs Required

| API | Purpose | Authentication |
|-----|---------|----------------|
| FHIR R4 `Communication` | Send secure messages | SMART on FHIR |
| FHIR R4 `PractitionerRole` | Find on-call providers | Backend service |
| Epic In Basket API | Alternative delivery | Epic backend |
| Deep linking | "Order Now" buttons | Epic Hyperspace |

### Message Format

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  SURGICAL PROPHYLAXIS ALERT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Patient: [Name] (MRN: [MRN])
Location: Pre-Op Holding, Bay 4
Procedure: Laparoscopic Appendectomy (44970)
Scheduled OR Time: 10:30 AM (in 45 minutes)

⚠️  NO PROPHYLAXIS ORDER FOUND

Recommended:
• Cefazolin 2g IV + Metronidazole 500mg IV
• Administer within 60 minutes of incision

[ORDER NOW]  [ALREADY ORDERED]  [NOT INDICATED]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Recipient Routing

| Role | When to Alert | Method |
|------|---------------|--------|
| Pre-op Nurse | Patient in pre-op, no order | Secure Chat |
| Anesthesiologist | 60 min before OR, not given | Secure Chat + Page |
| Surgeon | 30 min before OR, still missing | Secure Chat + Page |
| ASP Pharmacist | Any escalation | In Basket |
| OR Charge Nurse | Critical (entering OR) | Page |

### Authentication Requirements

- [ ] Epic SMART on FHIR app registration
- [ ] Backend service account for system-initiated messages
- [ ] Provider directory access for role-based routing
- [ ] Deep link configuration for order entry

### CCHMC Epic Contacts
- [ ] Epic Analyst: _______________
- [ ] Integration Team: _______________
- [ ] SMART on FHIR Admin: _______________

---

## Priority 4: SSI Outcome Correlation

**Status:** Future

### Use Case
Correlate prophylaxis compliance with SSI outcomes to demonstrate clinical impact and identify improvement opportunities.

### Data Requirements
- SSI surveillance data from Infection Prevention
- Link surgical cases to post-op SSI diagnoses
- 30-day and 90-day follow-up windows

### Metrics
- SSI rate by compliance status (compliant vs. non-compliant)
- SSI rate by specific deviation type (timing, agent, duration)
- Risk-adjusted rates by procedure category

### Integration
- Link to HAI Detection module (SSI candidates)
- NSQIP reporting alignment

---

## Priority 5: NSQIP Reporting Integration

**Status:** Future

### Use Case
Automatically populate NSQIP (National Surgical Quality Improvement Program) data fields related to prophylaxis.

### NSQIP Fields
- Prophylaxis antibiotic given (yes/no)
- Antibiotic name
- Time of administration relative to incision
- Duration of prophylaxis

### Implementation
- Export compliance data in NSQIP format
- Automated abstraction for sampled cases
- Integration with NSQIP data collection workflow

---

## Priority 6: Intraoperative Redosing Alerts

**Status:** Future

### Use Case
Alert anesthesia team when surgery duration approaches redosing interval for the prophylaxis antibiotic.

### Logic
```
Surgery start time + Redosing interval (e.g., 4h for cefazolin)
    ↓
15 minutes before: "Reminder: Cefazolin redose due in 15 min"
    ↓
At interval: "Cefazolin redose NOW"
    ↓
15 minutes after: "OVERDUE: Cefazolin redose"
```

### Delivery
- Anesthesia workstation alert
- Epic Secure Chat to anesthesiologist
- OR display board

---

## Technical Dependencies

### Infrastructure Needed

| Component | Status | Notes |
|-----------|--------|-------|
| HL7 Interface Engine | TBD | Mirth Connect or similar |
| Real-time event bus | TBD | Kafka, RabbitMQ, or Redis Streams |
| Epic FHIR access | TBD | SMART on FHIR registration |
| Epic Secure Chat API | TBD | Backend service auth |
| Provider directory | TBD | PractitionerRole queries |

### Development Estimates

| Enhancement | Complexity | Dependencies |
|-------------|------------|--------------|
| Actual CCHMC guidelines | Low | Guidelines document |
| Real-time ADT monitoring | Medium | HL7 feed access |
| Epic Secure Chat | High | Epic API access, auth |
| SSI correlation | Medium | HAI Detection module |
| NSQIP integration | Low | Export format spec |
| Intraop redosing | Medium | Real-time OR data |

---

## Next Steps

1. **Immediate:** Obtain actual CCHMC surgical prophylaxis guidelines
2. **Short-term:** Investigate HL7 ADT feed availability
3. **Medium-term:** Request Epic SMART on FHIR app registration
4. **Long-term:** Pilot real-time alerting in one OR suite

---

## References

- Epic FHIR R4 Documentation: https://fhir.epic.com/
- Epic Secure Chat API: (internal Epic documentation)
- ASHP/IDSA/SHEA/SIS Guidelines 2013
- NSQIP Participant Use Data File: https://www.facs.org/quality-programs/acs-nsqip/
