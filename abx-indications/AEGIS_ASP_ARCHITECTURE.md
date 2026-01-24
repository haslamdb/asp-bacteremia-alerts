# AEGIS Antimicrobial Stewardship Module Architecture

## Overview

The AEGIS ASP functionality consists of two related but distinct modules:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AEGIS ASP PLATFORM                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────┐    ┌─────────────────────────────────┐ │
│  │  MODULE 1                       │    │  MODULE 2                       │ │
│  │  ANTIBIOTIC APPROPRIATENESS     │    │  GUIDELINE ADHERENCE            │ │
│  │                                 │    │                                 │ │
│  │  Scope: Per-order, real-time    │    │  Scope: Population, periodic    │ │
│  │  Purpose: CDS, ASP alerts       │    │  Purpose: QI, JC reporting      │ │
│  │                                 │    │                                 │ │
│  │  ┌───────────────────────────┐  │    │  ┌───────────────────────────┐  │ │
│  │  │ • Indication documented?  │  │    │  │ • Bundle compliance %     │  │ │
│  │  │ • Agent appropriate?      │  │    │  │ • Trends over time        │  │ │
│  │  │ • Duration appropriate?   │  │    │  │ • Unit comparisons        │  │ │
│  │  │ • Prophylaxis valid?      │  │    │  │ • Provider feedback       │  │ │
│  │  └───────────────────────────┘  │    │  └───────────────────────────┘  │ │
│  │                                 │    │                                 │ │
│  │  Output: Alerts, flags          │    │  Output: Dashboards, reports    │ │
│  └─────────────────────────────────┘    └─────────────────────────────────┘ │
│                                                                             │
│                    ▼                                    ▼                   │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                      SHARED DATA LAYER                                  ││
│  │  • Patient encounters    • Antibiotic orders    • Diagnoses             ││
│  │  • Culture results       • Vital signs          • Lab values            ││
│  │  • Procedures            • Consults             • Imaging               ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Module 1: Antibiotic Appropriateness (Existing)

**Purpose**: Real-time clinical decision support for individual antibiotic orders

**Files**:
- `pediatric_abx_indications.py` - Classification engine
- `pediatric_icd10_abx_classification.csv` - ICD-10 indication lookup
- `pediatric_abx_reference.json` - Prophylaxis tables

**Use Cases**:
- Alert pharmacist when antibiotic ordered without documented indication
- Flag when antibiotic doesn't match guideline for documented indication
- Track surgical prophylaxis duration
- Identify febrile neutropenia for protocol compliance

**Output**: Per-order classification result with flags and recommendations

---

## Module 2: Guideline Adherence Tracking (New)

**Purpose**: Population-level monitoring of adherence to evidence-based clinical guidelines/bundles

### Joint Commission Requirement

> **MM.09.01.01 EP 18**: "The hospital implements at least two evidence-based guidelines or recommendations for diagnosis/treatment of infection, or for specific syndrome/condition..."

This requires not just having guidelines, but **measuring adherence** to them.

### Key Differences from Appropriateness Module

| Aspect | Appropriateness | Adherence |
|--------|-----------------|-----------|
| Timing | Real-time | Retrospective (daily/weekly/monthly) |
| Scope | Single order | Entire clinical pathway |
| Elements | Antibiotic only | Antibiotics + cultures + labs + consults + imaging |
| Output | Alert/flag | Compliance percentage |
| Audience | Pharmacist, ordering provider | ASP leadership, QI, JC surveyors |
| Granularity | Patient-level | Aggregate (unit, service, hospital) |

### Guideline Bundle Structure

A guideline is more than just "right antibiotic" - it's a bundle of recommended actions:

