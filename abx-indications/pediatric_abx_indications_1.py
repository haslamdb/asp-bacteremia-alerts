"""
Pediatric Antibiotic Indication Classifier for AEGIS
=====================================================

Based on Chua et al. BMJ 2019 ICD-10 classification with modifications
for pediatric inpatient antimicrobial stewardship.

Categories:
    A = Always appropriate (antibiotic indicated)
    S = Sometimes appropriate (clinical judgment needed)
    N = Never appropriate (antibiotic not indicated)
    P = Prophylaxis (surgical or medical prophylaxis indication)

Usage:
    from pediatric_abx_indications import AntibioticIndicationClassifier
    
    classifier = AntibioticIndicationClassifier('path/to/chuk046645_ww2.csv')
    result = classifier.classify(
        icd10_codes=['J18.9', 'R78.81'],
        cpt_codes=['47562'],
        fever_present=True
    )

Author: AEGIS Development Team
Version: 1.0.0
Last Updated: 2025-01-24
"""

import csv
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum
from datetime import timedelta


class IndicationCategory(Enum):
    """Antibiotic indication categories"""
    ALWAYS = 'A'
    SOMETIMES = 'S'
    NEVER = 'N'
    PROPHYLAXIS = 'P'
    FEBRILE_NEUTROPENIA = 'FN'
    UNKNOWN = 'U'


@dataclass
class ClassificationResult:
    """Result of antibiotic indication classification"""
    overall_category: IndicationCategory
    primary_indication: Optional[str] = None
    primary_code: Optional[str] = None
    all_indications: List[Dict] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'overall_category': self.overall_category.value,
            'category_description': self._category_description(),
            'primary_indication': self.primary_indication,
            'primary_code': self.primary_code,
            'all_indications': self.all_indications,
            'flags': self.flags,
            'recommendations': self.recommendations
        }
    
    def _category_description(self) -> str:
        descriptions = {
            IndicationCategory.ALWAYS: "Antibiotic indicated - documented infection",
            IndicationCategory.SOMETIMES: "Review recommended - may or may not need antibiotics",
            IndicationCategory.NEVER: "No documented indication for antibiotics",
            IndicationCategory.PROPHYLAXIS: "Surgical/medical prophylaxis indication",
            IndicationCategory.FEBRILE_NEUTROPENIA: "Febrile neutropenia - antibiotic indicated",
            IndicationCategory.UNKNOWN: "Diagnosis code not found in classification"
        }
        return descriptions.get(self.overall_category, "Unknown")


# =============================================================================
# PEDIATRIC INPATIENT MODIFICATIONS TO CHUA CLASSIFICATION
# =============================================================================
# These override the base Chua classification for inpatient pediatric use

PEDIATRIC_INPATIENT_OVERRIDES: Dict[str, Tuple[str, str]] = {
    # Format: 'ICD10_CODE': ('NEW_CATEGORY', 'RATIONALE')
    
    # BACTEREMIA - Upgrade from N to A for inpatient
    'R78.81': ('A', 'Bacteremia requires treatment in inpatient setting'),
    
    # ASPIRATION PNEUMONIA - Upgrade from N to S
    'J69.0': ('S', 'Aspiration pneumonitis often requires empiric antibiotics'),
    'J69.1': ('S', 'Lipoid pneumonia may require antibiotics if superinfected'),
    'J69.8': ('S', 'Aspiration pneumonitis - clinical judgment needed'),
    
    # VIRAL MENINGITIS - Keep as N but flag for review
    # (Already N in Chua, which is correct)
    
    # CANDIDAL INFECTIONS - Keep N for antibacterials, but flag for antifungal review
    # B37.7 Candidal sepsis - N for antibacterials (correct)
    # B37.6 Candidal endocarditis - N for antibacterials (correct)
    
    # PERITONITIS - Ensure all are A
    'K65.0': ('A', 'Generalized acute peritonitis'),
    'K65.1': ('A', 'Peritoneal abscess'),
    'K65.2': ('A', 'Spontaneous bacterial peritonitis'),
    'K65.3': ('A', 'Choleperitonitis'),
    'K65.4': ('A', 'Sclerosing mesenteritis'),
    'K65.8': ('A', 'Other peritonitis'),
    'K65.9': ('A', 'Peritonitis, unspecified'),
    
    # CHOLANGITIS - Upgrade to A
    'K83.0': ('A', 'Cholangitis requires antibiotics'),
    'K83.09': ('A', 'Other cholangitis'),
    
    # EMPYEMA - Ensure A
    'J86.0': ('A', 'Pyothorax with fistula'),
    'J86.9': ('A', 'Pyothorax without fistula'),
    
    # INFECTED DEVICES - Ensure A for all
    'T82.7XXA': ('A', 'Infection of cardiac/vascular device - initial'),
    'T83.51XA': ('A', 'Infection of urinary catheter - initial'),
    'T84.50XA': ('A', 'Infection of joint prosthesis - initial'),
    'T85.79XA': ('A', 'Infection of other internal prosthetic device - initial'),
}


# =============================================================================
# FEBRILE NEUTROPENIA LOGIC
# =============================================================================

