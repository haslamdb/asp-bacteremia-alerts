"""
AEGIS Integration Example
=========================

Example showing how to integrate the Pediatric Antibiotic Indication Classifier
into AEGIS workflows for real-time antibiotic appropriateness assessment.

This can be adapted to work with:
- Epic FHIR API data
- Direct database queries
- HL7 message streams
"""

from pediatric_abx_indications import (
    AntibioticIndicationClassifier,
    ClassificationResult,
    IndicationCategory
)
from typing import List, Dict, Optional
from datetime import datetime
import json


class AEGISAntibioticMonitor:
    """
    Integration layer between AEGIS and the antibiotic indication classifier.
    """
    
    def __init__(self, chua_csv_path: str):
        """Initialize with path to Chua classification CSV."""
        self.classifier = AntibioticIndicationClassifier(chua_csv_path)
        
    def assess_antibiotic_order(
        self,
        patient_mrn: str,
        encounter_id: str,
        antibiotic_name: str,
        diagnosis_codes: List[str],
        procedure_codes: Optional[List[str]] = None,
        vital_signs: Optional[Dict] = None
    ) -> Dict:
        """
        Assess appropriateness of an antibiotic order.
        
        Args:
            patient_mrn: Patient medical record number
            encounter_id: Current encounter ID
            antibiotic_name: Name of ordered antibiotic
            diagnosis_codes: List of ICD-10 codes from encounter
            procedure_codes: Optional list of CPT codes
            vital_signs: Optional dict with 'temperature' key
            
        Returns:
            Assessment result dict for AEGIS dashboard
        """
        # Check for fever in vital signs
        fever_present = False
        if vital_signs and 'temperature' in vital_signs:
            # Fever defined as temp >= 38.0°C
            fever_present = vital_signs['temperature'] >= 38.0
        
        # Run classification
        result = self.classifier.classify(
            icd10_codes=diagnosis_codes,
            cpt_codes=procedure_codes or [],
            fever_present=fever_present
        )
        
        # Build AEGIS-formatted response
        assessment = {
            'timestamp': datetime.now().isoformat(),
            'patient_mrn': patient_mrn,
            'encounter_id': encounter_id,
            'antibiotic': antibiotic_name,
            'assessment': {
                'category': result.overall_category.value,
                'category_name': self._category_display_name(result.overall_category),
                'primary_indication': result.primary_indication,
                'primary_code': result.primary_code,
                'action_required': self._get_action(result.overall_category),
                'alert_level': self._get_alert_level(result.overall_category)
            },
            'details': {
                'all_diagnoses_assessed': len(result.all_indications),
                'flags': result.flags,
                'recommendations': result.recommendations
            },
            'raw_classification': result.to_dict()
        }
        
        return assessment
    
    def _category_display_name(self, category: IndicationCategory) -> str:
        """Human-readable category name for dashboard."""
        names = {
            IndicationCategory.ALWAYS: "Indicated",
            IndicationCategory.SOMETIMES: "Review Needed",
            IndicationCategory.NEVER: "Not Indicated",
            IndicationCategory.PROPHYLAXIS: "Prophylaxis",
            IndicationCategory.FEBRILE_NEUTROPENIA: "Febrile Neutropenia",
            IndicationCategory.UNKNOWN: "Unknown"
        }
        return names.get(category, "Unknown")
    
    def _get_action(self, category: IndicationCategory) -> str:
        """Recommended action for ASP team."""
        actions = {
            IndicationCategory.ALWAYS: "None - indication documented",
            IndicationCategory.SOMETIMES: "Prospective review recommended",
            IndicationCategory.NEVER: "Intervention - no documented indication",
            IndicationCategory.PROPHYLAXIS: "Verify duration within guidelines",
            IndicationCategory.FEBRILE_NEUTROPENIA: "Verify protocol compliance",
            IndicationCategory.UNKNOWN: "Manual review required"
        }
        return actions.get(category, "Manual review required")
    
    def _get_alert_level(self, category: IndicationCategory) -> str:
        """Alert level for dashboard color coding."""
        levels = {
            IndicationCategory.ALWAYS: "green",
            IndicationCategory.SOMETIMES: "yellow",
            IndicationCategory.NEVER: "red",
            IndicationCategory.PROPHYLAXIS: "blue",
            IndicationCategory.FEBRILE_NEUTROPENIA: "green",
            IndicationCategory.UNKNOWN: "yellow"
        }
        return levels.get(category, "yellow")
    
    def batch_assess_active_orders(
        self,
        orders: List[Dict]
    ) -> List[Dict]:
        """
        Batch assess multiple active antibiotic orders.
        
        Args:
            orders: List of order dicts with keys:
                - patient_mrn
                - encounter_id
                - antibiotic_name
                - diagnosis_codes
                - procedure_codes (optional)
                - vital_signs (optional)
                
        Returns:
            List of assessment results
        """
        results = []
        for order in orders:
            assessment = self.assess_antibiotic_order(
                patient_mrn=order['patient_mrn'],
                encounter_id=order['encounter_id'],
                antibiotic_name=order['antibiotic_name'],
                diagnosis_codes=order['diagnosis_codes'],
                procedure_codes=order.get('procedure_codes'),
                vital_signs=order.get('vital_signs')
            )
            results.append(assessment)
        
        return results
    
    def generate_daily_report(self, assessments: List[Dict]) -> Dict:
        """
        Generate summary report from assessments.
        
        Args:
            assessments: List of assessment results
            
        Returns:
            Summary report dict
        """
        total = len(assessments)
        if total == 0:
            return {'error': 'No assessments to summarize'}
        
        # Count by category
        category_counts = {}
        intervention_needed = []
        review_needed = []
        
        for a in assessments:
            cat = a['assessment']['category']
            category_counts[cat] = category_counts.get(cat, 0) + 1
            
            if a['assessment']['alert_level'] == 'red':
                intervention_needed.append(a)
            elif a['assessment']['alert_level'] == 'yellow':
                review_needed.append(a)
        
        return {
            'report_date': datetime.now().strftime('%Y-%m-%d'),
            'total_orders_assessed': total,
            'summary': {
                'indicated': category_counts.get('A', 0) + category_counts.get('FN', 0),
                'review_needed': category_counts.get('S', 0) + category_counts.get('U', 0),
                'not_indicated': category_counts.get('N', 0),
                'prophylaxis': category_counts.get('P', 0)
            },
            'appropriateness_rate': round(
                (category_counts.get('A', 0) + category_counts.get('FN', 0) + category_counts.get('P', 0)) 
                / total * 100, 1
            ) if total > 0 else 0,
            'intervention_needed_count': len(intervention_needed),
            'review_needed_count': len(review_needed),
            'detailed_category_counts': category_counts
        }


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == '__main__':
    # Initialize the monitor
    monitor = AEGISAntibioticMonitor('chuk046645_ww2.csv')
    
    # Example: Single order assessment
    print("="*70)
    print("SINGLE ORDER ASSESSMENT EXAMPLE")
    print("="*70)
    
    assessment = monitor.assess_antibiotic_order(
        patient_mrn='123456',
        encounter_id='ENC001',
        antibiotic_name='Ceftriaxone',
        diagnosis_codes=['J18.9', 'R50.9'],  # Pneumonia + Fever
        vital_signs={'temperature': 38.5}
    )
    
    print(json.dumps(assessment, indent=2, default=str))
    
    # Example: Batch assessment
    print("\n" + "="*70)
    print("BATCH ASSESSMENT EXAMPLE")
    print("="*70)
    
    sample_orders = [
        {
            'patient_mrn': '111111',
            'encounter_id': 'ENC101',
            'antibiotic_name': 'Amoxicillin',
            'diagnosis_codes': ['J06.9'],  # Viral URI
        },
        {
            'patient_mrn': '222222',
            'encounter_id': 'ENC102',
            'antibiotic_name': 'Ceftriaxone',
            'diagnosis_codes': ['N39.0'],  # UTI
        },
        {
            'patient_mrn': '333333',
            'encounter_id': 'ENC103',
            'antibiotic_name': 'Piperacillin-tazobactam',
            'diagnosis_codes': ['D70.9', 'R50.9'],  # Neutropenia + Fever
            'vital_signs': {'temperature': 39.0}
        },
        {
            'patient_mrn': '444444',
            'encounter_id': 'ENC104',
            'antibiotic_name': 'Cefazolin',
            'diagnosis_codes': ['K80.20'],  # Cholelithiasis
            'procedure_codes': ['47562']  # Lap chole
        }
    ]
    
    batch_results = monitor.batch_assess_active_orders(sample_orders)
    
    for result in batch_results:
        print(f"\nPatient {result['patient_mrn']} - {result['antibiotic']}:")
        print(f"  Category: {result['assessment']['category_name']} ({result['assessment']['alert_level']})")
        print(f"  Indication: {result['assessment']['primary_indication']}")
        print(f"  Action: {result['assessment']['action_required']}")
    
    # Generate daily report
    print("\n" + "="*70)
    print("DAILY REPORT EXAMPLE")
    print("="*70)
    
    report = monitor.generate_daily_report(batch_results)
    print(json.dumps(report, indent=2))