```python
@dataclass
class GuidelineElement:
    """Single element of a clinical guideline bundle."""
    element_id: str
    description: str
    element_type: str  # 'antibiotic', 'culture', 'lab', 'consult', 'imaging', 'other'
    required: bool     # True = must do, False = recommended
    timing: Optional[str]  # e.g., "before_antibiotics", "within_24h"
    data_source: str   # How to check compliance (FHIR resource, etc.)
    
@dataclass 
class ClinicalGuideline:
    """Complete clinical guideline/bundle definition."""
    guideline_id: str
    name: str
    version: str
    applicable_diagnoses: List[str]  # ICD-10 patterns
    applicable_settings: List[str]   # 'ED', 'inpatient', 'ICU', etc.
    elements: List[GuidelineElement]
    references: List[str]
    last_updated: date
```

### Example Guidelines

#### 1. Community-Acquired Pneumonia (CAP) Bundle

```python
CAP_GUIDELINE = ClinicalGuideline(
    guideline_id='CAP-PEDS-001',
    name='Pediatric Community-Acquired Pneumonia',
    version='2024.1',
    applicable_diagnoses=['J13', 'J14', 'J15.*', 'J18.*'],
    applicable_settings=['ED', 'inpatient'],
    elements=[
        GuidelineElement(
            element_id='CAP-01',
            description='Blood culture obtained',
            element_type='culture',
            required=False,  # Recommended for inpatient, not required
            timing='before_antibiotics',
            data_source='Lab.blood_culture'
        ),
        GuidelineElement(
            element_id='CAP-02',
            description='Chest X-ray performed',
            element_type='imaging',
            required=True,
            timing='within_24h_of_admission',
            data_source='Imaging.CXR'
        ),
        GuidelineElement(
            element_id='CAP-03',
            description='Appropriate empiric antibiotic',
            element_type='antibiotic',
            required=True,
            timing='within_4h_of_diagnosis',
            data_source='MedicationRequest',
            # Sub-criteria handled by appropriateness module
        ),
        GuidelineElement(
            element_id='CAP-04',
            description='Narrow-spectrum preferred (ampicillin/amoxicillin)',
            element_type='antibiotic',
            required=False,  # Recommended, not required
            timing=None,
            data_source='MedicationRequest'
        ),
        GuidelineElement(
            element_id='CAP-05',
            description='Duration ≤5 days for uncomplicated',
            element_type='antibiotic',
            required=True,
            timing='at_discharge',
            data_source='MedicationAdministration'
        ),
    ],
    references=['PIDS/IDSA CAP Guidelines 2011', 'Cincinnati Pocket Card'],
    last_updated=date(2024, 6, 1)
)
```

#### 2. Febrile Neutropenia Bundle

```python
FN_GUIDELINE = ClinicalGuideline(
    guideline_id='FN-PEDS-001',
    name='Pediatric Febrile Neutropenia',
    version='2024.1',
    applicable_diagnoses=['D70.*'],  # With fever
    applicable_settings=['ED', 'inpatient', 'oncology'],
    elements=[
        GuidelineElement(
            element_id='FN-01',
            description='Blood culture (peripheral) obtained',
            element_type='culture',
            required=True,
            timing='before_antibiotics',
            data_source='Lab.blood_culture'
        ),
        GuidelineElement(
            element_id='FN-02',
            description='Blood culture (central line) obtained if present',
            element_type='culture',
            required=True,  # If line present
            timing='before_antibiotics',
            data_source='Lab.blood_culture'
        ),
        GuidelineElement(
            element_id='FN-03',
            description='Empiric antibiotics within 60 minutes of triage',
            element_type='antibiotic',
            required=True,
            timing='within_60min_of_triage',
            data_source='MedicationAdministration'
        ),
        GuidelineElement(
            element_id='FN-04',
            description='Antipseudomonal beta-lactam used',
            element_type='antibiotic',
            required=True,
            timing=None,
            data_source='MedicationRequest',
            # Acceptable: cefepime, piperacillin-tazobactam, meropenem
        ),
        GuidelineElement(
            element_id='FN-05',
            description='CBC with differential obtained',
            element_type='lab',
            required=True,
            timing='within_1h',
            data_source='Lab.CBC'
        ),
        GuidelineElement(
            element_id='FN-06',
            description='Risk stratification documented',
            element_type='other',
            required=False,
            timing='within_4h',
            data_source='Documentation'
        ),
    ],
    references=['IDSA Febrile Neutropenia Guidelines 2010', 'COG Supportive Care'],
    last_updated=date(2024, 6, 1)
)
```