# Neutropenia codes (base classification is S - Sometimes)
NEUTROPENIA_CODES: Set[str] = {
    'D70',      # Neutropenia (parent code)
    'D70.0',    # Congenital agranulocytosis
    'D70.1',    # Agranulocytosis secondary to cancer chemotherapy
    'D70.2',    # Other drug-induced agranulocytosis
    'D70.3',    # Neutropenia due to infection
    'D70.4',    # Cyclic neutropenia
    'D70.8',    # Other neutropenia
    'D70.9',    # Neutropenia, unspecified
}

# Fever codes
FEVER_CODES: Set[str] = {
    'R50',      # Fever of other and unknown origin (parent)
    'R50.2',    # Drug induced fever
    'R50.8',    # Other specified fever
    'R50.81',   # Fever presenting with conditions classified elsewhere
    'R50.82',   # Postprocedural fever
    'R50.83',   # Postvaccination fever
    'R50.84',   # Febrile nonhemolytic transfusion reaction
    'R50.9',    # Fever, unspecified
}

# Immunocompromised state codes (enhance febrile neutropenia logic)
IMMUNOCOMPROMISED_CODES: Set[str] = {
    'D80.0',    # Hereditary hypogammaglobulinemia
    'D80.1',    # Nonfamilial hypogammaglobulinemia
    'D81.0',    # SCID with reticular dysgenesis
    'D81.1',    # SCID with low T- and B-cell numbers
    'D81.2',    # SCID with low or normal B-cell numbers
    'D82.0',    # Wiskott-Aldrich syndrome
    'D82.1',    # Di George's syndrome
    'D83.0',    # Common variable immunodeficiency with predominant abnormalities
    'D84.9',    # Immunodeficiency, unspecified
    'Z94.81',   # Bone marrow transplant status
    'Z94.84',   # Stem cells transplant status
    'C91.00',   # ALL not having achieved remission
    'C91.01',   # ALL in remission
    'C91.02',   # ALL in relapse
    'C92.00',   # AML not having achieved remission
    'C92.01',   # AML in remission
    'C92.02',   # AML in relapse
}


# =============================================================================
# SURGICAL PROPHYLAXIS CPT CODES
# =============================================================================

@dataclass
class SurgicalProphylaxisInfo:
    """Information about surgical prophylaxis for a procedure"""
    procedure_name: str
    prophylaxis_indicated: bool
    recommended_agents: List[str]
    max_duration_hours: int
    special_considerations: Optional[str] = None
    weight_based_dosing: bool = True
    redosing_interval_hours: Optional[int] = None


