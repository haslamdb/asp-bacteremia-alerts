# AEGIS Antimicrobial Stewardship Modules

## Overview

AEGIS (Automated Evaluation and Guidance for Infection Surveillance) includes two complementary modules for antimicrobial stewardship, supporting Joint Commission MM.09.01.01 compliance:

| Module | Purpose | Scope | Output |
|--------|---------|-------|--------|
| **Module 1: Appropriateness** | Clinical decision support | Per-order, real-time | Alerts, intervention worklist |
| **Module 2: Guideline Adherence** | Quality monitoring | Population, periodic | Dashboards, JC reports |

**Key Distinction**:
- **Appropriateness** asks: "Is this antibiotic order justified?" (antibiotics only)
- **Adherence** asks: "Did we follow the complete clinical pathway?" (antibiotics + cultures + labs + consults + imaging)

See [AEGIS_ASP_ARCHITECTURE.md](AEGIS_ASP_ARCHITECTURE.md) for detailed architecture documentation.

---

# Module 1: Antibiotic Appropriateness

## Overview

This module provides automated classification of antibiotic indication appropriateness. It enables real-time assessment of whether antibiotic orders have documented indications.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AEGIS ANTIBIOTIC APPROPRIATENESS                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │  LAYER 1        │    │  LAYER 2        │    │  LAYER 3        │         │
│  │  Indication     │ +  │  Agent          │ +  │  Duration       │         │
│  │  Appropriate?   │    │  Appropriate?   │    │  Appropriate?   │         │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘         │
│           │                      │                      │                   │
│  ┌────────▼────────┐    ┌────────▼────────┐    ┌────────▼────────┐         │
│  │ Chua ICD-10     │    │ Pocket Card     │    │ PIDS/IDSA       │         │
│  │ Classification  │    │ + Stanford      │    │ Guidelines      │         │
│  │ (This Module)   │    │ Guidelines      │    │ (Future)        │         │
│  │                 │    │ (Phase 2)       │    │                 │         │
│  │ ✓ IMPLEMENTED   │    │ □ PLANNED       │    │ □ PLANNED       │         │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Three-Layer Appropriateness Model

| Layer | Question | Data Source | Status |
|-------|----------|-------------|--------|
| **Layer 1** | Is there ANY indication for antibiotics? | Chua ICD-10 classification | ✅ Implemented |
| **Layer 2** | Is THIS antibiotic appropriate for the indication? | Pocket card + Guidelines | 🔲 Phase 2 |
| **Layer 3** | Is the DURATION appropriate? | PIDS/IDSA guidelines | 🔲 Phase 3 |

---

## Current Functionality (Layer 1)

### Files

| File | Description |
|------|-------------|
| `pediatric_abx_indications.py` | Main Python module with `AntibioticIndicationClassifier` class |
| `pediatric_icd10_abx_classification.csv` | Modified Chua classification (94,249 ICD-10 codes) |
| `pediatric_abx_reference.json` | Surgical/medical prophylaxis tables, febrile neutropenia logic |
| `aegis_integration_example.py` | Example AEGIS dashboard integration |

### Classification Categories

| Category | Code | Meaning | Dashboard Color |
|----------|------|---------|-----------------|
| Always | `A` | Antibiotic indicated - documented bacterial infection | 🟢 Green |
| Sometimes | `S` | May need antibiotics - clinical judgment required | 🟡 Yellow |
| Never | `N` | No antibiotic indication - likely inappropriate | 🔴 Red |
| Prophylaxis | `P` | Surgical or medical prophylaxis indication | 🔵 Blue |
| Febrile Neutropenia | `FN` | Neutropenia + fever - empiric therapy indicated | 🟢 Green |

### Quick Start

```python
from pediatric_abx_indications import AntibioticIndicationClassifier

# Initialize with Chua CSV
classifier = AntibioticIndicationClassifier('chuk046645_ww2.csv')

# Classify an encounter
result = classifier.classify(
    icd10_codes=['J18.9', 'R50.9'],  # Pneumonia + Fever
    cpt_codes=['47562'],              # Lap chole (optional)
    fever_present=True                # From vital signs
)

print(result.overall_category)      # IndicationCategory.ALWAYS
print(result.primary_indication)    # "Pneumonia, unspecified organism"
print(result.flags)                 # []
print(result.recommendations)       # []
```

### Special Logic