#### 3. Sepsis Bundle (Pediatric)

```python
SEPSIS_GUIDELINE = ClinicalGuideline(
    guideline_id='SEPSIS-PEDS-001',
    name='Pediatric Sepsis/Septic Shock Bundle',
    version='2024.1',
    applicable_diagnoses=['A41.*', 'R65.2*'],
    applicable_settings=['ED', 'inpatient', 'PICU'],
    elements=[
        GuidelineElement(
            element_id='SEP-01',
            description='Blood culture obtained',
            element_type='culture',
            required=True,
            timing='before_antibiotics',
            data_source='Lab.blood_culture'
        ),
        GuidelineElement(
            element_id='SEP-02',
            description='Lactate measured',
            element_type='lab',
            required=True,
            timing='within_1h',
            data_source='Lab.lactate'
        ),
        GuidelineElement(
            element_id='SEP-03',
            description='Broad-spectrum antibiotics administered',
            element_type='antibiotic',
            required=True,
            timing='within_1h_of_recognition',
            data_source='MedicationAdministration'
        ),
        GuidelineElement(
            element_id='SEP-04',
            description='Fluid resuscitation initiated (if hypotensive)',
            element_type='other',
            required=True,
            timing='within_1h',
            data_source='FluidAdministration'
        ),
        GuidelineElement(
            element_id='SEP-05',
            description='Repeat lactate if initial elevated',
            element_type='lab',
            required=True,
            timing='within_6h',
            data_source='Lab.lactate'
        ),
        GuidelineElement(
            element_id='SEP-06',
            description='Source control addressed',
            element_type='other',
            required=False,
            timing='within_12h',
            data_source='Documentation'
        ),
    ],
    references=['Surviving Sepsis Campaign 2021', 'Cincinnati Sepsis Pathway'],
    last_updated=date(2024, 6, 1)
)
```

#### 4. Surgical Prophylaxis Bundle

```python
SURG_PROPH_GUIDELINE = ClinicalGuideline(
    guideline_id='SURGPROPH-001',
    name='Surgical Antimicrobial Prophylaxis',
    version='2024.1',
    applicable_diagnoses=[],  # Triggered by CPT codes instead
    applicable_settings=['OR', 'perioperative'],
    elements=[
        GuidelineElement(
            element_id='SP-01',
            description='Antibiotic given within 60 min of incision',
            element_type='antibiotic',
            required=True,
            timing='within_60min_before_incision',
            data_source='MedicationAdministration + OR_times'
        ),
        GuidelineElement(
            element_id='SP-02',
            description='Appropriate agent for procedure type',
            element_type='antibiotic',
            required=True,
            timing=None,
            data_source='MedicationRequest'
            # Cross-reference with surgical prophylaxis table
        ),
        GuidelineElement(
            element_id='SP-03',
            description='Weight-based dosing used',
            element_type='antibiotic',
            required=True,
            timing=None,
            data_source='MedicationRequest.dose'
        ),
        GuidelineElement(
            element_id='SP-04',
            description='Redosing given if surgery >4 hours (cefazolin)',
            element_type='antibiotic',
            required=True,  # If applicable
            timing='q4h_intraop',
            data_source='MedicationAdministration'
        ),
        GuidelineElement(
            element_id='SP-05',
            description='Prophylaxis discontinued within 24 hours',
            element_type='antibiotic',
            required=True,
            timing='within_24h_of_surgery_end',
            data_source='MedicationAdministration'
        ),
    ],
    references=['ASHP/IDSA/SHEA/SIS Guidelines 2013', 'SCIP measures'],
    last_updated=date(2024, 6, 1)
)
```

---

## Adherence Tracking Engine

### Core Data Structures

