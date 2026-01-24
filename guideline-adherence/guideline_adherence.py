"""
AEGIS Guideline Adherence Monitoring Module
============================================

Tracks adherence to evidence-based treatment algorithms/guidelines for
infectious diseases. Supports Joint Commission MM.09.01.01 EP 18-19
requirement to implement and monitor adherence to guidelines.

This is SEPARATE from antibiotic appropriateness monitoring:
- Appropriateness: Is this antibiotic order justified? (order-level)
- Adherence: Did we follow the full care pathway? (episode-level)

Guidelines include non-antibiotic elements:
- Diagnostic workup (cultures, imaging, labs)
- Antibiotic timing, selection, duration
- Source control interventions
- Consultation requirements
- De-escalation/reassessment checkpoints

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                    AEGIS MONITORING FRAMEWORK                    │
    ├─────────────────────────────────────────────────────────────────┤
    │                                                                 │
    │  ┌─────────────────────┐       ┌─────────────────────┐         │
    │  │  APPROPRIATENESS    │       │  ADHERENCE          │         │
    │  │  MODULE             │       │  MODULE             │         │
    │  │                     │       │                     │         │
    │  │  Order-level        │       │  Episode-level      │         │
    │  │  Real-time alerts   │       │  Bundle scoring     │         │
    │  │  ASP intervention   │       │  Aggregate metrics  │         │
    │  │                     │       │  Quality dashboards │         │
    │  └─────────────────────┘       └─────────────────────┘         │
    │           │                             │                       │
    │           └──────────┬──────────────────┘                       │
    │                      ▼                                          │
    │           ┌─────────────────────┐                               │
    │           │  SHARED DATA LAYER  │                               │
    │           │  - Patient data     │                               │
    │           │  - Orders/MAR       │                               │
    │           │  - Labs/cultures    │                               │
    │           │  - Imaging          │                               │
    │           └─────────────────────┘                               │
    └─────────────────────────────────────────────────────────────────┘

Author: AEGIS Development Team
Version: 1.0.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
from enum import Enum
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import json


# =============================================================================
# CORE DATA STRUCTURES
# =============================================================================

class BundleElementStatus(Enum):
    """Status of individual bundle element compliance."""
    MET = "met"
    NOT_MET = "not_met"
    NOT_APPLICABLE = "na"
    PENDING = "pending"  # Still within window to complete
    UNABLE_TO_ASSESS = "unknown"


class AdherenceLevel(Enum):
    """Overall adherence classification."""
    FULL = "full"           # 100% of applicable elements met
    PARTIAL = "partial"     # >50% but <100% met
    LOW = "low"             # ≤50% met
    NOT_APPLICABLE = "na"   # Guideline doesn't apply


@dataclass
class BundleElement:
    """Single element within a guideline bundle."""
    element_id: str
    name: str
    description: str
    required: bool = True  # vs "recommended"
    time_window_hours: Optional[float] = None  # Time limit relative to trigger
    data_source: str = ""  # Where to find this data (lab, order, imaging, etc.)
    query_logic: str = ""  # How to determine if element was completed
    

@dataclass
class BundleElementResult:
    """Result of checking a single bundle element."""
    element: BundleElement
    status: BundleElementStatus
    timestamp_completed: Optional[datetime] = None
    value: Optional[Any] = None  # The actual value found
    notes: str = ""


@dataclass
class GuidelineBundle:
    """Complete guideline bundle definition."""
    bundle_id: str
    name: str
    description: str
    condition_icd10_codes: List[str]  # Triggering diagnoses
    trigger_criteria: Dict  # Additional criteria to activate bundle
    elements: List[BundleElement] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    version: str = "1.0"
    last_updated: str = ""


@dataclass 
class AdherenceResult:
    """Result of guideline adherence assessment for an episode."""
    patient_mrn: str
    encounter_id: str
    bundle: GuidelineBundle
    assessment_time: datetime
    trigger_time: datetime  # When the guideline was activated
    element_results: List[BundleElementResult] = field(default_factory=list)
    
    @property
    def total_applicable(self) -> int:
        return sum(1 for r in self.element_results 
                   if r.status != BundleElementStatus.NOT_APPLICABLE)
    
    @property
    def total_met(self) -> int:
        return sum(1 for r in self.element_results 
                   if r.status == BundleElementStatus.MET)
    
    @property
    def adherence_percentage(self) -> float:
        if self.total_applicable == 0:
            return 100.0
        return round(self.total_met / self.total_applicable * 100, 1)
    
    @property
    def adherence_level(self) -> AdherenceLevel:
        pct = self.adherence_percentage
        if pct == 100:
            return AdherenceLevel.FULL
        elif pct > 50:
            return AdherenceLevel.PARTIAL
        else:
            return AdherenceLevel.LOW
    
    def to_dict(self) -> Dict:
        return {
            'patient_mrn': self.patient_mrn,
            'encounter_id': self.encounter_id,
            'bundle_id': self.bundle.bundle_id,
            'bundle_name': self.bundle.name,
            'assessment_time': self.assessment_time.isoformat(),
            'trigger_time': self.trigger_time.isoformat(),
            'adherence_percentage': self.adherence_percentage,
            'adherence_level': self.adherence_level.value,
            'elements_met': self.total_met,
            'elements_applicable': self.total_applicable,
            'element_details': [
                {
                    'element_id': r.element.element_id,
                    'name': r.element.name,
                    'required': r.element.required,
                    'status': r.status.value,
                    'completed_at': r.timestamp_completed.isoformat() if r.timestamp_completed else None,
                    'value': r.value,
                    'notes': r.notes
                }
                for r in self.element_results
            ]
        }


# =============================================================================
# GUIDELINE BUNDLE DEFINITIONS
# =============================================================================

# -----------------------------------------------------------------------------
# SEPSIS BUNDLE (based on Surviving Sepsis Campaign pediatric recommendations)
# -----------------------------------------------------------------------------

SEPSIS_BUNDLE = GuidelineBundle(
    bundle_id='sepsis_peds_2024',
    name='Pediatric Sepsis Bundle',
    description='Evidence-based bundle for recognition and treatment of pediatric sepsis',
    condition_icd10_codes=[
        'A41.9', 'A41.01', 'A41.02', 'A41.1', 'A41.2', 'A41.3', 'A41.4', 'A41.5',
        'A41.50', 'A41.51', 'A41.52', 'A41.53', 'A41.59', 'A41.8', 'A41.81', 'A41.89',
        'R65.20', 'R65.21',  # Severe sepsis
        'A40.0', 'A40.1', 'A40.3', 'A40.8', 'A40.9',  # Streptococcal sepsis
        'P36.0', 'P36.1', 'P36.2', 'P36.3', 'P36.4', 'P36.5', 'P36.8', 'P36.9',  # Neonatal
    ],
    trigger_criteria={
        'any_of': ['sepsis_diagnosis', 'sepsis_alert_fired', 'lactate_elevated']
    },
    elements=[
        BundleElement(
            element_id='sepsis_blood_cx',
            name='Blood culture obtained',
            description='Blood culture collected before or within 1 hour of antibiotics',
            required=True,
            time_window_hours=1.0,
            data_source='lab_orders',
            query_logic="order_code IN ('BLDCX', 'BLOOD_CULTURE') AND collected_time <= abx_time + 1h"
        ),
        BundleElement(
            element_id='sepsis_lactate',
            name='Lactate measured',
            description='Serum lactate obtained within 3 hours of sepsis recognition',
            required=True,
            time_window_hours=3.0,
            data_source='lab_results',
            query_logic="test_code = 'LACTATE' AND result_time <= trigger_time + 3h"
        ),
        BundleElement(
            element_id='sepsis_abx_1hr',
            name='Antibiotics within 1 hour',
            description='Broad-spectrum antibiotics administered within 1 hour of recognition',
            required=True,
            time_window_hours=1.0,
            data_source='mar',
            query_logic="antibiotic_admin_time <= trigger_time + 1h"
        ),
        BundleElement(
            element_id='sepsis_fluid_bolus',
            name='Fluid resuscitation initiated',
            description='IV fluid bolus (20 mL/kg) initiated within 1 hour if hypotensive/hypoperfused',
            required=True,  # Required if shock criteria met
            time_window_hours=1.0,
            data_source='mar',
            query_logic="fluid_bolus_given AND bolus_time <= trigger_time + 1h"
        ),
        BundleElement(
            element_id='sepsis_repeat_lactate',
            name='Repeat lactate if initially elevated',
            description='Repeat lactate within 6 hours if initial lactate >2 mmol/L',
            required=False,  # Only if initial elevated
            time_window_hours=6.0,
            data_source='lab_results',
            query_logic="IF initial_lactate > 2 THEN repeat_lactate_time <= trigger_time + 6h"
        ),
        BundleElement(
            element_id='sepsis_reassess_48h',
            name='Antibiotic reassessment at 48 hours',
            description='Documented reassessment of antibiotic therapy at 48-72 hours',
            required=True,
            time_window_hours=72.0,
            data_source='notes',
            query_logic="note_type = 'ID_CONSULT' OR note_type = 'ASP_REVIEW' WITHIN 48-72h"
        ),
    ],
    references=[
        'Surviving Sepsis Campaign International Guidelines 2020',
        'PIDS Pediatric Sepsis Guidelines',
        'Cincinnati Sepsis Pathway'
    ],
    version='2024.1',
    last_updated='2024-01-01'
)


# -----------------------------------------------------------------------------
# COMMUNITY-ACQUIRED PNEUMONIA BUNDLE
# -----------------------------------------------------------------------------

CAP_BUNDLE = GuidelineBundle(
    bundle_id='cap_peds_2024',
    name='Pediatric Community-Acquired Pneumonia Bundle',
    description='Evidence-based bundle for treatment of pediatric CAP (>3 months)',
    condition_icd10_codes=[
        'J13', 'J14', 'J15.0', 'J15.1', 'J15.2', 'J15.3', 'J15.4', 'J15.5',
        'J15.6', 'J15.7', 'J15.8', 'J15.9', 'J16.0', 'J16.8', 'J17', 'J18.0',
        'J18.1', 'J18.8', 'J18.9'
    ],
    trigger_criteria={
        'all_of': ['pneumonia_diagnosis', 'age_months >= 3']
    },
    elements=[
        BundleElement(
            element_id='cap_cxr',
            name='Chest radiograph obtained',
            description='Chest X-ray performed to confirm pneumonia diagnosis',
            required=True,
            time_window_hours=24.0,
            data_source='imaging_orders',
            query_logic="order_code LIKE 'CXR%' AND completed"
        ),
        BundleElement(
            element_id='cap_pulse_ox',
            name='Oxygen saturation documented',
            description='SpO2 measured and documented',
            required=True,
            time_window_hours=4.0,
            data_source='vitals',
            query_logic="vital_type = 'SPO2' AND recorded"
        ),
        BundleElement(
            element_id='cap_abx_appropriate',
            name='Appropriate empiric antibiotic',
            description='First-line antibiotic per guidelines (ampicillin/amoxicillin for typical)',
            required=True,
            time_window_hours=24.0,
            data_source='medication_orders',
            query_logic="antibiotic IN ('ampicillin', 'amoxicillin', 'penicillin') OR documented_exception"
        ),
        BundleElement(
            element_id='cap_blood_cx_severe',
            name='Blood culture if severe/complicated',
            description='Blood culture for patients with severe pneumonia or empyema',
            required=False,  # Only if severe
            time_window_hours=24.0,
            data_source='lab_orders',
            query_logic="IF severe_pneumonia THEN blood_culture_ordered"
        ),
        BundleElement(
            element_id='cap_duration_appropriate',
            name='Treatment duration ≤7 days (uncomplicated)',
            description='Antibiotic duration 5-7 days for uncomplicated CAP',
            required=True,
            time_window_hours=None,  # Assessed at discharge
            data_source='medication_orders',
            query_logic="total_antibiotic_days <= 7 OR documented_exception"
        ),
        BundleElement(
            element_id='cap_followup_arranged',
            name='Follow-up arranged',
            description='Follow-up visit scheduled or communicated for clinical reassessment',
            required=False,
            time_window_hours=None,
            data_source='appointments',
            query_logic="followup_scheduled_within_14_days"
        ),
    ],
    references=[
        'PIDS/IDSA CAP Guidelines 2011',
        'AAP CAP Management Guidelines',
        'Stanford LPCH Pneumonia Pathway'
    ],
    version='2024.1',
    last_updated='2024-01-01'
)


# -----------------------------------------------------------------------------
# UTI BUNDLE
# -----------------------------------------------------------------------------

UTI_BUNDLE = GuidelineBundle(
    bundle_id='uti_peds_2024',
    name='Pediatric Urinary Tract Infection Bundle',
    description='Evidence-based bundle for diagnosis and treatment of pediatric UTI',
    condition_icd10_codes=[
        'N39.0', 'N10', 'N11.0', 'N11.1', 'N11.8', 'N11.9', 'N12',
        'N30.00', 'N30.01', 'N30.10', 'N30.11', 'N30.90', 'N30.91'
    ],
    trigger_criteria={
        'all_of': ['uti_diagnosis']
    },
    elements=[
        BundleElement(
            element_id='uti_ua_obtained',
            name='Urinalysis obtained',
            description='Urinalysis performed before or at time of treatment',
            required=True,
            time_window_hours=24.0,
            data_source='lab_orders',
            query_logic="order_code = 'UA' AND collected"
        ),
        BundleElement(
            element_id='uti_culture_obtained',
            name='Urine culture obtained',
            description='Urine culture collected via appropriate method (cath/clean catch)',
            required=True,
            time_window_hours=24.0,
            data_source='lab_orders',
            query_logic="order_code = 'URINE_CX' AND collected"
        ),
        BundleElement(
            element_id='uti_culture_positive',
            name='Culture confirms diagnosis',
            description='Urine culture positive with appropriate colony count',
            required=True,
            time_window_hours=72.0,
            data_source='lab_results',
            query_logic="urine_cx_cfu >= threshold"  # 50k for cath, 100k for clean catch
        ),
        BundleElement(
            element_id='uti_empiric_appropriate',
            name='Appropriate empiric antibiotic',
            description='Empiric antibiotic based on local resistance patterns',
            required=True,
            time_window_hours=24.0,
            data_source='medication_orders',
            query_logic="antibiotic IN ('cephalexin', 'cefixime', 'TMP-SMX', 'nitrofurantoin')"
        ),
        BundleElement(
            element_id='uti_narrowed_to_culture',
            name='Therapy narrowed to culture results',
            description='Antibiotic adjusted based on culture and susceptibility',
            required=True,
            time_window_hours=96.0,
            data_source='medication_orders',
            query_logic="antibiotic_matches_susceptibility OR documented_reason"
        ),
        BundleElement(
            element_id='uti_rbus_febrile',
            name='Renal ultrasound if febrile UTI',
            description='RBUS for first febrile UTI in children <2 years',
            required=False,  # Age-dependent
            time_window_hours=48.0,
            data_source='imaging_orders',
            query_logic="IF febrile_uti AND age < 24mo THEN rbus_ordered"
        ),
        BundleElement(
            element_id='uti_vcug_considered',
            name='VCUG consideration documented',
            description='VCUG discussed/ordered if abnormal RBUS or recurrent febrile UTI',
            required=False,
            time_window_hours=None,
            data_source='notes',
            query_logic="vcug_discussion_documented"
        ),
    ],
    references=[
        'AAP UTI Guidelines 2011, Reaffirmed 2016',
        'NICE UTI Guidelines',
        'Cincinnati UTI Pathway'
    ],
    version='2024.1',
    last_updated='2024-01-01'
)


# -----------------------------------------------------------------------------
# SKIN AND SOFT TISSUE INFECTION BUNDLE
# -----------------------------------------------------------------------------

SSTI_BUNDLE = GuidelineBundle(
    bundle_id='ssti_peds_2024',
    name='Pediatric Skin and Soft Tissue Infection Bundle',
    description='Evidence-based bundle for management of pediatric SSTI including cellulitis and abscess',
    condition_icd10_codes=[
        'L03.90', 'L03.011', 'L03.012', 'L03.019', 'L03.111', 'L03.112',
        'L03.113', 'L03.114', 'L03.115', 'L03.116', 'L03.119', 'L03.211',
        'L03.212', 'L03.213', 'L03.311', 'L03.312', 'L03.313', 'L03.314',
        'L03.315', 'L03.316', 'L03.317', 'L03.319',
        'L02.01', 'L02.11', 'L02.211', 'L02.212', 'L02.213', 'L02.214',
        'L02.215', 'L02.216', 'L02.219', 'L02.31', 'L02.411', 'L02.412',
        'L02.413', 'L02.414', 'L02.415', 'L02.416', 'L02.419', 'L02.511',
        'L02.512', 'L02.519', 'L02.611', 'L02.612', 'L02.619', 'L02.811',
        'L02.818', 'L02.91'
    ],
    trigger_criteria={
        'any_of': ['cellulitis_diagnosis', 'abscess_diagnosis']
    },
    elements=[
        BundleElement(
            element_id='ssti_margins_marked',
            name='Cellulitis margins marked',
            description='Borders of cellulitis marked to monitor progression',
            required=True,
            time_window_hours=12.0,
            data_source='nursing_notes',
            query_logic="documentation CONTAINS 'margins marked' OR 'borders outlined'"
        ),
        BundleElement(
            element_id='ssti_mrsa_coverage',
            name='MRSA coverage if indicated',
            description='Antibiotic with MRSA activity if purulent or MRSA risk factors',
            required=False,  # Depends on presentation
            time_window_hours=24.0,
            data_source='medication_orders',
            query_logic="IF purulent THEN antibiotic HAS mrsa_coverage"
        ),
        BundleElement(
            element_id='ssti_id_no_purulence',
            name='I&D performed if purulent/abscess',
            description='Incision and drainage performed for abscess or purulent collection',
            required=False,  # Only if purulent
            time_window_hours=24.0,
            data_source='procedure_orders',
            query_logic="IF abscess THEN id_performed"
        ),
        BundleElement(
            element_id='ssti_culture_purulent',
            name='Wound culture if I&D performed',
            description='Culture obtained from drained purulent material',
            required=False,
            time_window_hours=24.0,
            data_source='lab_orders',
            query_logic="IF id_performed THEN wound_culture_obtained"
        ),
        BundleElement(
            element_id='ssti_no_abx_simple_abscess',
            name='No antibiotics for simple abscess (post-I&D)',
            description='Simple abscess treated with I&D alone (no antibiotics) per guidelines',
            required=False,
            time_window_hours=None,
            data_source='medication_orders',
            query_logic="IF simple_abscess_post_id THEN no_antibiotic_ordered"
        ),
        BundleElement(
            element_id='ssti_reassess_48h',
            name='Clinical reassessment at 48-72h',
            description='Documented reassessment of clinical response',
            required=True,
            time_window_hours=72.0,
            data_source='notes',
            query_logic="reassessment_documented_48_72h"
        ),
    ],
    references=[
        'IDSA SSTI Guidelines 2014',
        'PIDS MRSA Guidelines',
        'Cincinnati SSTI Pathway'
    ],
    version='2024.1',
    last_updated='2024-01-01'
)


# -----------------------------------------------------------------------------
# SURGICAL PROPHYLAXIS BUNDLE
# -----------------------------------------------------------------------------

SURGICAL_PROPHYLAXIS_BUNDLE = GuidelineBundle(
    bundle_id='surgical_prophy_2024',
    name='Surgical Antimicrobial Prophylaxis Bundle',
    description='Evidence-based bundle for appropriate surgical antimicrobial prophylaxis',
    condition_icd10_codes=[],  # Triggered by CPT codes, not ICD-10
    trigger_criteria={
        'any_of': ['surgical_procedure_requiring_prophylaxis']
    },
    elements=[
        BundleElement(
            element_id='surg_abx_selection',
            name='Appropriate prophylactic antibiotic selected',
            description='Antibiotic matches guideline recommendation for procedure type',
            required=True,
            time_window_hours=None,
            data_source='medication_orders',
            query_logic="antibiotic IN procedure_recommended_agents"
        ),
        BundleElement(
            element_id='surg_abx_timing',
            name='Antibiotic given within 60 minutes of incision',
            description='Prophylaxis administered 0-60 min before surgical incision',
            required=True,
            time_window_hours=1.0,
            data_source='mar',
            query_logic="admin_time BETWEEN (incision_time - 60min) AND incision_time"
        ),
        BundleElement(
            element_id='surg_abx_weight_dose',
            name='Appropriate weight-based dosing',
            description='Dose appropriate for patient weight',
            required=True,
            time_window_hours=None,
            data_source='medication_orders',
            query_logic="dose_mg_kg >= recommended_dose_mg_kg"
        ),
        BundleElement(
            element_id='surg_abx_redose',
            name='Redosing for prolonged procedures',
            description='Redose given if procedure duration exceeds 2 half-lives',
            required=False,  # Only if prolonged
            time_window_hours=None,
            data_source='mar',
            query_logic="IF procedure_hours > redose_threshold THEN redose_given"
        ),
        BundleElement(
            element_id='surg_abx_discontinued',
            name='Prophylaxis discontinued within 24-48 hours',
            description='Prophylactic antibiotics stopped within guideline timeframe',
            required=True,
            time_window_hours=48.0,
            data_source='medication_orders',
            query_logic="last_dose_time <= incision_time + max_duration_hours"
        ),
    ],
    references=[
        'ASHP/IDSA/SHEA/SIS Surgical Prophylaxis Guidelines 2013',
        'SCIP Measures',
        'Cincinnati Surgical Prophylaxis Protocol'
    ],
    version='2024.1',
    last_updated='2024-01-01'
)


# -----------------------------------------------------------------------------
# FEBRILE NEUTROPENIA BUNDLE
# -----------------------------------------------------------------------------

FEBRILE_NEUTROPENIA_BUNDLE = GuidelineBundle(
    bundle_id='fn_peds_2024',
    name='Pediatric Febrile Neutropenia Bundle',
    description='Evidence-based bundle for management of febrile neutropenia',
    condition_icd10_codes=[
        'D70.0', 'D70.1', 'D70.2', 'D70.3', 'D70.4', 'D70.8', 'D70.9'
    ],
    trigger_criteria={
        'all_of': ['neutropenia', 'fever']
    },
    elements=[
        BundleElement(
            element_id='fn_blood_cx_peripheral',
            name='Peripheral blood culture obtained',
            description='Blood culture from peripheral site',
            required=True,
            time_window_hours=1.0,
            data_source='lab_orders',
            query_logic="blood_cx_peripheral_obtained"
        ),
        BundleElement(
            element_id='fn_blood_cx_central',
            name='Central line blood culture (if present)',
            description='Blood culture from central line if patient has CVC',
            required=False,  # Only if CVC present
            time_window_hours=1.0,
            data_source='lab_orders',
            query_logic="IF has_cvc THEN blood_cx_from_line_obtained"
        ),
        BundleElement(
            element_id='fn_abx_1hr',
            name='Empiric antibiotics within 1 hour',
            description='Broad-spectrum empiric therapy initiated within 1 hour of fever',
            required=True,
            time_window_hours=1.0,
            data_source='mar',
            query_logic="antibiotic_admin_time <= fever_time + 1h"
        ),
        BundleElement(
            element_id='fn_abx_appropriate',
            name='Appropriate empiric regimen',
            description='Antipseudomonal beta-lactam monotherapy or per protocol',
            required=True,
            time_window_hours=1.0,
            data_source='medication_orders',
            query_logic="antibiotic IN ('cefepime', 'piperacillin-tazobactam', 'meropenem')"
        ),
        BundleElement(
            element_id='fn_risk_stratification',
            name='Risk stratification performed',
            description='High vs low risk assessment documented',
            required=True,
            time_window_hours=24.0,
            data_source='notes',
            query_logic="risk_stratification_documented"
        ),
        BundleElement(
            element_id='fn_daily_assessment',
            name='Daily reassessment documented',
            description='Daily assessment of need for continued antibiotics',
            required=True,
            time_window_hours=24.0,
            data_source='notes',
            query_logic="daily_fn_assessment_documented"
        ),
    ],
    references=[
        'IDSA Febrile Neutropenia Guidelines',
        'COG Supportive Care Guidelines',
        'Cincinnati FN Protocol'
    ],
    version='2024.1',
    last_updated='2024-01-01'
)


# -----------------------------------------------------------------------------
# FEBRILE INFANT BUNDLE (AAP 2021 Guideline)
# -----------------------------------------------------------------------------

FEBRILE_INFANT_BUNDLE = GuidelineBundle(
    bundle_id='febrile_infant_2024',
    name='Febrile Infant Bundle (0-60 days)',
    description='Evidence-based bundle for evaluation of well-appearing febrile infants 8-60 days old (AAP 2021)',
    condition_icd10_codes=[
        'R50.9',   # Fever, unspecified
        'R50.81',  # Fever presenting with conditions classified elsewhere
        'R50.82',  # Postprocedural fever
        'R50.83',  # Postvaccination fever
        'R50.84',  # Febrile nonhemolytic transfusion reaction
        'P81.9',   # Disturbance of temperature regulation of newborn
    ],
    trigger_criteria={
        'all_of': ['fever', 'age_days <= 60', 'well_appearing']
    },
    elements=[
        # Workup elements - all age groups
        BundleElement(
            element_id='fi_ua',
            name='Urinalysis obtained',
            description='Urinalysis performed via catheter or suprapubic aspiration',
            required=True,
            time_window_hours=2.0,
            data_source='lab_orders',
            query_logic="order_code IN ('UA', 'URINALYSIS') AND collected"
        ),
        BundleElement(
            element_id='fi_blood_culture',
            name='Blood culture obtained',
            description='Blood culture obtained prior to antibiotics',
            required=True,
            time_window_hours=2.0,
            data_source='lab_orders',
            query_logic="order_code = 'BLOOD_CULTURE' AND collected_time <= abx_time"
        ),
        BundleElement(
            element_id='fi_inflammatory_markers',
            name='Inflammatory markers obtained',
            description='ANC and CRP obtained; procalcitonin recommended for 29-60 days',
            required=True,
            time_window_hours=2.0,
            data_source='lab_results',
            query_logic="(ANC IS NOT NULL OR CRP IS NOT NULL)"
        ),
        BundleElement(
            element_id='fi_procalcitonin',
            name='Procalcitonin obtained (29-60 days)',
            description='Procalcitonin recommended for infants 29-60 days; most useful if fever onset >6 hours',
            required=False,  # Recommended, not required
            time_window_hours=2.0,
            data_source='lab_results',
            query_logic="PCT IS NOT NULL"
        ),
        # LP elements - age-stratified
        BundleElement(
            element_id='fi_lp_8_21d',
            name='LP performed (8-21 days)',
            description='Lumbar puncture required for all febrile infants 8-21 days',
            required=True,  # Required for 8-21 days
            time_window_hours=2.0,
            data_source='procedure_orders',
            query_logic="procedure_code = 'LUMBAR_PUNCTURE' AND age_days BETWEEN 8 AND 21"
        ),
        BundleElement(
            element_id='fi_lp_22_28d_im_abnormal',
            name='LP performed (22-28 days, IMs abnormal)',
            description='LP required if inflammatory markers abnormal in 22-28 day old',
            required=True,  # Required if IMs abnormal
            time_window_hours=2.0,
            data_source='procedure_orders',
            query_logic="procedure_code = 'LUMBAR_PUNCTURE' AND age_days BETWEEN 22 AND 28 AND inflammatory_markers_abnormal"
        ),
        # Treatment elements
        BundleElement(
            element_id='fi_abx_8_21d',
            name='Parenteral antibiotics (8-21 days)',
            description='Start parenteral antimicrobials for all febrile infants 8-21 days',
            required=True,
            time_window_hours=1.0,
            data_source='mar',
            query_logic="antibiotic_route = 'IV' AND age_days BETWEEN 8 AND 21"
        ),
        BundleElement(
            element_id='fi_abx_22_28d_im_abnormal',
            name='Parenteral antibiotics (22-28 days, IMs abnormal)',
            description='Start empiric parenteral antimicrobials if inflammatory markers abnormal',
            required=True,
            time_window_hours=1.0,
            data_source='mar',
            query_logic="antibiotic_route = 'IV' AND age_days BETWEEN 22 AND 28 AND inflammatory_markers_abnormal"
        ),
        # HSV consideration
        BundleElement(
            element_id='fi_hsv_risk_assessment',
            name='HSV risk assessment',
            description='Consider HSV risk factors and need for acyclovir (8-28 days)',
            required=True,  # Required for 8-28 days
            time_window_hours=4.0,
            data_source='notes',
            query_logic="documentation CONTAINS 'HSV' OR acyclovir_ordered"
        ),
        # Disposition elements
        BundleElement(
            element_id='fi_admit_8_21d',
            name='Hospital admission (8-21 days)',
            description='Admit to hospital for all febrile infants 8-21 days',
            required=True,
            time_window_hours=None,
            data_source='encounter',
            query_logic="encounter_type = 'INPATIENT' AND age_days BETWEEN 8 AND 21"
        ),
        BundleElement(
            element_id='fi_admit_22_28d_im_abnormal',
            name='Hospital admission (22-28 days, IMs abnormal)',
            description='Admit to hospital if inflammatory markers abnormal',
            required=True,
            time_window_hours=None,
            data_source='encounter',
            query_logic="encounter_type = 'INPATIENT' AND age_days BETWEEN 22 AND 28 AND inflammatory_markers_abnormal"
        ),
        BundleElement(
            element_id='fi_safe_discharge_checklist',
            name='Safe discharge checklist',
            description='If discharging: documented follow-up within 24h, working phone number, reliable transportation',
            required=False,  # Only if discharging
            time_window_hours=None,
            data_source='notes',
            query_logic="(disposition = 'HOME' AND followup_documented AND contact_documented)"
        ),
    ],
    references=[
        'AAP Clinical Practice Guideline: Evaluation and Management of Well-Appearing Febrile Infants 8 to 60 Days Old. Pediatrics. August 2021',
        'Cincinnati Childrens Febrile Infant Pathway',
        'PECARN Febrile Infant Studies'
    ],
    version='2024.1',
    last_updated='2024-01-01'
)


# =============================================================================
# ALL BUNDLES REGISTRY
# =============================================================================

GUIDELINE_BUNDLES: Dict[str, GuidelineBundle] = {
    'sepsis_peds_2024': SEPSIS_BUNDLE,
    'cap_peds_2024': CAP_BUNDLE,
    'uti_peds_2024': UTI_BUNDLE,
    'ssti_peds_2024': SSTI_BUNDLE,
    'surgical_prophy_2024': SURGICAL_PROPHYLAXIS_BUNDLE,
    'fn_peds_2024': FEBRILE_NEUTROPENIA_BUNDLE,
    'febrile_infant_2024': FEBRILE_INFANT_BUNDLE,
}


# =============================================================================
# ADHERENCE CHECKER CLASS
# =============================================================================

class GuidelineAdherenceChecker:
    """
    Checks guideline bundle adherence for patient episodes.
    
    This is an abstract base that needs to be implemented with actual
    data source connections (Epic FHIR, database, etc.)
    """
    
    def __init__(self, bundles: Dict[str, GuidelineBundle] = None):
        """Initialize with available guideline bundles."""
        self.bundles = bundles or GUIDELINE_BUNDLES
    
    def identify_applicable_bundles(
        self,
        icd10_codes: List[str],
        cpt_codes: Optional[List[str]] = None,
        patient_age_months: Optional[int] = None
    ) -> List[GuidelineBundle]:
        """
        Identify which guideline bundles apply to this patient/encounter.
        
        Args:
            icd10_codes: Active diagnosis codes
            cpt_codes: Procedure codes (for surgical prophylaxis)
            patient_age_months: Patient age in months
            
        Returns:
            List of applicable GuidelineBundle objects
        """
        applicable = []
        
        for bundle_id, bundle in self.bundles.items():
            # Check if any ICD-10 codes match
            for code in icd10_codes:
                for bundle_code in bundle.condition_icd10_codes:
                    if code.startswith(bundle_code):
                        applicable.append(bundle)
                        break
                else:
                    continue
                break
        
        # Special handling for surgical prophylaxis (CPT-based)
        if cpt_codes:
            from pediatric_abx_indications import SURGICAL_PROPHYLAXIS_CPT
            for cpt in cpt_codes:
                if cpt in SURGICAL_PROPHYLAXIS_CPT:
                    info = SURGICAL_PROPHYLAXIS_CPT[cpt]
                    if info.prophylaxis_indicated:
                        if SURGICAL_PROPHYLAXIS_BUNDLE not in applicable:
                            applicable.append(SURGICAL_PROPHYLAXIS_BUNDLE)
                        break
        
        return applicable
    
    def check_bundle_adherence(
        self,
        patient_mrn: str,
        encounter_id: str,
        bundle: GuidelineBundle,
        trigger_time: datetime,
        clinical_data: Dict
    ) -> AdherenceResult:
        """
        Check adherence to a specific guideline bundle.
        
        Args:
            patient_mrn: Patient identifier
            encounter_id: Encounter identifier
            bundle: The guideline bundle to check
            trigger_time: When the bundle was activated (e.g., sepsis recognition)
            clinical_data: Dict containing clinical data for assessment
                Expected keys: labs, vitals, medications, orders, notes, procedures
                
        Returns:
            AdherenceResult with element-by-element assessment
        """
        element_results = []
        
        for element in bundle.elements:
            result = self._check_element(element, trigger_time, clinical_data)
            element_results.append(result)
        
        return AdherenceResult(
            patient_mrn=patient_mrn,
            encounter_id=encounter_id,
            bundle=bundle,
            assessment_time=datetime.now(),
            trigger_time=trigger_time,
            element_results=element_results
        )
    
    def _check_element(
        self,
        element: BundleElement,
        trigger_time: datetime,
        clinical_data: Dict
    ) -> BundleElementResult:
        """
        Check a single bundle element.
        
        This is a placeholder - real implementation needs actual data queries.
        """
        # This would be implemented with actual FHIR queries or database lookups
        # For now, return UNABLE_TO_ASSESS
        return BundleElementResult(
            element=element,
            status=BundleElementStatus.UNABLE_TO_ASSESS,
            notes="Data connection not implemented - requires FHIR integration"
        )


# =============================================================================
# DASHBOARD AGGREGATION
# =============================================================================

@dataclass
class AdherenceDashboardMetrics:
    """Aggregated adherence metrics for dashboard display."""
    time_period_start: datetime
    time_period_end: datetime
    bundle_id: str
    bundle_name: str
    total_episodes: int
    full_adherence_count: int
    partial_adherence_count: int
    low_adherence_count: int
    average_adherence_percentage: float
    element_adherence_rates: Dict[str, float]  # element_id -> % met
    by_unit: Dict[str, Dict]  # unit_name -> metrics
    by_provider: Dict[str, Dict]  # provider_id -> metrics
    trend_data: List[Dict]  # [{date, adherence_pct}, ...]


class AdherenceDashboard:
    """
    Generates aggregated adherence metrics for QI dashboards.
    """
    
    def __init__(self, checker: GuidelineAdherenceChecker):
        self.checker = checker
    
    def generate_metrics(
        self,
        results: List[AdherenceResult],
        group_by_unit: bool = True,
        group_by_provider: bool = False
    ) -> AdherenceDashboardMetrics:
        """
        Generate dashboard metrics from a list of adherence results.
        
        Args:
            results: List of AdherenceResult objects
            group_by_unit: Include breakdown by hospital unit
            group_by_provider: Include breakdown by ordering provider
            
        Returns:
            AdherenceDashboardMetrics for dashboard display
        """
        if not results:
            return None
        
        bundle = results[0].bundle
        
        # Overall metrics
        total = len(results)
        full = sum(1 for r in results if r.adherence_level == AdherenceLevel.FULL)
        partial = sum(1 for r in results if r.adherence_level == AdherenceLevel.PARTIAL)
        low = sum(1 for r in results if r.adherence_level == AdherenceLevel.LOW)
        avg_pct = sum(r.adherence_percentage for r in results) / total
        
        # Element-level rates
        element_rates = {}
        for element in bundle.elements:
            met_count = sum(
                1 for r in results
                for er in r.element_results
                if er.element.element_id == element.element_id 
                and er.status == BundleElementStatus.MET
            )
            applicable_count = sum(
                1 for r in results
                for er in r.element_results
                if er.element.element_id == element.element_id
                and er.status != BundleElementStatus.NOT_APPLICABLE
            )
            if applicable_count > 0:
                element_rates[element.element_id] = round(met_count / applicable_count * 100, 1)
        
        return AdherenceDashboardMetrics(
            time_period_start=min(r.trigger_time for r in results),
            time_period_end=max(r.trigger_time for r in results),
            bundle_id=bundle.bundle_id,
            bundle_name=bundle.name,
            total_episodes=total,
            full_adherence_count=full,
            partial_adherence_count=partial,
            low_adherence_count=low,
            average_adherence_percentage=round(avg_pct, 1),
            element_adherence_rates=element_rates,
            by_unit={},  # Would need unit data from encounter
            by_provider={},  # Would need provider data
            trend_data=[]  # Would need historical data
        )
    
    def export_to_json(self, metrics: AdherenceDashboardMetrics) -> str:
        """Export metrics to JSON for web dashboard."""
        return json.dumps({
            'time_period': {
                'start': metrics.time_period_start.isoformat(),
                'end': metrics.time_period_end.isoformat()
            },
            'bundle': {
                'id': metrics.bundle_id,
                'name': metrics.bundle_name
            },
            'summary': {
                'total_episodes': metrics.total_episodes,
                'full_adherence': metrics.full_adherence_count,
                'partial_adherence': metrics.partial_adherence_count,
                'low_adherence': metrics.low_adherence_count,
                'average_percentage': metrics.average_adherence_percentage
            },
            'element_rates': metrics.element_adherence_rates,
            'by_unit': metrics.by_unit,
            'by_provider': metrics.by_provider,
            'trend': metrics.trend_data
        }, indent=2)


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == '__main__':
    print("="*70)
    print("AEGIS GUIDELINE ADHERENCE MODULE")
    print("="*70)
    
    # List available bundles
    print("\nAvailable Guideline Bundles:")
    print("-"*70)
    for bundle_id, bundle in GUIDELINE_BUNDLES.items():
        print(f"\n{bundle.name} ({bundle_id})")
        print(f"  ICD-10 triggers: {len(bundle.condition_icd10_codes)} codes")
        print(f"  Elements: {len(bundle.elements)}")
        for element in bundle.elements:
            req = "Required" if element.required else "Recommended"
            window = f"within {element.time_window_hours}h" if element.time_window_hours else "at discharge"
            print(f"    - [{req}] {element.name} ({window})")
    
    # Example: Check which bundles apply
    print("\n" + "="*70)
    print("BUNDLE IDENTIFICATION EXAMPLE")
    print("="*70)
    
    checker = GuidelineAdherenceChecker()
    
    # Patient with sepsis
    applicable = checker.identify_applicable_bundles(
        icd10_codes=['A41.9', 'J18.9'],  # Sepsis + Pneumonia
        patient_age_months=36
    )
    
    print(f"\nPatient with ICD-10: A41.9 (Sepsis), J18.9 (Pneumonia)")
    print(f"Applicable bundles: {[b.name for b in applicable]}")
    
    # Patient with surgical procedure
    applicable = checker.identify_applicable_bundles(
        icd10_codes=['K80.20'],  # Cholelithiasis
        cpt_codes=['47562']      # Lap chole
    )
    
    print(f"\nPatient with CPT 47562 (Lap Chole)")
    print(f"Applicable bundles: {[b.name for b in applicable]}")