#### Febrile Neutropenia Detection
```python
# Automatically detected when:
# - ANY neutropenia code (D70.x) is present
# - AND fever code (R50.x) OR fever_present=True

result = classifier.classify(
    icd10_codes=['D70.9'],  # Neutropenia
    fever_present=True       # Temp >= 38.0°C
)
# Result: Category FN with recommendation for empiric protocol
```

#### Surgical Prophylaxis Validation
```python
# Automatically detected when CPT code matches surgical prophylaxis table

result = classifier.classify(
    icd10_codes=['K80.20'],   # Cholelithiasis (not an infection)
    cpt_codes=['47562']        # Laparoscopic cholecystectomy
)
# Result: Category P with prophylaxis recommendations
# - Agent: cefazolin
# - Max duration: 24 hours
# - Note: "Single dose often sufficient for low-risk"
```

#### Pediatric Inpatient Overrides
The base Chua classification is designed for outpatient use. We apply these modifications for inpatient pediatrics:

| Code | Original | Modified | Rationale |
|------|----------|----------|-----------|
| R78.81 (Bacteremia) | N | **A** | Inpatient bacteremia always requires treatment |
| J69.0 (Aspiration PNA) | N | **S** | Often requires empiric coverage |
| K65.x (Peritonitis) | S | **A** | Surgical emergency requiring antibiotics |

---

## Phase 2: Agent Appropriateness (Pocket Card Integration)

### Goal
Answer: "Given the diagnosis, is the SPECIFIC antibiotic ordered appropriate?"

### Data Sources

1. **Cincinnati Children's Pocket Card** - First-line and second-line agents by indication
2. **Stanford/LPCH Guidelines** - Comprehensive pediatric infection treatment table
3. **Local antibiogram** - Resistance patterns affecting empiric choice

### Planned Data Structure

```python
# Agent appropriateness will be stored as:
AGENT_RECOMMENDATIONS = {
    'indication_group': {
        'name': 'Community-Acquired Pneumonia',
        'icd10_patterns': ['J13', 'J14', 'J15', 'J18'],
        'first_line': [
            {
                'agent': 'ampicillin',
                'dose': '50 mg/kg/dose IV q6h',
                'max_dose': '2g/dose',
                'conditions': ['inpatient', 'no_atypical_coverage_needed']
            },
            {
                'agent': 'amoxicillin',
                'dose': '45 mg/kg/dose PO q12h',
                'max_dose': '1g/dose',
                'conditions': ['outpatient', 'mild_moderate']
            }
        ],
        'second_line': [
            {
                'agent': 'ceftriaxone',
                'dose': '50 mg/kg/dose IV q24h',
                'max_dose': '2g/dose',
                'conditions': ['penicillin_allergy_non_severe', 'failed_first_line']
            }
        ],
        'avoid': [
            {
                'agent': 'azithromycin',
                'reason': 'Monotherapy not recommended for typical bacterial CAP'
            }
        ],
        'duration_days': {'typical': 5, 'range': [5, 7]},
        'references': ['PIDS CAP Guidelines 2011', 'Cincinnati Pocket Card 2024']
    }
}
```

### Implementation Plan

```
Phase 2 Tasks:
├── 2.1 Parse Cincinnati pocket card into structured format
│   ├── Extract indication → agent mappings
│   ├── Capture dose recommendations
│   └── Note allergy alternatives
│
├── 2.2 Parse Stanford/LPCH guidelines PDF
│   ├── Extract by body system
│   ├── Map to ICD-10 codes
│   └── Capture duration recommendations
│
├── 2.3 Create indication grouping logic
│   ├── Map ICD-10 codes to indication groups
│   ├── Handle overlapping indications
│   └── Priority rules for multiple diagnoses
│
├── 2.4 Build agent matching function
│   ├── Match ordered antibiotic to recommendations
│   ├── Flag first-line vs second-line vs off-guideline
│   └── Check for contraindicated agents
│
└── 2.5 Integration with Layer 1
    ├── Extend ClassificationResult
    ├── Add agent_appropriate field
    └── Add agent_recommendations field
```

### Expected Output (Phase 2)

```python
result = classifier.classify(
    icd10_codes=['J18.9'],           # Pneumonia
    ordered_antibiotic='azithromycin' # What was actually ordered
)

# Extended result:
{
    'overall_category': 'A',          # Indication appropriate
    'primary_indication': 'Pneumonia, unspecified organism',
    'agent_assessment': {
        'ordered': 'azithromycin',
        'appropriate': False,
        'classification': 'AVOID',
        'reason': 'Monotherapy not recommended for typical bacterial CAP',
        'first_line_alternatives': ['ampicillin', 'amoxicillin'],
        'second_line_alternatives': ['ceftriaxone', 'levofloxacin']
    },
    'flags': ['AGENT_NOT_FIRST_LINE', 'REVIEW_RECOMMENDED']
}
```