```python
@dataclass
class ElementCompliance:
    """Compliance result for a single guideline element."""
    element_id: str
    element_description: str
    compliant: bool
    not_applicable: bool = False
    evidence: Optional[str] = None  # What data showed compliance/non-compliance
    timestamp: Optional[datetime] = None
    notes: Optional[str] = None

@dataclass
class EncounterCompliance:
    """Compliance result for a single patient encounter."""
    encounter_id: str
    patient_mrn: str
    guideline_id: str
    guideline_name: str
    admission_date: datetime
    discharge_date: Optional[datetime]
    applicable: bool  # Did this guideline apply to this encounter?
    element_results: List[ElementCompliance]
    overall_compliant: bool  # All required elements met?
    compliance_score: float  # Percentage of elements met
    
@dataclass
class AggregateCompliance:
    """Aggregated compliance metrics for reporting."""
    guideline_id: str
    guideline_name: str
    time_period: Tuple[date, date]
    filters: Dict[str, str]  # e.g., {'unit': 'PICU', 'service': 'oncology'}
    
    total_applicable_encounters: int
    fully_compliant_encounters: int
    overall_compliance_rate: float
    
    element_compliance: Dict[str, float]  # element_id -> compliance %
    trend_data: List[Dict]  # For time-series charts
```

### Compliance Checker

```python
class GuidelineComplianceChecker:
    """
    Checks compliance with clinical guidelines for individual encounters.
    """
    
    def __init__(self, data_source):
        """
        Args:
            data_source: Interface to EHR data (FHIR client, database, etc.)
        """
        self.data = data_source
        self.guidelines = self._load_guidelines()
    
    def check_encounter(
        self, 
        encounter_id: str,
        guideline_id: Optional[str] = None
    ) -> List[EncounterCompliance]:
        """
        Check guideline compliance for an encounter.
        
        If guideline_id not specified, checks all applicable guidelines.
        """
        # Get encounter data
        encounter = self.data.get_encounter(encounter_id)
        diagnoses = self.data.get_diagnoses(encounter_id)
        
        results = []
        
        # Determine applicable guidelines
        applicable = self._get_applicable_guidelines(diagnoses, encounter)
        
        if guideline_id:
            applicable = [g for g in applicable if g.guideline_id == guideline_id]
        
        for guideline in applicable:
            result = self._check_guideline(encounter_id, guideline)
            results.append(result)
        
        return results
    
    def _check_guideline(
        self, 
        encounter_id: str, 
        guideline: ClinicalGuideline
    ) -> EncounterCompliance:
        """Check compliance with a specific guideline."""
        
        element_results = []
        
        for element in guideline.elements:
            compliance = self._check_element(encounter_id, element)
            element_results.append(compliance)
        
        # Calculate overall compliance
        required_elements = [e for e in element_results 
                           if not e.not_applicable and 
                           guideline.elements[element_results.index(e)].required]
        
        if required_elements:
            compliant_required = sum(1 for e in required_elements if e.compliant)
            overall_compliant = compliant_required == len(required_elements)
            compliance_score = compliant_required / len(required_elements)
        else:
            overall_compliant = True
            compliance_score = 1.0
        
        return EncounterCompliance(
            encounter_id=encounter_id,
            patient_mrn=self.data.get_mrn(encounter_id),
            guideline_id=guideline.guideline_id,
            guideline_name=guideline.name,
            admission_date=self.data.get_admission_date(encounter_id),
            discharge_date=self.data.get_discharge_date(encounter_id),
            applicable=True,
            element_results=element_results,
            overall_compliant=overall_compliant,
            compliance_score=compliance_score
        )
    
    def _check_element(
        self, 
        encounter_id: str, 
        element: GuidelineElement
    ) -> ElementCompliance:
        """Check compliance with a single guideline element."""
        
        # Dispatch to specific checker based on element type
        checkers = {
            'antibiotic': self._check_antibiotic_element,
            'culture': self._check_culture_element,
            'lab': self._check_lab_element,
            'imaging': self._check_imaging_element,
            'consult': self._check_consult_element,
            'other': self._check_other_element,
        }
        
        checker = checkers.get(element.element_type, self._check_other_element)
        return checker(encounter_id, element)
    
    def _check_antibiotic_element(
        self, 
        encounter_id: str, 
        element: GuidelineElement
    ) -> ElementCompliance:
        """Check antibiotic-related guideline element."""
        
        # Get antibiotic orders/administrations
        meds = self.data.get_antibiotics(encounter_id)
        
        if not meds:
            return ElementCompliance(
                element_id=element.element_id,
                element_description=element.description,
                compliant=False,
                evidence='No antibiotics found'
            )
        
        # Check timing if specified
        if element.timing:
            compliant, evidence = self._check_timing(
                encounter_id, meds, element.timing
            )
        else:
            compliant = True
            evidence = f'Antibiotic administered: {meds[0].name}'
        
        return ElementCompliance(
            element_id=element.element_id,
            element_description=element.description,
            compliant=compliant,
            evidence=evidence,
            timestamp=meds[0].administered_at if meds else None
        )
    
    def _check_culture_element(
        self, 
        encounter_id: str, 
        element: GuidelineElement
    ) -> ElementCompliance:
        """Check culture-related guideline element."""
        
        cultures = self.data.get_cultures(encounter_id)
        antibiotics = self.data.get_antibiotics(encounter_id)
        
        if not cultures:
            return ElementCompliance(
                element_id=element.element_id,
                element_description=element.description,
                compliant=False,
                evidence='No cultures obtained'
            )
        
        # Check if culture was before antibiotics
        if element.timing == 'before_antibiotics' and antibiotics:
            first_abx = min(a.administered_at for a in antibiotics)
            first_culture = min(c.collected_at for c in cultures)
            
            compliant = first_culture < first_abx
            evidence = f'Culture at {first_culture}, Abx at {first_abx}'
        else:
            compliant = True
            evidence = f'Culture obtained at {cultures[0].collected_at}'
        
        return ElementCompliance(
            element_id=element.element_id,
            element_description=element.description,
            compliant=compliant,
            evidence=evidence,
            timestamp=cultures[0].collected_at if cultures else None
        )
    
    # ... additional element checkers ...
```