# Comprehensive surgical prophylaxis table
# Based on ASHP/IDSA/SHEA/SIS guidelines adapted for pediatrics
SURGICAL_PROPHYLAXIS_CPT: Dict[str, SurgicalProphylaxisInfo] = {
    
    # =========================================================================
    # CARDIAC SURGERY
    # =========================================================================
    '33400': SurgicalProphylaxisInfo(
        procedure_name='Ventricular septal defect repair',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=48,
        redosing_interval_hours=4,
        special_considerations='Vancomycin for MRSA colonization or institutional MRSA rates >10%'
    ),
    '33405': SurgicalProphylaxisInfo(
        procedure_name='Aortic valve replacement',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=48,
        redosing_interval_hours=4
    ),
    '33426': SurgicalProphylaxisInfo(
        procedure_name='Mitral valve repair',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=48,
        redosing_interval_hours=4
    ),
    '33533': SurgicalProphylaxisInfo(
        procedure_name='CABG with arterial graft',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=48,
        redosing_interval_hours=4
    ),
    '33945': SurgicalProphylaxisInfo(
        procedure_name='Heart transplant',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin'],
        max_duration_hours=48,
        special_considerations='May extend based on transplant protocol'
    ),
    
    # =========================================================================
    # THORACIC SURGERY
    # =========================================================================
    '32480': SurgicalProphylaxisInfo(
        procedure_name='Lobectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'ampicillin-sulbactam'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '32440': SurgicalProphylaxisInfo(
        procedure_name='Pneumonectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'ampicillin-sulbactam'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    
    # =========================================================================
    # ABDOMINAL - HEPATOBILIARY
    # =========================================================================
    '47562': SurgicalProphylaxisInfo(
        procedure_name='Laparoscopic cholecystectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24,
        special_considerations='Single dose often sufficient for low-risk'
    ),
    '47600': SurgicalProphylaxisInfo(
        procedure_name='Open cholecystectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'cefoxitin', 'ampicillin-sulbactam'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '47100': SurgicalProphylaxisInfo(
        procedure_name='Liver biopsy, wedge',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0
    ),
    '47135': SurgicalProphylaxisInfo(
        procedure_name='Liver transplant',
        prophylaxis_indicated=True,
        recommended_agents=['piperacillin-tazobactam', 'ampicillin-sulbactam'],
        max_duration_hours=48,
        special_considerations='Follow transplant protocol; may need antifungal'
    ),
    
    # =========================================================================
    # ABDOMINAL - COLORECTAL
    # =========================================================================
    '44140': SurgicalProphylaxisInfo(
        procedure_name='Colectomy, partial',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin + metronidazole', 'ertapenem', 'cefoxitin'],
        max_duration_hours=24,
        redosing_interval_hours=4,
        special_considerations='Mechanical bowel prep + oral antibiotics may be added'
    ),
    '44150': SurgicalProphylaxisInfo(
        procedure_name='Colectomy, total',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin + metronidazole', 'ertapenem', 'cefoxitin'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '44950': SurgicalProphylaxisInfo(
        procedure_name='Appendectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefoxitin', 'cefazolin + metronidazole'],
        max_duration_hours=24,
        special_considerations='If perforated/gangrenous, treat as infection not prophylaxis'
    ),
    '44960': SurgicalProphylaxisInfo(
        procedure_name='Appendectomy for ruptured appendix',
        prophylaxis_indicated=False,  # This is TREATMENT, not prophylaxis
        recommended_agents=['piperacillin-tazobactam', 'ceftriaxone + metronidazole'],
        max_duration_hours=0,  # Treatment duration varies
        special_considerations='TREATMENT indication, not prophylaxis - 5-7 days typical'
    ),
    '45100': SurgicalProphylaxisInfo(
        procedure_name='Rectal biopsy',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0
    ),
    '45110': SurgicalProphylaxisInfo(
        procedure_name='Proctectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin + metronidazole', 'ertapenem'],
        max_duration_hours=24
    ),
    
    # =========================================================================
    # ABDOMINAL - GASTRIC/ESOPHAGEAL
    # =========================================================================
    '43280': SurgicalProphylaxisInfo(
        procedure_name='Laparoscopic fundoplication',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '43631': SurgicalProphylaxisInfo(
        procedure_name='Gastrectomy, partial',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    
    # =========================================================================
    # GENITOURINARY
    # =========================================================================
    '50540': SurgicalProphylaxisInfo(
        procedure_name='Pyeloplasty',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'TMP-SMX'],
        max_duration_hours=24,
        special_considerations='Culture urine preop; adjust based on culture'
    ),
    '50220': SurgicalProphylaxisInfo(
        procedure_name='Nephrectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '50360': SurgicalProphylaxisInfo(
        procedure_name='Kidney transplant',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24,
        special_considerations='Follow transplant protocol'
    ),
    '51040': SurgicalProphylaxisInfo(
        procedure_name='Cystostomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'fluoroquinolone'],
        max_duration_hours=24
    ),
    '52000': SurgicalProphylaxisInfo(
        procedure_name='Cystourethroscopy',
        prophylaxis_indicated=False,
        recommended_agents=['TMP-SMX', 'fluoroquinolone'],
        max_duration_hours=0,
        special_considerations='Prophylaxis only if risk factors present'
    ),
    '54150': SurgicalProphylaxisInfo(
        procedure_name='Circumcision (surgical)',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0
    ),
    '54640': SurgicalProphylaxisInfo(
        procedure_name='Orchiopexy',
        prophylaxis_indicated=False,
        recommended_agents=['cefazolin'],
        max_duration_hours=0,
        special_considerations='Consider single dose if prosthetic material used'
    ),
    '55700': SurgicalProphylaxisInfo(
        procedure_name='Prostate biopsy',
        prophylaxis_indicated=True,
        recommended_agents=['fluoroquinolone', 'TMP-SMX'],
        max_duration_hours=24
    ),
    
    # =========================================================================
    # ORTHOPEDIC
    # =========================================================================
    '27130': SurgicalProphylaxisInfo(
        procedure_name='Total hip arthroplasty',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '27447': SurgicalProphylaxisInfo(
        procedure_name='Total knee arthroplasty',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '27236': SurgicalProphylaxisInfo(
        procedure_name='Open treatment of femoral fracture',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '22800': SurgicalProphylaxisInfo(
        procedure_name='Spinal fusion, posterior',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=24,
        redosing_interval_hours=4,
        special_considerations='Consider extending if hardware placed'
    ),
    '22630': SurgicalProphylaxisInfo(
        procedure_name='Spinal fusion with interbody technique',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '28296': SurgicalProphylaxisInfo(
        procedure_name='Bunionectomy with implant',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '29881': SurgicalProphylaxisInfo(
        procedure_name='Knee arthroscopy with meniscectomy',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0,
        special_considerations='Prophylaxis not routinely indicated for clean arthroscopy'
    ),
    
    # =========================================================================
    # NEUROSURGERY
    # =========================================================================
    '61510': SurgicalProphylaxisInfo(
        procedure_name='Craniectomy for tumor',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin (if MRSA risk)'],
        max_duration_hours=24,
        redosing_interval_hours=4
    ),
    '61312': SurgicalProphylaxisInfo(
        procedure_name='Craniectomy for hematoma',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '62223': SurgicalProphylaxisInfo(
        procedure_name='VP shunt creation',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'vancomycin'],
        max_duration_hours=24,
        special_considerations='Some centers use vancomycin routinely due to CoNS risk'
    ),
    '63030': SurgicalProphylaxisInfo(
        procedure_name='Laminotomy with discectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '63045': SurgicalProphylaxisInfo(
        procedure_name='Laminectomy with facetectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    
    # =========================================================================
    # VASCULAR SURGERY
    # =========================================================================
    '35301': SurgicalProphylaxisInfo(
        procedure_name='Carotid endarterectomy',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '35656': SurgicalProphylaxisInfo(
        procedure_name='Femoral-popliteal bypass',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '36558': SurgicalProphylaxisInfo(
        procedure_name='Central venous catheter insertion',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0,
        special_considerations='Prophylaxis not indicated for line placement alone'
    ),
    '36561': SurgicalProphylaxisInfo(
        procedure_name='Port-a-cath insertion',
        prophylaxis_indicated=False,
        recommended_agents=['cefazolin'],
        max_duration_hours=0,
        special_considerations='Consider single dose in immunocompromised'
    ),
    
    # =========================================================================
    # HEAD AND NECK
    # =========================================================================
    '21310': SurgicalProphylaxisInfo(
        procedure_name='Closed treatment nasal bone fracture',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0
    ),
    '30520': SurgicalProphylaxisInfo(
        procedure_name='Septoplasty',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0,
        special_considerations='Prophylaxis generally not indicated for clean nasal surgery'
    ),
    '42820': SurgicalProphylaxisInfo(
        procedure_name='Tonsillectomy with adenoidectomy',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0,
        special_considerations='Antibiotics do not reduce infection rates'
    ),
    '42821': SurgicalProphylaxisInfo(
        procedure_name='Tonsillectomy with adenoidectomy, age <12',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0
    ),
    '69436': SurgicalProphylaxisInfo(
        procedure_name='Tympanostomy with tube insertion',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0
    ),
    '31622': SurgicalProphylaxisInfo(
        procedure_name='Bronchoscopy with biopsy',
        prophylaxis_indicated=False,
        recommended_agents=[],
        max_duration_hours=0
    ),
    
    # =========================================================================
    # PLASTIC/RECONSTRUCTIVE
    # =========================================================================
    '15734': SurgicalProphylaxisInfo(
        procedure_name='Muscle flap',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '15756': SurgicalProphylaxisInfo(
        procedure_name='Free muscle flap with microvascular anastomosis',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    
    # =========================================================================
    # NEONATAL-SPECIFIC PROCEDURES
    # =========================================================================
    '43830': SurgicalProphylaxisInfo(
        procedure_name='Gastrostomy tube placement',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '44127': SurgicalProphylaxisInfo(
        procedure_name='Enterectomy for NEC/congenital anomaly',
        prophylaxis_indicated=False,  # TREATMENT indication if NEC
        recommended_agents=['ampicillin + gentamicin + metronidazole'],
        max_duration_hours=0,
        special_considerations='If for NEC, this is TREATMENT not prophylaxis'
    ),
    '49491': SurgicalProphylaxisInfo(
        procedure_name='Inguinal hernia repair, preterm infant',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24,
        special_considerations='Single dose typically sufficient'
    ),
    '49500': SurgicalProphylaxisInfo(
        procedure_name='Inguinal hernia repair, infant <6mo',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin'],
        max_duration_hours=24
    ),
    '43313': SurgicalProphylaxisInfo(
        procedure_name='Esophagoplasty for tracheoesophageal fistula',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin', 'ampicillin-sulbactam'],
        max_duration_hours=24
    ),
    '44126': SurgicalProphylaxisInfo(
        procedure_name='Enterectomy for atresia',
        prophylaxis_indicated=True,
        recommended_agents=['cefazolin + metronidazole', 'ampicillin-sulbactam'],
        max_duration_hours=24
    ),
}


# =============================================================================
# MEDICAL PROPHYLAXIS INDICATIONS
# =============================================================================

@dataclass
class MedicalProphylaxisInfo:
    """Information about medical (non-surgical) prophylaxis indications"""
    indication_name: str
    recommended_agents: List[str]
    duration: str
    icd10_codes: List[str]
    special_considerations: Optional[str] = None


MEDICAL_PROPHYLAXIS: Dict[str, MedicalProphylaxisInfo] = {
    'rheumatic_fever_secondary': MedicalProphylaxisInfo(
        indication_name='Secondary prophylaxis for rheumatic fever',
        recommended_agents=['penicillin V', 'penicillin G benzathine'],
        duration='Until age 21 or 10 years post-episode (whichever longer)',
        icd10_codes=['I00', 'I01', 'I02', 'I05', 'I06', 'I07', 'I08', 'I09'],
        special_considerations='Duration depends on cardiac involvement'
    ),
    'sbp_prophylaxis': MedicalProphylaxisInfo(
        indication_name='SBP prophylaxis in cirrhosis',
        recommended_agents=['TMP-SMX', 'norfloxacin', 'ciprofloxacin'],
        duration='Ongoing while indication persists',
        icd10_codes=['K70.31', 'K74.60', 'K74.69'],
        special_considerations='For patients with ascites and prior SBP or GI bleed'
    ),
    'uti_prophylaxis': MedicalProphylaxisInfo(
        indication_name='UTI prophylaxis (vesicoureteral reflux)',
        recommended_agents=['TMP-SMX', 'nitrofurantoin'],
        duration='Per urology guidance',
        icd10_codes=['N13.70', 'N13.71', 'N13.72', 'N13.73'],
        special_considerations='Controversial; shared decision making recommended'
    ),
    'bite_wound_prophylaxis': MedicalProphylaxisInfo(
        indication_name='Bite wound prophylaxis',
        recommended_agents=['amoxicillin-clavulanate'],
        duration='3-5 days',
        icd10_codes=['W53', 'W54', 'W55', 'W56', 'W57'],
        special_considerations='For high-risk bites: cat, hand, face, immunocompromised'
    ),
    'asplenia_prophylaxis': MedicalProphylaxisInfo(
        indication_name='Prophylaxis for asplenia',
        recommended_agents=['penicillin V', 'amoxicillin'],
        duration='At least until age 5; may continue lifelong',
        icd10_codes=['D73.0', 'Q89.01', 'Z90.81'],
        special_considerations='Critical in first 2 years post-splenectomy'
    ),
    'sickle_cell_prophylaxis': MedicalProphylaxisInfo(
        indication_name='Penicillin prophylaxis for sickle cell',
        recommended_agents=['penicillin V'],
        duration='Until at least age 5',
        icd10_codes=['D57.0', 'D57.1', 'D57.2'],
        special_considerations='Continue beyond age 5 if history of invasive pneumococcal disease'
    ),
    'endocarditis_prophylaxis': MedicalProphylaxisInfo(
        indication_name='Endocarditis prophylaxis',
        recommended_agents=['amoxicillin', 'ampicillin', 'cefazolin', 'clindamycin'],
        duration='Single dose pre-procedure',
        icd10_codes=['Q20', 'Q21', 'Q22', 'Q23', 'I34', 'I35', 'I36', 'I37', 'Z95.2', 'Z95.3', 'Z95.4'],
        special_considerations='Only for high-risk cardiac conditions + high-risk procedures'
    ),
}


# =============================================================================
# ANTIFUNGAL INDICATION CODES (Separate tracking from antibacterials)
# =============================================================================

ANTIFUNGAL_INDICATION_CODES: Dict[str, str] = {
    # Candidiasis
    'B37.0': 'Candidal stomatitis',
    'B37.1': 'Pulmonary candidiasis',
    'B37.2': 'Candidiasis of skin and nail',
    'B37.3': 'Candidiasis of vulva and vagina',
    'B37.4': 'Candidiasis of other urogenital sites',
    'B37.5': 'Candidal meningitis',
    'B37.6': 'Candidal endocarditis',
    'B37.7': 'Candidal sepsis',
    'B37.8': 'Candidiasis of other sites',
    'B37.81': 'Candidal esophagitis',
    'B37.82': 'Candidal enteritis',
    'B37.83': 'Candidal cheilitis',
    'B37.84': 'Candidal otitis externa',
    'B37.89': 'Other sites of candidiasis',
    'B37.9': 'Candidiasis, unspecified',
    
    # Aspergillosis
    'B44.0': 'Invasive pulmonary aspergillosis',
    'B44.1': 'Other pulmonary aspergillosis',
    'B44.2': 'Tonsillar aspergillosis',
    'B44.7': 'Disseminated aspergillosis',
    'B44.8': 'Other forms of aspergillosis',
    'B44.81': 'Allergic bronchopulmonary aspergillosis',
    'B44.89': 'Other forms of aspergillosis',
    'B44.9': 'Aspergillosis, unspecified',
    
    # Other systemic mycoses
    'B45.0': 'Pulmonary cryptococcosis',
    'B45.1': 'Cerebral cryptococcosis',
    'B45.2': 'Cutaneous cryptococcosis',
    'B45.3': 'Osseous cryptococcosis',
    'B45.7': 'Disseminated cryptococcosis',
    'B46.0': 'Pulmonary mucormycosis',
    'B46.1': 'Rhinocerebral mucormycosis',
    'B46.2': 'Gastrointestinal mucormycosis',
    'B46.3': 'Cutaneous mucormycosis',
    'B46.4': 'Disseminated mucormycosis',
    'B46.5': 'Mucormycosis, unspecified',
    
    # Endemic mycoses
    'B39.0': 'Acute pulmonary histoplasmosis capsulati',
    'B39.1': 'Chronic pulmonary histoplasmosis capsulati',
    'B39.2': 'Pulmonary histoplasmosis capsulati, unspecified',
    'B39.3': 'Disseminated histoplasmosis capsulati',
    'B38.0': 'Acute pulmonary coccidioidomycosis',
    'B38.1': 'Chronic pulmonary coccidioidomycosis',
    'B38.2': 'Pulmonary coccidioidomycosis, unspecified',
    'B38.3': 'Cutaneous coccidioidomycosis',
    'B38.4': 'Coccidioidomycosis meningitis',
    'B38.7': 'Disseminated coccidioidomycosis',
    'B40.0': 'Acute pulmonary blastomycosis',
    'B40.1': 'Chronic pulmonary blastomycosis',
    'B40.2': 'Pulmonary blastomycosis, unspecified',
    'B40.3': 'Cutaneous blastomycosis',
    'B40.7': 'Disseminated blastomycosis',
    
    # Pneumocystis
    'B59': 'Pneumocystosis',
}


# =============================================================================
# MAIN CLASSIFIER CLASS
# =============================================================================

class AntibioticIndicationClassifier:
    """
    Classifier for antibiotic indication appropriateness based on ICD-10 and CPT codes.
    
    Incorporates:
    - Base Chua et al. classification
    - Pediatric inpatient modifications
    - Febrile neutropenia logic
    - Surgical prophylaxis validation
    - Medical prophylaxis identification
    - Antifungal indication flagging
    """
    
    def __init__(self, chua_csv_path: str):
        """
        Initialize classifier with Chua et al. ICD-10 classification file.
        
        Args:
            chua_csv_path: Path to the Chua et al. CSV file (chuk046645_ww2.csv)
        """
        self.base_classification: Dict[str, Tuple[str, str]] = {}
        self._load_chua_classification(chua_csv_path)
        self._apply_pediatric_overrides()
    
    def _load_chua_classification(self, csv_path: str) -> None:
        """Load base classification from Chua CSV file."""
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row['ICD10_CODE'].strip()
                category = row['CATEGORY'].strip()
                description = row['FULL_DESCRIPTION'].strip()
                self.base_classification[code] = (category, description)
        
        print(f"Loaded {len(self.base_classification):,} ICD-10 codes from Chua classification")
    
    def _apply_pediatric_overrides(self) -> None:
        """Apply pediatric inpatient modifications to base classification."""
        override_count = 0
        for code, (new_cat, rationale) in PEDIATRIC_INPATIENT_OVERRIDES.items():
            if code in self.base_classification:
                old_cat, description = self.base_classification[code]
                if old_cat != new_cat:
                    self.base_classification[code] = (new_cat, description)
                    override_count += 1
            else:
                # Code not in base, add it
                self.base_classification[code] = (new_cat, rationale)
                override_count += 1
        
        print(f"Applied {override_count} pediatric inpatient overrides")
    
    def _get_code_category(self, code: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Get category and description for an ICD-10 code.
        Tries exact match first, then parent codes.
        """
        # Try exact match
        if code in self.base_classification:
            return self.base_classification[code]
        
        # Try progressively shorter codes (parent codes)
        for length in range(len(code) - 1, 2, -1):
            parent = code[:length]
            if parent in self.base_classification:
                return self.base_classification[parent]
        
        return (None, None)
    
    def _check_febrile_neutropenia(self, icd10_codes: List[str], fever_present: bool = False) -> bool:
        """Check if patient has febrile neutropenia."""
        has_neutropenia = any(
            code in NEUTROPENIA_CODES or 
            any(code.startswith(nc) for nc in NEUTROPENIA_CODES)
            for code in icd10_codes
        )
        
        has_fever = fever_present or any(
            code in FEVER_CODES or 
            any(code.startswith(fc) for fc in FEVER_CODES)
            for code in icd10_codes
        )
        
        return has_neutropenia and has_fever
    
    def _check_immunocompromised(self, icd10_codes: List[str]) -> bool:
        """Check if patient has immunocompromised state codes."""
        return any(
            code in IMMUNOCOMPROMISED_CODES or
            any(code.startswith(ic) for ic in IMMUNOCOMPROMISED_CODES)
            for code in icd10_codes
        )
    
    def _check_surgical_prophylaxis(self, cpt_codes: List[str]) -> List[SurgicalProphylaxisInfo]:
        """Get surgical prophylaxis info for CPT codes."""
        prophylaxis_info = []
        for code in cpt_codes:
            if code in SURGICAL_PROPHYLAXIS_CPT:
                info = SURGICAL_PROPHYLAXIS_CPT[code]
                if info.prophylaxis_indicated:
                    prophylaxis_info.append(info)
        return prophylaxis_info
    
    def _check_medical_prophylaxis(self, icd10_codes: List[str]) -> List[MedicalProphylaxisInfo]:
        """Check for medical prophylaxis indications."""
        prophylaxis_info = []
        for name, info in MEDICAL_PROPHYLAXIS.items():
            for code in icd10_codes:
                if any(code.startswith(pc) for pc in info.icd10_codes):
                    prophylaxis_info.append(info)
                    break
        return prophylaxis_info
    
    def _check_antifungal_indication(self, icd10_codes: List[str]) -> List[Tuple[str, str]]:
        """Check for antifungal (not antibacterial) indications."""
        antifungal_codes = []
        for code in icd10_codes:
            if code in ANTIFUNGAL_INDICATION_CODES:
                antifungal_codes.append((code, ANTIFUNGAL_INDICATION_CODES[code]))
            else:
                # Check parent codes
                for af_code, description in ANTIFUNGAL_INDICATION_CODES.items():
                    if code.startswith(af_code):
                        antifungal_codes.append((code, description))
                        break
        return antifungal_codes
    
    def classify(
        self,
        icd10_codes: List[str],
        cpt_codes: Optional[List[str]] = None,
        fever_present: bool = False,
        antibiotic_class: Optional[str] = None
    ) -> ClassificationResult:
        """
        Classify antibiotic indication appropriateness.
        
        Args:
            icd10_codes: List of ICD-10 diagnosis codes
            cpt_codes: Optional list of CPT procedure codes
            fever_present: Whether patient has documented fever
            antibiotic_class: Optional antibiotic class for specific guidance
            
        Returns:
            ClassificationResult with overall category and details
        """
        cpt_codes = cpt_codes or []
        
        # Initialize result
        result = ClassificationResult(
            overall_category=IndicationCategory.NEVER,
            all_indications=[]
        )
        
        # Check all ICD-10 codes
        categories_found = {'A': [], 'S': [], 'N': [], 'U': []}
        
        for code in icd10_codes:
            cat, description = self._get_code_category(code)
            if cat:
                categories_found[cat].append({
                    'code': code,
                    'description': description,
                    'category': cat
                })
            else:
                categories_found['U'].append({
                    'code': code,
                    'description': 'Unknown code',
                    'category': 'U'
                })
        
        # Flatten all indications
        for cat in ['A', 'S', 'N', 'U']:
            result.all_indications.extend(categories_found[cat])
        
        # Check for febrile neutropenia (upgrades to Always)
        if self._check_febrile_neutropenia(icd10_codes, fever_present):
            result.overall_category = IndicationCategory.FEBRILE_NEUTROPENIA
            result.primary_indication = "Febrile neutropenia"
            result.flags.append("FEBRILE_NEUTROPENIA: Empiric broad-spectrum antibiotics indicated")
            result.recommendations.append(
                "Febrile neutropenia protocol: Obtain cultures, start empiric therapy immediately"
            )
            return result
        
        # Check for surgical prophylaxis
        surgical_prophylaxis = self._check_surgical_prophylaxis(cpt_codes)
        if surgical_prophylaxis:
            result.overall_category = IndicationCategory.PROPHYLAXIS
            result.primary_indication = f"Surgical prophylaxis: {surgical_prophylaxis[0].procedure_name}"
            result.primary_code = cpt_codes[0] if cpt_codes else None
            result.flags.append("SURGICAL_PROPHYLAXIS")
            for sp in surgical_prophylaxis:
                result.recommendations.append(
                    f"{sp.procedure_name}: {', '.join(sp.recommended_agents)} "
                    f"(max {sp.max_duration_hours}h)"
                )
                if sp.special_considerations:
                    result.recommendations.append(f"  Note: {sp.special_considerations}")
            return result
        
        # Check for medical prophylaxis
        medical_prophylaxis = self._check_medical_prophylaxis(icd10_codes)
        if medical_prophylaxis:
            result.flags.append("MEDICAL_PROPHYLAXIS_POSSIBLE")
            for mp in medical_prophylaxis:
                result.recommendations.append(
                    f"Consider {mp.indication_name}: {', '.join(mp.recommended_agents)}"
                )
        
        # Check for antifungal indications
        antifungal = self._check_antifungal_indication(icd10_codes)
        if antifungal:
            result.flags.append("ANTIFUNGAL_INDICATION")
            for code, desc in antifungal:
                result.recommendations.append(
                    f"Antifungal (not antibacterial) indication: {desc} ({code})"
                )
        
        # Determine overall category based on diagnosis codes
        # Priority: A > S > N > U
        if categories_found['A']:
            result.overall_category = IndicationCategory.ALWAYS
            result.primary_indication = categories_found['A'][0]['description']
            result.primary_code = categories_found['A'][0]['code']
        elif categories_found['S']:
            result.overall_category = IndicationCategory.SOMETIMES
            result.primary_indication = categories_found['S'][0]['description']
            result.primary_code = categories_found['S'][0]['code']
            result.flags.append("REVIEW_RECOMMENDED")
            result.recommendations.append(
                "Clinical judgment needed - review appropriateness with prescriber"
            )
        elif categories_found['N']:
            result.overall_category = IndicationCategory.NEVER
            if categories_found['N']:
                result.primary_indication = categories_found['N'][0]['description']
                result.primary_code = categories_found['N'][0]['code']
            result.flags.append("NO_DOCUMENTED_INDICATION")
            result.recommendations.append(
                "No documented indication for antibiotics - consider discontinuation"
            )
        else:
            result.overall_category = IndicationCategory.UNKNOWN
            result.flags.append("CODES_NOT_FOUND")
            result.recommendations.append(
                "Diagnosis codes not found in classification - manual review required"
            )
        
        # Additional flags
        if self._check_immunocompromised(icd10_codes):
            result.flags.append("IMMUNOCOMPROMISED")
            result.recommendations.append(
                "Patient is immunocompromised - lower threshold for antibiotic therapy"
            )
        
        return result
    
    def get_surgical_prophylaxis_info(self, cpt_code: str) -> Optional[SurgicalProphylaxisInfo]:
        """Get detailed surgical prophylaxis info for a specific CPT code."""
        return SURGICAL_PROPHYLAXIS_CPT.get(cpt_code)
    
    def get_category_counts(self) -> Dict[str, int]:
        """Get counts of codes in each category."""
        counts = {'A': 0, 'S': 0, 'N': 0}
        for code, (cat, desc) in self.base_classification.items():
            if cat in counts:
                counts[cat] += 1
        return counts
    
    def search_codes(self, search_term: str, category: Optional[str] = None) -> List[Dict]:
        """
        Search for codes by description.
        
        Args:
            search_term: Text to search for in descriptions
            category: Optional category filter (A, S, or N)
            
        Returns:
            List of matching codes with their info
        """
        results = []
        pattern = re.compile(search_term, re.IGNORECASE)
        
        for code, (cat, description) in self.base_classification.items():
            if category and cat != category:
                continue
            if pattern.search(description):
                results.append({
                    'code': code,
                    'description': description,
                    'category': cat
                })
        
        return results
    
    def export_classification(self, output_path: str, include_modifications: bool = True) -> None:
        """
        Export the current classification to CSV.
        
        Args:
            output_path: Path for output CSV
            include_modifications: Whether to include a column showing modifications
        """
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            if include_modifications:
                writer.writerow(['ICD10_CODE', 'DESCRIPTION', 'CATEGORY', 'MODIFIED', 'MODIFICATION_REASON'])
            else:
                writer.writerow(['ICD10_CODE', 'DESCRIPTION', 'CATEGORY'])
            
            for code in sorted(self.base_classification.keys()):
                cat, description = self.base_classification[code]
                
                if include_modifications:
                    modified = code in PEDIATRIC_INPATIENT_OVERRIDES
                    reason = PEDIATRIC_INPATIENT_OVERRIDES.get(code, ('', ''))[1] if modified else ''
                    writer.writerow([code, description, cat, 'Y' if modified else 'N', reason])
                else:
                    writer.writerow([code, description, cat])
        
        print(f"Exported classification to {output_path}")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_classifier(chua_csv_path: str) -> AntibioticIndicationClassifier:
    """Convenience function to create a classifier instance."""
    return AntibioticIndicationClassifier(chua_csv_path)


def classify_encounter(
    classifier: AntibioticIndicationClassifier,
    icd10_codes: List[str],
    cpt_codes: Optional[List[str]] = None,
    fever_present: bool = False
) -> Dict:
    """
    Convenience function to classify an encounter and return dict result.
    
    Args:
        classifier: Initialized AntibioticIndicationClassifier
        icd10_codes: List of ICD-10 codes
        cpt_codes: Optional list of CPT codes
        fever_present: Whether fever is documented
        
    Returns:
        Dictionary with classification result
    """
    result = classifier.classify(icd10_codes, cpt_codes, fever_present)
    return result.to_dict()


# =============================================================================
# EXAMPLE USAGE AND TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    
    # Check for CSV path argument
    if len(sys.argv) < 2:
        print("Usage: python pediatric_abx_indications.py <path_to_chua_csv>")
        print("\nExample: python pediatric_abx_indications.py chuk046645_ww2.csv")
        sys.exit(1)
    
    csv_path = sys.argv[1]
    
    # Initialize classifier
    print("="*70)
    print("PEDIATRIC ANTIBIOTIC INDICATION CLASSIFIER")
    print("="*70)
    
    classifier = AntibioticIndicationClassifier(csv_path)
    
    # Show category counts
    counts = classifier.get_category_counts()
    print(f"\nCategory distribution:")
    print(f"  Always (A):    {counts['A']:,}")
    print(f"  Sometimes (S): {counts['S']:,}")
    print(f"  Never (N):     {counts['N']:,}")
    
    # Test cases
    print("\n" + "="*70)
    print("TEST CASES")
    print("="*70)
    
    test_cases = [
        {
            'name': 'Bacterial pneumonia',
            'icd10': ['J18.9'],
            'cpt': [],
            'fever': False
        },
        {
            'name': 'Viral URI',
            'icd10': ['J06.9'],
            'cpt': [],
            'fever': False
        },
        {
            'name': 'Febrile neutropenia',
            'icd10': ['D70.9', 'R50.9'],
            'cpt': [],
            'fever': True
        },
        {
            'name': 'Laparoscopic cholecystectomy',
            'icd10': ['K80.20'],  # Cholelithiasis
            'cpt': ['47562'],
            'fever': False
        },
        {
            'name': 'Bacteremia',
            'icd10': ['R78.81'],
            'cpt': [],
            'fever': True
        },
        {
            'name': 'Acute bronchiolitis (viral)',
            'icd10': ['J21.9'],
            'cpt': [],
            'fever': False
        },
        {
            'name': 'Neonatal sepsis',
            'icd10': ['P36.9'],
            'cpt': [],
            'fever': True
        },
        {
            'name': 'CLABSI',
            'icd10': ['T80.211A'],
            'cpt': [],
            'fever': True
        },
        {
            'name': 'Candidal sepsis (antifungal, not antibacterial)',
            'icd10': ['B37.7'],
            'cpt': [],
            'fever': True
        },
        {
            'name': 'VP shunt placement',
            'icd10': ['G91.1'],  # Obstructive hydrocephalus
            'cpt': ['62223'],
            'fever': False
        },
    ]
    
    for tc in test_cases:
        print(f"\n--- {tc['name']} ---")
        result = classifier.classify(
            icd10_codes=tc['icd10'],
            cpt_codes=tc['cpt'],
            fever_present=tc['fever']
        )
        print(f"ICD-10: {tc['icd10']}, CPT: {tc['cpt']}, Fever: {tc['fever']}")
        print(f"Result: {result.overall_category.value} - {result._category_description()}")
        if result.primary_indication:
            print(f"Primary: {result.primary_indication}")
        if result.flags:
            print(f"Flags: {', '.join(result.flags)}")
        if result.recommendations:
            for rec in result.recommendations[:2]:
                print(f"  → {rec}")