---

## Phase 3: Duration Appropriateness

### Goal
Answer: "Is the antibiotic being continued longer than guidelines recommend?"

### Implementation Approach

```python
# Track antibiotic duration and compare to guidelines
DURATION_GUIDELINES = {
    'pneumonia_uncomplicated': {
        'recommended_days': 5,
        'max_days': 7,
        'alert_at_days': 6,
        'exceptions': ['empyema', 'necrotizing', 'immunocompromised']
    },
    'uti_cystitis': {
        'recommended_days': 3,
        'max_days': 5,
        'alert_at_days': 4
    },
    'surgical_prophylaxis': {
        'recommended_hours': 24,
        'max_hours': 48,  # Cardiac surgery exception
        'alert_at_hours': 25
    }
}
```

---

## Surgical Prophylaxis Validation

### Current Coverage (55+ procedures)

The module includes detailed surgical prophylaxis recommendations organized by specialty:

| Specialty | Procedures | Key Agents |
|-----------|------------|------------|
| Cardiac | VSD repair, valve replacement, CABG, transplant | Cefazolin, Vancomycin |
| Thoracic | Lobectomy, pneumonectomy | Cefazolin, Amp-sulbactam |
| Hepatobiliary | Cholecystectomy, liver transplant | Cefazolin, Pip-tazo |
| Colorectal | Colectomy, appendectomy | Cefazolin + Metronidazole |
| GU | Pyeloplasty, nephrectomy, transplant | Cefazolin |
| Orthopedic | Arthroplasty, spinal fusion, ORIF | Cefazolin |
| Neurosurgery | Craniotomy, VP shunt, laminectomy | Cefazolin, Vancomycin |
| Vascular | Endarterectomy, bypass | Cefazolin |
| Neonatal | G-tube, hernia repair, TEF repair | Cefazolin |

### Validation Logic

```python
def validate_surgical_prophylaxis(
    cpt_code: str,
    antibiotic_ordered: str,
    hours_since_incision: float,
    mrsa_risk: bool = False
) -> Dict:
    """
    Validate surgical prophylaxis appropriateness.
    
    Returns:
        {
            'prophylaxis_indicated': True/False,
            'agent_appropriate': True/False,
            'duration_appropriate': True/False,
            'recommendations': [...]
        }
    """
    
    info = SURGICAL_PROPHYLAXIS_CPT.get(cpt_code)
    
    if not info:
        return {'error': 'CPT code not in prophylaxis table'}
    
    if not info.prophylaxis_indicated:
        return {
            'prophylaxis_indicated': False,
            'recommendation': f'Prophylaxis not routinely indicated for {info.procedure_name}'
        }
    
    # Check agent
    agent_ok = antibiotic_ordered.lower() in [a.lower() for a in info.recommended_agents]
    
    # Check duration
    duration_ok = hours_since_incision <= info.max_duration_hours
    
    return {
        'prophylaxis_indicated': True,
        'procedure': info.procedure_name,
        'agent_appropriate': agent_ok,
        'agent_ordered': antibiotic_ordered,
        'recommended_agents': info.recommended_agents,
        'duration_appropriate': duration_ok,
        'hours_elapsed': hours_since_incision,
        'max_hours': info.max_duration_hours,
        'flags': [] if (agent_ok and duration_ok) else ['REVIEW_PROPHYLAXIS'],
        'special_considerations': info.special_considerations
    }
```

### Dashboard Integration