### Aggregation and Reporting

```python
class ComplianceReporter:
    """
    Aggregates compliance data for dashboards and reports.
    """
    
    def __init__(self, checker: GuidelineComplianceChecker):
        self.checker = checker
    
    def generate_report(
        self,
        guideline_id: str,
        start_date: date,
        end_date: date,
        filters: Optional[Dict] = None
    ) -> AggregateCompliance:
        """
        Generate aggregate compliance report.
        
        Args:
            guideline_id: Which guideline to report on
            start_date: Report period start
            end_date: Report period end
            filters: Optional filters (unit, service, provider, etc.)
        """
        
        # Get all applicable encounters in time period
        encounters = self.checker.data.get_encounters(
            start_date=start_date,
            end_date=end_date,
            filters=filters
        )
        
        # Check compliance for each
        results = []
        for enc in encounters:
            compliance = self.checker.check_encounter(enc.id, guideline_id)
            if compliance and compliance[0].applicable:
                results.append(compliance[0])
        
        if not results:
            return None
        
        # Aggregate
        total = len(results)
        fully_compliant = sum(1 for r in results if r.overall_compliant)
        
        # Element-level compliance
        element_compliance = {}
        guideline = self.checker.guidelines[guideline_id]
        for element in guideline.elements:
            element_results = [
                r.element_results[i] 
                for r in results 
                for i, e in enumerate(r.element_results) 
                if e.element_id == element.element_id and not e.not_applicable
            ]
            if element_results:
                element_compliance[element.element_id] = (
                    sum(1 for e in element_results if e.compliant) / len(element_results)
                )
        
        return AggregateCompliance(
            guideline_id=guideline_id,
            guideline_name=guideline.name,
            time_period=(start_date, end_date),
            filters=filters or {},
            total_applicable_encounters=total,
            fully_compliant_encounters=fully_compliant,
            overall_compliance_rate=fully_compliant / total if total > 0 else 0,
            element_compliance=element_compliance,
            trend_data=self._calculate_trend(results, start_date, end_date)
        )
    
    def _calculate_trend(
        self, 
        results: List[EncounterCompliance],
        start_date: date,
        end_date: date,
        interval: str = 'week'
    ) -> List[Dict]:
        """Calculate compliance trend over time."""
        # Group results by time interval and calculate compliance for each
        # Returns data suitable for time-series charting
        pass
    
    def compare_units(
        self,
        guideline_id: str,
        start_date: date,
        end_date: date,
        units: List[str]
    ) -> Dict[str, AggregateCompliance]:
        """Compare compliance across hospital units."""
        
        results = {}
        for unit in units:
            report = self.generate_report(
                guideline_id=guideline_id,
                start_date=start_date,
                end_date=end_date,
                filters={'unit': unit}
            )
            results[unit] = report
        
        return results
```