```
┌────────────────────────────────────────────────────────────────────────┐
│ SURGICAL PROPHYLAXIS MONITOR                                           │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│ Patient: Smith, John (MRN: 123456)                                     │
│ Procedure: Laparoscopic cholecystectomy (CPT 47562)                    │
│ OR Start: 2025-01-24 08:00                                             │
│                                                                        │
│ ┌──────────────────────────────────────────────────────────────────┐   │
│ │ Antibiotic: Cefazolin 1g IV                                      │   │
│ │ Given: 07:45 (15 min before incision) ✓                          │   │
│ │ Status: APPROPRIATE                                         🟢   │   │
│ └──────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│ Duration Monitor:                                                      │
│ ├─────────────────────────────────────────┤                           │
│ 0h              12h              24h      ← Max recommended            │
│ ▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░                              │
│ Current: 6h elapsed                                                    │
│                                                                        │
│ ⚠ ALERT AT: 24h - Recommend discontinuation                           │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Integration with Epic FHIR

### Required FHIR Resources

```python
FHIR_RESOURCES_NEEDED = {
    'Condition': 'ICD-10 diagnosis codes',
    'Procedure': 'CPT codes for surgical prophylaxis',
    'MedicationRequest': 'Antibiotic orders',
    'MedicationAdministration': 'Actual doses given (for duration tracking)',
    'Observation': 'Vital signs (temperature for fever detection)',
    'Patient': 'Demographics, allergies'
}
```

### Example FHIR Query Flow

```python
async def assess_patient_antibiotics(patient_id: str, encounter_id: str):
    """
    Full antibiotic appropriateness assessment from FHIR data.
    """
    
    # 1. Get active diagnoses
    conditions = await fhir_client.search('Condition', {
        'patient': patient_id,
        'encounter': encounter_id,
        'clinical-status': 'active'
    })
    icd10_codes = [c.code.coding[0].code for c in conditions]
    
    # 2. Get procedures (for surgical prophylaxis)
    procedures = await fhir_client.search('Procedure', {
        'patient': patient_id,
        'encounter': encounter_id
    })
    cpt_codes = [p.code.coding[0].code for p in procedures]
    
    # 3. Get vital signs (for fever detection)
    vitals = await fhir_client.search('Observation', {
        'patient': patient_id,
        'code': '8310-5',  # Body temperature LOINC
        '_sort': '-date',
        '_count': 1
    })
    temp = vitals[0].valueQuantity.value if vitals else None
    fever_present = temp and temp >= 38.0
    
    # 4. Get active antibiotic orders
    med_requests = await fhir_client.search('MedicationRequest', {
        'patient': patient_id,
        'encounter': encounter_id,
        'status': 'active',
        'category': 'antibiotic'  # May need local mapping
    })
    
    # 5. Classify each antibiotic order
    results = []
    for order in med_requests:
        result = classifier.classify(
            icd10_codes=icd10_codes,
            cpt_codes=cpt_codes,
            fever_present=fever_present
        )
        results.append({
            'medication': order.medicationCodeableConcept.text,
            'classification': result.to_dict()
        })
    
    return results
```

---

## Testing

### Unit Tests

```bash
# Run test cases
python pediatric_abx_indications.py chuk046645_ww2.csv
```

### Expected Test Output

```
======================================================================
TEST CASES
======================================================================

--- Bacterial pneumonia ---
ICD-10: ['J18.9'], CPT: [], Fever: False
Result: A - Antibiotic indicated - documented infection
Primary: Pneumonia, unspecified organism

--- Viral URI ---
ICD-10: ['J06.9'], CPT: [], Fever: False
Result: N - No documented indication for antibiotics
Primary: Acute upper respiratory infection, unspecified
Flags: NO_DOCUMENTED_INDICATION