---

## Dashboard Specifications

### Guideline Adherence Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ AEGIS - Guideline Adherence Dashboard                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Filters: [Guideline ▼] [Time Period ▼] [Unit ▼] [Service ▼] [Apply]       │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ OVERALL COMPLIANCE                                                   │   │
│  │                                                                      │   │
│  │   ████████████████████████████░░░░░░░░░░  78.3%                     │   │
│  │                                                                      │   │
│  │   Fully Compliant: 423 / 540 encounters                             │   │
│  │   Target: 85%                                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ COMPLIANCE TREND (Last 6 Months)                                     │   │
│  │                                                                      │   │
│  │  100% ┤                                                              │   │
│  │   90% ┤                              ╭─────╮                         │   │
│  │   80% ┤         ╭────╮    ╭────╮    │     │    ╭────                │   │
│  │   70% ┤    ╭────╯    ╰────╯    ╰────╯     ╰────╯                    │   │
│  │   60% ┤────╯                                                         │   │
│  │       └────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────       │   │
│  │        Aug  Sep  Oct  Nov  Dec  Jan                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ ELEMENT-LEVEL COMPLIANCE                                             │   │
│  │                                                                      │   │
│  │  Blood culture before Abx    ████████████████████░░░░░░░  82%  ✓   │   │
│  │  Appropriate empiric agent   █████████████████████████░░  92%  ✓   │   │
│  │  Duration ≤5 days           ████████████░░░░░░░░░░░░░░░  58%  ⚠   │   │
│  │  Narrow-spectrum preferred   ██████████░░░░░░░░░░░░░░░░░  45%  ✗   │   │
│  │                                                                      │   │
│  │  ✓ Meeting target  ⚠ Near target  ✗ Below target                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ UNIT COMPARISON                                                      │   │
│  │                                                                      │   │
│  │  PICU        ████████████████████████████████░░░  88%              │   │
│  │  Gen Peds    ██████████████████████████░░░░░░░░░  76%              │   │
│  │  Oncology    █████████████████████████████░░░░░░  83%              │   │
│  │  NICU        ██████████████████████░░░░░░░░░░░░░  68%              │   │
│  │  ED          █████████████████░░░░░░░░░░░░░░░░░░  61%              │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  [Export Report]  [Schedule Email]  [Drill Down to Encounters]             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Drill-Down: Non-Compliant Encounters

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Non-Compliant Encounters - CAP Guideline - January 2025                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ MRN       Admit    Unit     Compliance  Missing Elements            │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │ 123456   01/05    Gen Peds   60%       Duration >5d, No CXR        │   │
│  │ 234567   01/08    PICU       80%       Culture after Abx           │   │
│  │ 345678   01/12    ED         40%       No culture, Broad-spectrum  │   │
│  │ 456789   01/15    Gen Peds   60%       Duration >5d                │   │
│  │ 567890   01/18    Oncology   80%       Culture after Abx           │   │
│  │ ...                                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Filter by: [Missing Element ▼]  [Unit ▼]  [Provider ▼]                    │
│                                                                             │
│  Most Common Compliance Failures:                                           │
│  1. Duration >5 days (42% of failures)                                     │
│  2. Blood culture after antibiotics (28% of failures)                      │
│  3. Broad-spectrum instead of narrow (18% of failures)                     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Integration Points