--- Febrile neutropenia ---
ICD-10: ['D70.9', 'R50.9'], CPT: [], Fever: True
Result: FN - Febrile neutropenia - antibiotic indicated
Primary: Febrile neutropenia
Flags: FEBRILE_NEUTROPENIA
```

---

## Roadmap

### Phase 1 (Complete ✅)
- [x] Chua ICD-10 classification import
- [x] Pediatric inpatient modifications
- [x] Febrile neutropenia logic
- [x] Surgical prophylaxis table (55+ CPT codes)
- [x] Medical prophylaxis identification
- [x] Antifungal indication flagging
- [x] Basic AEGIS integration example

### Phase 2 (Next)
- [ ] Parse Cincinnati pocket card → structured format
- [ ] Parse Stanford/LPCH guidelines
- [ ] Build indication → agent mapping
- [ ] Agent appropriateness scoring
- [ ] Allergy-aware alternatives

### Phase 3 (Future)
- [ ] Duration tracking from MAR data
- [ ] Auto-stop recommendations
- [ ] De-escalation prompts
- [ ] IV-to-PO conversion alerts

### Phase 4 (Future)
- [ ] Local antibiogram integration
- [ ] Culture-directed therapy recommendations
- [ ] Machine learning for prediction

---

## References

1. **Chua KP, Fischer MA, Linder JA.** Appropriateness of outpatient antibiotic prescribing among privately insured US patients: ICD-10-CM based cross sectional study. BMJ. 2019;364:k5092.

2. **Stanford Children's Health.** Guidelines for Initial Therapy for Common Pediatric Infections. Updated October 2025.

3. **ASHP/IDSA/SHEA/SIS.** Clinical Practice Guidelines for Antimicrobial Prophylaxis in Surgery. 2013.

4. **Bradley JS, et al.** The Management of Community-Acquired Pneumonia in Infants and Children Older Than 3 Months of Age: Clinical Practice Guidelines by PIDS and IDSA. Clin Infect Dis. 2011.

5. **The Joint Commission.** MM.09.01.01 - Antimicrobial Stewardship Standard. Effective January 1, 2023.

---

## Contact

AEGIS Development Team  
Cincinnati Children's Hospital Medical Center  
Division of Infectious Diseases

---

# Module 2: Guideline Adherence Tracking

## Overview

This module tracks adherence to evidence-based clinical guidelines/bundles at the **population level**. Unlike Module 1 (which assesses individual orders in real-time), this module generates **aggregate metrics over time** for quality improvement and JC reporting.

## Why Separate Modules?

| Aspect | Appropriateness (Module 1) | Adherence (Module 2) |
|--------|---------------------------|---------------------|
| **Question** | "Is this order justified?" | "Did we follow the full pathway?" |
| **Timing** | Real-time (per order) | Retrospective (daily/weekly/monthly) |
| **Scope** | Antibiotic orders only | Full care bundle (cultures, labs, imaging, consults, antibiotics) |
| **Output** | Alert/flag for ASP intervention | Compliance % for dashboard/report |
| **Audience** | Pharmacist, ordering provider | ASP leadership, QI, JC surveyors |

## Guideline Bundles

Guidelines include **non-antibiotic elements** that are essential for quality care:

### Example: CAP Bundle Elements

| Element | Type | Required | Timing |
|---------|------|----------|--------|
| Blood culture obtained | Culture | Recommended | Before antibiotics |
| Chest X-ray performed | Imaging | Required | Within 24h |
| Appropriate empiric antibiotic | Antibiotic | Required | Within 4h |
| Narrow-spectrum preferred | Antibiotic | Recommended | - |
| Duration ≤5 days (uncomplicated) | Antibiotic | Required | At discharge |
| Follow-up arranged | Process | Recommended | At discharge |

### Available Guidelines

| Guideline | Elements | Key Metrics |
|-----------|----------|-------------|
| **Pediatric CAP** | 6 | Blood culture timing, empiric choice, duration |
| **Febrile Neutropenia** | 6 | Time to antibiotics, appropriate agent, cultures |
| **Pediatric Sepsis** | 6 | Lactate, culture timing, fluid resuscitation |
| **Surgical Prophylaxis** | 5 | Timing, agent selection, duration ≤24h |
| **Pediatric UTI** | 8 | Culture method, empiric choice, imaging |
| **SSTI/Cellulitis** | 6 | MRSA coverage decision, I&D if purulent |

## Dashboard Features

### Aggregate Compliance View
- Overall compliance rate (% of encounters meeting all required elements)
- Trend over time (weekly/monthly)
- Comparison by unit, service, or provider
- Element-level breakdown (which elements are failing?)

### Drill-Down Capabilities
- View non-compliant encounters
- Filter by missing element
- Identify common failure patterns
- Provider-level feedback reports

### Example Dashboard Output

```
Guideline: Pediatric CAP
Period: January 2025
Total Encounters: 540

Overall Compliance: 78.3% (423/540)
Target: 85%

Element Compliance:
  • Blood culture before Abx:  82%  ✓
  • Appropriate empiric agent: 92%  ✓
  • Duration ≤5 days:          58%  ⚠ (Below target)
  • Narrow-spectrum preferred: 45%  ✗

Unit Comparison:
  • PICU:      88%
  • Gen Peds:  76%
  • Oncology:  83%
  • NICU:      68%
  • ED:        61%
```

## Implementation

### Core Classes

```python
from guideline_adherence import (
    GuidelineAdherenceTracker,
    PediatricCAPGuideline,
    PediatricUTIGuideline,
    SurgicalProphylaxisGuideline
)

# Initialize tracker
tracker = GuidelineAdherenceTracker()

# Assess a single episode
result = tracker.assess_episode(
    guideline_id='pediatric_cap',
    encounter_data={
        'episode_id': 'ENC001',
        'patient_mrn': '123456',
        'icd10_codes': ['J18.9'],
        'unit': '7NW',
        'admission_date': datetime(2025, 1, 20),
        'cxr_obtained': True,
        'blood_culture_before_abx': True,
        'empiric_antibiotic': 'ampicillin',
        'antibiotic_duration_days': 5
    }
)

print(result.adherence_percentage)  # 100.0
print(result.outcome)               # AdherenceLevel.FULL
```

### Aggregate Reporting

```python
# Calculate metrics for a time period
metrics = tracker.calculate_metrics(
    guideline_id='pediatric_cap',
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 1, 31),
    stratify_by=['unit', 'month']
)

print(metrics.overall_adherence_rate)  # 78.3
print(metrics.by_unit)                 # {'PICU': 88%, 'Gen Peds': 76%, ...}
```

## Data Requirements

To track guideline adherence, AEGIS needs access to:

| Data Type | FHIR Resource | Example Elements |
|-----------|---------------|------------------|
| Diagnoses | Condition | ICD-10 codes for triggering guidelines |
| Antibiotics | MedicationRequest, MedicationAdministration | Agent, timing, duration |
| Cultures | ServiceRequest, Observation | Blood culture, urine culture, timing |
| Labs | Observation | Lactate, CBC, procalcitonin |
| Imaging | ImagingStudy | CXR, CT, ultrasound |
| Vitals | Observation | Temperature, heart rate, BP |
| Procedures | Procedure | I&D, source control |
| Notes | DocumentReference | Risk stratification, reassessment |

## Relationship to Module 1

Module 1 (Appropriateness) feeds into Module 2 (Adherence):

```
Patient admitted with CAP
         │
         ▼
┌─────────────────────────┐
│ Module 1: Real-time     │
│ - Ampicillin ordered    │
│ - Check: Indication? ✓  │
│ - Check: Agent? ✓       │
│ - No alert needed       │
└───────────┬─────────────┘
            │
            │  (Data stored)
            ▼
┌─────────────────────────┐
│ Module 2: At discharge  │
│ - Blood culture? ✓      │
│ - CXR? ✓                │
│ - Appropriate agent? ✓  │
│ - Duration ≤5d? ✓       │
│ - COMPLIANT             │
└───────────┬─────────────┘
            │
            │  (Aggregated nightly)
            ▼
┌─────────────────────────┐
│ Dashboard Updated       │
│ - CAP compliance: 79%   │
│ - Trend: ↑ 3% vs prior  │
└─────────────────────────┘
```

## Files

| File | Description |
|------|-------------|
| `guideline_adherence.py` | Core adherence tracking module |
| `AEGIS_ASP_ARCHITECTURE.md` | Detailed architecture documentation |

---

## Roadmap

### Phase 1: Antibiotic Appropriateness ✅
- [x] ICD-10 indication classification
- [x] Pediatric inpatient modifications
- [x] Febrile neutropenia logic
- [x] Surgical prophylaxis tables

### Phase 2: Agent Appropriateness 🔲
- [ ] Parse Cincinnati pocket card
- [ ] Build indication → agent mapping
- [ ] Real-time agent mismatch alerts

### Phase 3: Guideline Adherence Framework 🔲
- [ ] Define bundle data structures
- [ ] Implement CAP, FN, Sepsis, Surgical bundles
- [ ] Build compliance checker engine
- [ ] FHIR data integration

### Phase 4: Adherence Dashboard 🔲
- [ ] Aggregate compliance calculation
- [ ] Trend visualization
- [ ] Unit/provider comparisons
- [ ] Drill-down to non-compliant encounters

### Phase 5: Duration Tracking 🔲
- [ ] MAR integration for actual duration
- [ ] Auto-stop recommendations
- [ ] Duration compliance in bundles

---

## References

1. **Chua KP, Fischer MA, Linder JA.** Appropriateness of outpatient antibiotic prescribing among privately insured US patients: ICD-10-CM based cross sectional study. BMJ. 2019;364:k5092.

2. **Bradley JS, et al.** The Management of Community-Acquired Pneumonia in Infants and Children Older Than 3 Months of Age: Clinical Practice Guidelines by PIDS and IDSA. Clin Infect Dis. 2011.

3. **ASHP/IDSA/SHEA/SIS.** Clinical Practice Guidelines for Antimicrobial Prophylaxis in Surgery. 2013.

4. **Surviving Sepsis Campaign.** International Guidelines for Management of Sepsis and Septic Shock. 2021.

5. **The Joint Commission.** MM.09.01.01 - Antimicrobial Stewardship Standard. Effective January 1, 2023.

---

## License

Internal use only - Cincinnati Children's Hospital Medical Center