### Module 1 → Module 2 Data Flow

```
┌─────────────────────────┐
│ Antibiotic Order Placed │
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Module 1: Appropriateness│
│ - Indication check      │
│ - Agent check           │
│ - Real-time alert       │
└───────────┬─────────────┘
            │
            │  (Results stored)
            ▼
┌─────────────────────────┐
│ AEGIS Database          │
│ - Encounter data        │
│ - Classification results│
│ - Timestamps            │
└───────────┬─────────────┘
            │
            │  (Nightly/Weekly batch)
            ▼
┌─────────────────────────┐
│ Module 2: Adherence     │
│ - Aggregate compliance  │
│ - Trend analysis        │
│ - Dashboard update      │
└─────────────────────────┘
```

### Shared Components

Both modules share:
- ICD-10 classification data
- Antibiotic formulary/classes
- FHIR data access layer
- User authentication

---

## File Structure (Proposed)

```
aegis/
├── asp/
│   ├── __init__.py
│   │
│   ├── appropriateness/                    # MODULE 1
│   │   ├── __init__.py
│   │   ├── classifier.py                   # AntibioticIndicationClassifier
│   │   ├── prophylaxis.py                  # Surgical/medical prophylaxis
│   │   └── data/
│   │       ├── chua_icd10_classification.csv
│   │       └── pediatric_overrides.json
│   │
│   ├── adherence/                          # MODULE 2
│   │   ├── __init__.py
│   │   ├── guidelines.py                   # Guideline definitions
│   │   ├── checker.py                      # GuidelineComplianceChecker
│   │   ├── reporter.py                     # ComplianceReporter
│   │   └── data/
│   │       ├── cap_guideline.json
│   │       ├── fn_guideline.json
│   │       ├── sepsis_guideline.json
│   │       └── surgical_prophylaxis_guideline.json
│   │
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── fhir_client.py                  # FHIR data access
│   │   ├── models.py                       # Shared data classes
│   │   └── antibiotic_classes.py           # Drug classification
│   │
│   └── dashboard/
│       ├── __init__.py
│       ├── appropriateness_api.py          # REST API for Module 1
│       ├── adherence_api.py                # REST API for Module 2
│       └── templates/
│           ├── appropriateness_dashboard.html
│           └── adherence_dashboard.html
│
└── tests/
    ├── test_appropriateness.py
    └── test_adherence.py
```

---

## Implementation Phases

### Phase 1: Antibiotic Appropriateness (Complete ✅)
- [x] ICD-10 indication classification
- [x] Pediatric inpatient modifications
- [x] Febrile neutropenia logic
- [x] Surgical prophylaxis validation

### Phase 2: Agent Appropriateness
- [ ] Parse Cincinnati pocket card
- [ ] Build indication → agent mapping
- [ ] Agent matching logic
- [ ] Real-time agent alerts

### Phase 3: Guideline Adherence Framework
- [ ] Define guideline data structure
- [ ] Implement CAP guideline bundle
- [ ] Implement FN guideline bundle
- [ ] Build compliance checker engine

### Phase 4: Adherence Dashboard
- [ ] Aggregate compliance calculation
- [ ] Trend analysis
- [ ] Unit/service comparisons
- [ ] Drill-down to non-compliant encounters

### Phase 5: Duration Tracking
- [ ] MAR integration for actual duration
- [ ] Auto-stop alerts
- [ ] Duration compliance in bundles

---

## Summary

| Module | Purpose | Scope | Output |
|--------|---------|-------|--------|
| **Appropriateness** | Clinical decision support | Per-order, real-time | Alerts, flags |
| **Adherence** | Quality monitoring | Population, periodic | Dashboards, reports |

Both modules support Joint Commission compliance but serve different operational needs:
- **Appropriateness** → Helps ASP pharmacists intervene on individual orders
- **Adherence** → Helps ASP leadership track program effectiveness and report to JC

The modules share underlying data but have distinct workflows and user interfaces.
