# AEGIS Shared LLM/NLP Architecture

## Overview

Multiple AEGIS modules require parsing of clinical notes using LLM/NLP:

| Module | Notes Needed | Information Extracted |
|--------|--------------|----------------------|
| **Surgical Prophylaxis** | Operative notes, anesthesia records | Incision time, procedure details, blood loss |
| **Guideline Adherence** | Progress notes, consult notes | Reassessment documentation, risk stratification |
| **Febrile Infant** | ED notes, admission notes | HSV risk factors, clinical appearance |
| **Sepsis Bundle** | ED notes, nursing notes | Time of recognition, fluid documentation |
| **ASP Appropriateness** | Admission notes, ID consults | Infection source, culture interpretation |
| **HAI Surveillance** | Daily notes, procedure notes | Device presence, infection signs |

**Key Question**: Should each module call the LLM independently, or should we share a unified extraction layer?

---

## Architecture Options

### Option 1: Independent Module Calls (Simple but Inefficient)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     INDEPENDENT MODULE CALLS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Clinical Note                                                              │
│       │                                                                     │
│       ├──────────────────┬──────────────────┬──────────────────┐           │
│       ▼                  ▼                  ▼                  ▼           │
│  ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐     │
│  │Module 1 │        │Module 2 │        │Module 3 │        │Module 4 │     │
│  │ Prompt  │        │ Prompt  │        │ Prompt  │        │ Prompt  │     │
│  └────┬────┘        └────┬────┘        └────┬────┘        └────┬────┘     │
│       │                  │                  │                  │           │
│       ▼                  ▼                  ▼                  ▼           │
│  ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐     │
│  │   LLM   │        │   LLM   │        │   LLM   │        │   LLM   │     │
│  │  Call 1 │        │  Call 2 │        │  Call 3 │        │  Call 4 │     │
│  └─────────┘        └─────────┘        └─────────┘        └─────────┘     │
│                                                                             │
│  Pros: Simple, modules are independent                                     │
│  Cons: 4x cost, 4x latency (if sequential), potential inconsistency       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**When to use**: Prototyping, when modules have very different note types, when consistency isn't critical.

---

### Option 2: Parallel Independent Calls (Better Latency)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PARALLEL INDEPENDENT CALLS                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Clinical Note                                                              │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      ASYNC DISPATCHER                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ├──────────────────┬──────────────────┬──────────────────┐           │
│       ▼                  ▼                  ▼                  ▼           │
│  ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐     │
│  │   LLM   │        │   LLM   │        │   LLM   │        │   LLM   │     │
│  │  Call 1 │        │  Call 2 │        │  Call 3 │        │  Call 4 │     │
│  └────┬────┘        └────┬────┘        └────┬────┘        └────┬────┘     │
│       │                  │                  │                  │           │
│       └──────────────────┴──────────────────┴──────────────────┘           │
│                                   │                                         │
│                                   ▼                                         │
│                          ┌───────────────┐                                 │
│                          │   AGGREGATOR  │                                 │
│                          └───────────────┘                                 │
│                                                                             │
│  Pros: Low latency (parallel), modules still independent                   │
│  Cons: Still 4x cost, potential inconsistency between extractions         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**When to use**: When latency matters, modules truly need different parsing, cost is acceptable.

---

### Option 3: Unified Extraction Layer (Recommended) ⭐

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     UNIFIED EXTRACTION LAYER                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Clinical Note                                                              │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    UNIFIED EXTRACTION PROMPT                         │   │
│  │                                                                      │   │
│  │   "Extract ALL of the following from this clinical note:            │   │
│  │    - Procedure details (name, CPT, times)                           │   │
│  │    - Antibiotic information (drug, dose, timing)                    │   │
│  │    - Infection indicators (fever, WBC, cultures)                    │   │
│  │    - Risk factors (HSV, immunocompromised, devices)                 │   │
│  │    - Clinical assessments (appearance, vitals, labs)                │   │
│  │    - Documentation elements (reassessment, consults)                │   │
│  │    ..."                                                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         SINGLE LLM CALL                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    STRUCTURED EXTRACTION RESULT                      │   │
│  │                                                                      │   │
│  │   {                                                                  │   │
│  │     "procedure": { "name": "...", "cpt": "...", ... },              │   │
│  │     "antibiotics": [ { "drug": "...", "dose": "...", ... } ],       │   │
│  │     "infection_indicators": { "fever": true, "wbc": 15000, ... },   │   │
│  │     "risk_factors": { "hsv_risk": false, ... },                     │   │
│  │     "assessments": { "appearance": "well", ... },                   │   │
│  │     "documentation": { "reassessment_present": true, ... }          │   │
│  │   }                                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ├──────────────────┬──────────────────┬──────────────────┐           │
│       ▼                  ▼                  ▼                  ▼           │
│  ┌─────────┐        ┌─────────┐        ┌─────────┐        ┌─────────┐     │
│  │Module 1 │        │Module 2 │        │Module 3 │        │Module 4 │     │
│  │(uses    │        │(uses    │        │(uses    │        │(uses    │     │
│  │procedure│        │antibiot-│        │infection│        │document-│     │
│  │ data)   │        │ics data)│        │ data)   │        │ation)   │     │
│  └─────────┘        └─────────┘        └─────────┘        └─────────┘     │
│                                                                             │
│  Pros: 1x cost, consistent extraction, single source of truth             │
│  Cons: Larger prompt, more complex to maintain, single point of failure   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**When to use**: Production systems, when cost matters, when consistency is critical.

---

### Option 4: Hybrid (Shared Base + Module-Specific)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     HYBRID EXTRACTION ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Clinical Note                                                              │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              TIER 1: COMMON EXTRACTION (Always runs)                 │   │
│  │                                                                      │   │
│  │   Extract: dates/times, medications, vitals, labs, diagnoses        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    STRUCTURED BASE RESULT                            │   │
│  │   (Cached, shared across all modules)                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│       │                                                                     │
│       ├─────────────────────────────────────────────────────┐              │
│       │                                                     │              │
│       ▼                                                     ▼              │
│  ┌───────────────────────────────┐        ┌───────────────────────────┐   │
│  │ TIER 2: MODULE-SPECIFIC       │        │ TIER 2: MODULE-SPECIFIC   │   │
│  │ (Only if needed)              │        │ (Only if needed)          │   │
│  │                               │        │                           │   │
│  │ Surgical Prophylaxis:         │        │ HAI Surveillance:         │   │
│  │ - Blood loss estimation       │        │ - Device day counting     │   │
│  │ - Wound classification        │        │ - Infection criteria      │   │
│  └───────────────────────────────┘        └───────────────────────────┘   │
│                                                                             │
│  Pros: Balances efficiency with flexibility, caching reduces cost          │
│  Cons: More complex architecture                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Recommended Architecture: Unified Extraction Service

For AEGIS, I recommend **Option 3 (Unified Extraction)** with the following design:

### Core Components

```python
"""
AEGIS Clinical Note Extraction Service
======================================

Unified LLM-based extraction layer that serves all AEGIS modules.
Single call per note extracts all needed information.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, date, time
from enum import Enum
import json
import asyncio
from abc import ABC, abstractmethod


# =============================================================================
# EXTRACTION SCHEMA - What we extract from clinical notes
# =============================================================================

@dataclass
class ExtractedMedication:
    """Medication information extracted from notes."""
    drug_name: str
    dose: Optional[str] = None
    route: Optional[str] = None
    frequency: Optional[str] = None
    indication: Optional[str] = None
    start_time: Optional[datetime] = None
    administered: bool = False
    

@dataclass
class ExtractedProcedure:
    """Procedure information extracted from operative notes."""
    procedure_name: str
    cpt_code: Optional[str] = None
    surgeon: Optional[str] = None
    
    # Timing
    incision_time: Optional[datetime] = None
    closure_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    
    # Details
    wound_classification: Optional[str] = None  # Clean, Clean-contaminated, etc.
    estimated_blood_loss_ml: Optional[int] = None
    implant_placed: bool = False
    
    # Prophylaxis (from anesthesia/OR notes)
    prophylaxis_given: bool = False
    prophylaxis_drug: Optional[str] = None
    prophylaxis_time: Optional[datetime] = None


@dataclass
class ExtractedVitals:
    """Vital signs extracted from notes."""
    timestamp: Optional[datetime] = None
    temperature_c: Optional[float] = None
    heart_rate: Optional[int] = None
    respiratory_rate: Optional[int] = None
    blood_pressure_systolic: Optional[int] = None
    blood_pressure_diastolic: Optional[int] = None
    oxygen_saturation: Optional[float] = None
    weight_kg: Optional[float] = None


@dataclass
class ExtractedLabResult:
    """Lab result extracted from notes."""
    test_name: str
    value: Optional[str] = None
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    timestamp: Optional[datetime] = None
    abnormal: bool = False


@dataclass
class ExtractedCultureResult:
    """Microbiology culture result."""
    specimen_type: str  # blood, urine, CSF, wound, etc.
    collection_time: Optional[datetime] = None
    result_time: Optional[datetime] = None
    organism: Optional[str] = None
    no_growth: bool = False
    pending: bool = False
    susceptibilities: Dict[str, str] = field(default_factory=dict)


@dataclass
class ExtractedClinicalAssessment:
    """Clinical assessment/impression extracted from notes."""
    appearance: Optional[str] = None  # well-appearing, ill-appearing, toxic
    mental_status: Optional[str] = None
    hydration_status: Optional[str] = None
    pain_level: Optional[int] = None
    clinical_impression: Optional[str] = None


@dataclass
class ExtractedInfectionIndicators:
    """Infection-related findings."""
    fever_present: bool = False
    fever_max_temp_c: Optional[float] = None
    fever_onset_time: Optional[datetime] = None
    
    leukocytosis: bool = False
    leukopenia: bool = False
    wbc_count: Optional[float] = None
    
    bandemia: bool = False
    band_percentage: Optional[float] = None
    
    procalcitonin_elevated: bool = False
    procalcitonin_value: Optional[float] = None
    
    crp_elevated: bool = False
    crp_value: Optional[float] = None
    
    lactate_elevated: bool = False
    lactate_value: Optional[float] = None
    
    hypothermia: bool = False
    hypotension: bool = False
    tachycardia: bool = False
    tachypnea: bool = False


@dataclass
class ExtractedRiskFactors:
    """Clinical risk factors relevant to various modules."""
    # General
    immunocompromised: bool = False
    immunocompromise_reason: Optional[str] = None
    
    # Febrile infant specific
    hsv_risk_factors: bool = False
    hsv_risk_details: Optional[str] = None
    maternal_fever: bool = False
    vesicular_lesions: bool = False
    
    # HAI related
    central_line_present: bool = False
    central_line_type: Optional[str] = None
    central_line_days: Optional[int] = None
    urinary_catheter_present: bool = False
    urinary_catheter_days: Optional[int] = None
    ventilator_present: bool = False
    ventilator_days: Optional[int] = None
    
    # Surgical
    prior_mrsa_colonization: bool = False
    diabetes: bool = False
    obesity: bool = False
    smoking: bool = False


@dataclass
class ExtractedDocumentation:
    """Documentation elements for guideline adherence."""
    # Reassessment
    reassessment_documented: bool = False
    reassessment_time: Optional[datetime] = None
    reassessment_by: Optional[str] = None
    
    # Consults
    id_consult_requested: bool = False
    id_consult_time: Optional[datetime] = None
    id_recommendations: Optional[str] = None
    
    # Risk stratification
    risk_stratification_documented: bool = False
    risk_level: Optional[str] = None
    
    # Goals of care
    antibiotic_duration_planned: Optional[int] = None
    deescalation_plan: Optional[str] = None
    
    # Source control
    source_control_documented: bool = False
    source_control_details: Optional[str] = None


@dataclass 
class ExtractedDiagnoses:
    """Diagnoses mentioned in notes."""
    primary_diagnosis: Optional[str] = None
    diagnoses: List[str] = field(default_factory=list)
    icd10_codes: List[str] = field(default_factory=list)
    infection_diagnoses: List[str] = field(default_factory=list)


@dataclass
class ClinicalNoteExtraction:
    """
    Complete extraction result from a clinical note.
    
    This is the unified data structure that all modules consume.
    """
    # Metadata
    note_id: str
    note_type: str  # progress_note, operative_note, ed_note, consult, etc.
    note_datetime: datetime
    author: Optional[str] = None
    encounter_id: Optional[str] = None
    patient_mrn: Optional[str] = None
    
    # Extraction timestamp
    extracted_at: datetime = field(default_factory=datetime.now)
    extraction_model: str = ""
    extraction_confidence: float = 0.0
    
    # Extracted data
    medications: List[ExtractedMedication] = field(default_factory=list)
    procedures: List[ExtractedProcedure] = field(default_factory=list)
    vitals: List[ExtractedVitals] = field(default_factory=list)
    lab_results: List[ExtractedLabResult] = field(default_factory=list)
    culture_results: List[ExtractedCultureResult] = field(default_factory=list)
    clinical_assessment: Optional[ExtractedClinicalAssessment] = None
    infection_indicators: Optional[ExtractedInfectionIndicators] = None
    risk_factors: Optional[ExtractedRiskFactors] = None
    documentation: Optional[ExtractedDocumentation] = None
    diagnoses: Optional[ExtractedDiagnoses] = None
    
    # Raw extraction for debugging
    raw_extraction: Optional[Dict] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        # Implementation would recursively convert dataclasses
        pass


# =============================================================================
# EXTRACTION SERVICE
# =============================================================================

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def complete(self, prompt: str, system_prompt: str) -> str:
        """Send prompt to LLM and get response."""
        pass


class ClaudeProvider(LLMProvider):
    """Claude API provider."""
    
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
    
    async def complete(self, prompt: str, system_prompt: str) -> str:
        """Send prompt to Claude API."""
        import anthropic
        
        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        
        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text


class LocalLLMProvider(LLMProvider):
    """Local LLM provider (e.g., for on-premise deployment)."""
    
    def __init__(self, endpoint: str, model: str):
        self.endpoint = endpoint
        self.model = model
    
    async def complete(self, prompt: str, system_prompt: str) -> str:
        """Send prompt to local LLM endpoint."""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.endpoint,
                json={
                    "model": self.model,
                    "prompt": f"{system_prompt}\n\n{prompt}",
                    "max_tokens": 4096
                }
            ) as response:
                result = await response.json()
                return result["text"]


class ClinicalNoteExtractionService:
    """
    Unified extraction service for clinical notes.
    
    All AEGIS modules use this service to extract structured data
    from clinical notes. Single LLM call per note.
    """
    
    SYSTEM_PROMPT = """You are a clinical data extraction system for a pediatric hospital. 
Your task is to extract structured information from clinical notes.

IMPORTANT:
- Extract ONLY information explicitly stated in the note
- Do not infer or assume information not present
- Use null/empty values when information is not available
- Be precise with dates, times, and numeric values
- Preserve clinical terminology

You will return a JSON object with the extracted information.
"""
    
    EXTRACTION_PROMPT_TEMPLATE = """Extract structured clinical information from the following note.

Note Type: {note_type}
Note Date: {note_date}

=== CLINICAL NOTE ===
{note_text}
=== END NOTE ===

Extract the following information and return as JSON:

{{
    "medications": [
        {{
            "drug_name": "string",
            "dose": "string or null",
            "route": "string or null (IV, PO, IM, etc.)",
            "frequency": "string or null",
            "indication": "string or null",
            "start_time": "ISO datetime or null",
            "administered": boolean
        }}
    ],
    "procedures": [
        {{
            "procedure_name": "string",
            "cpt_code": "string or null",
            "surgeon": "string or null",
            "incision_time": "ISO datetime or null",
            "closure_time": "ISO datetime or null",
            "duration_minutes": integer or null,
            "wound_classification": "Clean|Clean-contaminated|Contaminated|Dirty or null",
            "estimated_blood_loss_ml": integer or null,
            "implant_placed": boolean,
            "prophylaxis_given": boolean,
            "prophylaxis_drug": "string or null",
            "prophylaxis_time": "ISO datetime or null"
        }}
    ],
    "vitals": [
        {{
            "timestamp": "ISO datetime or null",
            "temperature_c": number or null,
            "heart_rate": integer or null,
            "respiratory_rate": integer or null,
            "blood_pressure_systolic": integer or null,
            "blood_pressure_diastolic": integer or null,
            "oxygen_saturation": number or null,
            "weight_kg": number or null
        }}
    ],
    "lab_results": [
        {{
            "test_name": "string",
            "value": "string or null",
            "numeric_value": number or null,
            "unit": "string or null",
            "timestamp": "ISO datetime or null",
            "abnormal": boolean
        }}
    ],
    "culture_results": [
        {{
            "specimen_type": "blood|urine|CSF|wound|respiratory|other",
            "collection_time": "ISO datetime or null",
            "result_time": "ISO datetime or null",
            "organism": "string or null",
            "no_growth": boolean,
            "pending": boolean,
            "susceptibilities": {{"antibiotic": "S|I|R"}}
        }}
    ],
    "clinical_assessment": {{
        "appearance": "well-appearing|ill-appearing|toxic|null",
        "mental_status": "string or null",
        "hydration_status": "string or null",
        "pain_level": integer 0-10 or null,
        "clinical_impression": "string or null"
    }},
    "infection_indicators": {{
        "fever_present": boolean,
        "fever_max_temp_c": number or null,
        "fever_onset_time": "ISO datetime or null",
        "leukocytosis": boolean,
        "leukopenia": boolean,
        "wbc_count": number or null,
        "bandemia": boolean,
        "band_percentage": number or null,
        "procalcitonin_elevated": boolean,
        "procalcitonin_value": number or null,
        "crp_elevated": boolean,
        "crp_value": number or null,
        "lactate_elevated": boolean,
        "lactate_value": number or null,
        "hypothermia": boolean,
        "hypotension": boolean,
        "tachycardia": boolean,
        "tachypnea": boolean
    }},
    "risk_factors": {{
        "immunocompromised": boolean,
        "immunocompromise_reason": "string or null",
        "hsv_risk_factors": boolean,
        "hsv_risk_details": "string or null",
        "maternal_fever": boolean,
        "vesicular_lesions": boolean,
        "central_line_present": boolean,
        "central_line_type": "string or null",
        "central_line_days": integer or null,
        "urinary_catheter_present": boolean,
        "urinary_catheter_days": integer or null,
        "ventilator_present": boolean,
        "ventilator_days": integer or null,
        "prior_mrsa_colonization": boolean,
        "diabetes": boolean,
        "obesity": boolean,
        "smoking": boolean
    }},
    "documentation": {{
        "reassessment_documented": boolean,
        "reassessment_time": "ISO datetime or null",
        "reassessment_by": "string or null",
        "id_consult_requested": boolean,
        "id_consult_time": "ISO datetime or null",
        "id_recommendations": "string or null",
        "risk_stratification_documented": boolean,
        "risk_level": "high|moderate|low|null",
        "antibiotic_duration_planned": integer days or null,
        "deescalation_plan": "string or null",
        "source_control_documented": boolean,
        "source_control_details": "string or null"
    }},
    "diagnoses": {{
        "primary_diagnosis": "string or null",
        "diagnoses": ["list of diagnoses mentioned"],
        "icd10_codes": ["list of ICD-10 codes if mentioned"],
        "infection_diagnoses": ["list of infection-related diagnoses"]
    }}
}}

Return ONLY the JSON object, no other text."""
    
    def __init__(self, llm_provider: LLMProvider):
        """
        Initialize extraction service.
        
        Args:
            llm_provider: LLM provider to use for extraction
        """
        self.llm = llm_provider
        self._cache: Dict[str, ClinicalNoteExtraction] = {}
    
    async def extract(
        self,
        note_text: str,
        note_type: str,
        note_datetime: datetime,
        note_id: str,
        encounter_id: Optional[str] = None,
        patient_mrn: Optional[str] = None,
        use_cache: bool = True
    ) -> ClinicalNoteExtraction:
        """
        Extract structured data from a clinical note.
        
        Args:
            note_text: The raw clinical note text
            note_type: Type of note (progress_note, operative_note, etc.)
            note_datetime: When the note was written
            note_id: Unique identifier for the note
            encounter_id: Associated encounter ID
            patient_mrn: Patient MRN
            use_cache: Whether to use cached extractions
            
        Returns:
            ClinicalNoteExtraction with all extracted data
        """
        # Check cache
        if use_cache and note_id in self._cache:
            return self._cache[note_id]
        
        # Build prompt
        prompt = self.EXTRACTION_PROMPT_TEMPLATE.format(
            note_type=note_type,
            note_date=note_datetime.isoformat(),
            note_text=note_text
        )
        
        # Call LLM
        response = await self.llm.complete(prompt, self.SYSTEM_PROMPT)
        
        # Parse JSON response
        try:
            extracted_data = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                extracted_data = json.loads(json_match.group())
            else:
                raise ValueError(f"Could not parse LLM response as JSON: {response[:500]}")
        
        # Convert to dataclass structure
        extraction = self._parse_extraction(
            extracted_data,
            note_id=note_id,
            note_type=note_type,
            note_datetime=note_datetime,
            encounter_id=encounter_id,
            patient_mrn=patient_mrn
        )
        
        # Cache result
        if use_cache:
            self._cache[note_id] = extraction
        
        return extraction
    
    async def extract_batch(
        self,
        notes: List[Dict],
        max_concurrent: int = 5
    ) -> List[ClinicalNoteExtraction]:
        """
        Extract from multiple notes in parallel.
        
        Args:
            notes: List of dicts with note_text, note_type, note_datetime, note_id
            max_concurrent: Maximum concurrent LLM calls
            
        Returns:
            List of ClinicalNoteExtraction results
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def extract_with_semaphore(note: Dict) -> ClinicalNoteExtraction:
            async with semaphore:
                return await self.extract(**note)
        
        tasks = [extract_with_semaphore(note) for note in notes]
        return await asyncio.gather(*tasks)
    
    def _parse_extraction(
        self,
        data: Dict,
        note_id: str,
        note_type: str,
        note_datetime: datetime,
        encounter_id: Optional[str],
        patient_mrn: Optional[str]
    ) -> ClinicalNoteExtraction:
        """Parse raw JSON extraction into dataclass structure."""
        
        # Parse medications
        medications = []
        for med in data.get('medications', []):
            medications.append(ExtractedMedication(
                drug_name=med.get('drug_name', ''),
                dose=med.get('dose'),
                route=med.get('route'),
                frequency=med.get('frequency'),
                indication=med.get('indication'),
                start_time=self._parse_datetime(med.get('start_time')),
                administered=med.get('administered', False)
            ))
        
        # Parse procedures
        procedures = []
        for proc in data.get('procedures', []):
            procedures.append(ExtractedProcedure(
                procedure_name=proc.get('procedure_name', ''),
                cpt_code=proc.get('cpt_code'),
                surgeon=proc.get('surgeon'),
                incision_time=self._parse_datetime(proc.get('incision_time')),
                closure_time=self._parse_datetime(proc.get('closure_time')),
                duration_minutes=proc.get('duration_minutes'),
                wound_classification=proc.get('wound_classification'),
                estimated_blood_loss_ml=proc.get('estimated_blood_loss_ml'),
                implant_placed=proc.get('implant_placed', False),
                prophylaxis_given=proc.get('prophylaxis_given', False),
                prophylaxis_drug=proc.get('prophylaxis_drug'),
                prophylaxis_time=self._parse_datetime(proc.get('prophylaxis_time'))
            ))
        
        # Parse other sections similarly...
        # (abbreviated for length)
        
        return ClinicalNoteExtraction(
            note_id=note_id,
            note_type=note_type,
            note_datetime=note_datetime,
            encounter_id=encounter_id,
            patient_mrn=patient_mrn,
            medications=medications,
            procedures=procedures,
            # ... other fields
            raw_extraction=data
        )
    
    def _parse_datetime(self, value: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None


# =============================================================================
# MODULE INTERFACE - How modules consume extractions
# =============================================================================

class ExtractionConsumer(ABC):
    """Base class for modules that consume extractions."""
    
    def __init__(self, extraction_service: ClinicalNoteExtractionService):
        self.extraction_service = extraction_service
    
    @abstractmethod
    def get_required_note_types(self) -> List[str]:
        """Return list of note types this module needs."""
        pass
    
    @abstractmethod
    async def process_extraction(
        self, 
        extraction: ClinicalNoteExtraction
    ) -> Dict[str, Any]:
        """Process an extraction and return module-specific results."""
        pass


class SurgicalProphylaxisConsumer(ExtractionConsumer):
    """Surgical prophylaxis module's extraction consumer."""
    
    def get_required_note_types(self) -> List[str]:
        return ['operative_note', 'anesthesia_record', 'pre_op_note']
    
    async def process_extraction(
        self, 
        extraction: ClinicalNoteExtraction
    ) -> Dict[str, Any]:
        """Extract prophylaxis-relevant data from extraction."""
        
        result = {
            'procedures': [],
            'prophylaxis_given': False,
            'prophylaxis_timing_minutes': None,
            'prophylaxis_agent': None
        }
        
        for proc in extraction.procedures:
            result['procedures'].append({
                'name': proc.procedure_name,
                'cpt': proc.cpt_code,
                'incision_time': proc.incision_time,
                'closure_time': proc.closure_time,
                'duration_minutes': proc.duration_minutes,
                'wound_class': proc.wound_classification,
                'ebl_ml': proc.estimated_blood_loss_ml
            })
            
            if proc.prophylaxis_given:
                result['prophylaxis_given'] = True
                result['prophylaxis_agent'] = proc.prophylaxis_drug
                
                if proc.prophylaxis_time and proc.incision_time:
                    delta = (proc.incision_time - proc.prophylaxis_time).total_seconds() / 60
                    result['prophylaxis_timing_minutes'] = delta
        
        return result


class FebrileInfantConsumer(ExtractionConsumer):
    """Febrile infant module's extraction consumer."""
    
    def get_required_note_types(self) -> List[str]:
        return ['ed_note', 'admission_note', 'progress_note']
    
    async def process_extraction(
        self, 
        extraction: ClinicalNoteExtraction
    ) -> Dict[str, Any]:
        """Extract febrile infant-relevant data."""
        
        result = {
            'hsv_risk_factors': False,
            'clinical_appearance': None,
            'fever_temp_c': None,
            'lp_documented': False,
            'antibiotics': []
        }
        
        # Risk factors
        if extraction.risk_factors:
            result['hsv_risk_factors'] = extraction.risk_factors.hsv_risk_factors
        
        # Clinical assessment
        if extraction.clinical_assessment:
            result['clinical_appearance'] = extraction.clinical_assessment.appearance
        
        # Infection indicators
        if extraction.infection_indicators:
            result['fever_temp_c'] = extraction.infection_indicators.fever_max_temp_c
        
        # Procedures (looking for LP)
        for proc in extraction.procedures:
            if 'lumbar puncture' in proc.procedure_name.lower() or 'lp' in proc.procedure_name.lower():
                result['lp_documented'] = True
        
        # Antibiotics
        for med in extraction.medications:
            # Check if it's an antibiotic
            result['antibiotics'].append({
                'drug': med.drug_name,
                'dose': med.dose,
                'time': med.start_time
            })
        
        return result


# =============================================================================
# ORCHESTRATOR - Coordinates extraction across modules
# =============================================================================

class AEGISExtractionOrchestrator:
    """
    Orchestrates extraction for all AEGIS modules.
    
    Ensures each note is only processed once, then distributes
    results to all modules that need them.
    """
    
    def __init__(self, extraction_service: ClinicalNoteExtractionService):
        self.extraction_service = extraction_service
        self.consumers: Dict[str, ExtractionConsumer] = {}
    
    def register_consumer(self, module_name: str, consumer: ExtractionConsumer):
        """Register a module as an extraction consumer."""
        self.consumers[module_name] = consumer
    
    async def process_encounter(
        self,
        encounter_id: str,
        notes: List[Dict]
    ) -> Dict[str, Dict]:
        """
        Process all notes for an encounter and distribute to modules.
        
        Args:
            encounter_id: Encounter identifier
            notes: List of notes with text, type, datetime, id
            
        Returns:
            Dict mapping module_name -> module results
        """
        # Step 1: Extract from all notes (single LLM call per note)
        extractions = await self.extraction_service.extract_batch(notes)
        
        # Step 2: Distribute to each module
        results = {}
        
        for module_name, consumer in self.consumers.items():
            module_results = []
            
            # Filter to note types this module cares about
            relevant_note_types = consumer.get_required_note_types()
            relevant_extractions = [
                e for e in extractions 
                if e.note_type in relevant_note_types
            ]
            
            # Process each relevant extraction
            for extraction in relevant_extractions:
                module_result = await consumer.process_extraction(extraction)
                module_results.append(module_result)
            
            results[module_name] = {
                'encounter_id': encounter_id,
                'notes_processed': len(relevant_extractions),
                'results': module_results
            }
        
        return results


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

async def example_usage():
    """Example showing how modules share extraction service."""
    
    # Initialize LLM provider
    llm = ClaudeProvider(api_key="your-api-key")
    
    # Initialize extraction service
    extraction_service = ClinicalNoteExtractionService(llm)
    
    # Initialize orchestrator
    orchestrator = AEGISExtractionOrchestrator(extraction_service)
    
    # Register module consumers
    orchestrator.register_consumer(
        'surgical_prophylaxis',
        SurgicalProphylaxisConsumer(extraction_service)
    )
    orchestrator.register_consumer(
        'febrile_infant',
        FebrileInfantConsumer(extraction_service)
    )
    
    # Process an encounter
    notes = [
        {
            'note_text': "Operative note: Patient underwent appendectomy...",
            'note_type': 'operative_note',
            'note_datetime': datetime.now(),
            'note_id': 'note_001'
        },
        {
            'note_text': "Progress note: Patient is afebrile, tolerating diet...",
            'note_type': 'progress_note',
            'note_datetime': datetime.now(),
            'note_id': 'note_002'
        }
    ]
    
    # Single extraction pass, results distributed to all modules
    results = await orchestrator.process_encounter(
        encounter_id='enc_12345',
        notes=notes
    )
    
    print("Surgical Prophylaxis Results:", results['surgical_prophylaxis'])
    print("Febrile Infant Results:", results['febrile_infant'])


if __name__ == '__main__':
    asyncio.run(example_usage())
```

---

## Performance Considerations

### Latency Comparison

| Approach | Notes | LLM Calls | Total Latency |
|----------|-------|-----------|---------------|
| Sequential Independent | 1 note, 5 modules | 5 | 5 × 2s = 10s |
| Parallel Independent | 1 note, 5 modules | 5 | max(2s, 2s, 2s, 2s, 2s) = 2s |
| **Unified Extraction** | 1 note, 5 modules | **1** | **2s** |

### Cost Comparison (per 1000 notes)

| Approach | LLM Calls | Est. Tokens/Call | Total Tokens | Est. Cost* |
|----------|-----------|------------------|--------------|------------|
| Independent (5 modules) | 5,000 | 2,000 | 10M | $30 |
| **Unified Extraction** | **1,000** | **3,500** | **3.5M** | **$10.50** |

*Estimated at $3/M tokens (Claude Sonnet)

### Caching Strategy

```python
# Cache extractions to avoid re-processing same notes
EXTRACTION_CACHE = {
    'note_001': ClinicalNoteExtraction(...),  # Cached result
    'note_002': ClinicalNoteExtraction(...),
}

# TTL: 24 hours (notes don't change once written)
# Invalidation: On note amendment/addendum
```

---

## Deployment Options

### Option A: Cloud API (Simplest)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   AEGIS     │────▶│  Claude API │────▶│  Anthropic  │
│   Server    │     │  (Sonnet)   │     │   Cloud     │
└─────────────┘     └─────────────┘     └─────────────┘

Pros: No infrastructure, always latest model
Cons: PHI leaves network, cost per call
```

### Option B: On-Premise LLM (HIPAA Compliant)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   AEGIS     │────▶│  Local LLM  │────▶│  CCHMC GPU  │
│   Server    │     │  Endpoint   │     │  Cluster    │
└─────────────┘     └─────────────┘     └─────────────┘

Pros: PHI stays on-premise, fixed cost
Cons: Need GPU infrastructure, model maintenance
```

### Option C: Hybrid (Recommended for PHI)

```
┌─────────────┐     ┌─────────────┐     
│   AEGIS     │────▶│ De-identify │     
│   Server    │     │   Layer     │     
└─────────────┘     └──────┬──────┘     
                           │ (No PHI)
                           ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  Claude API │────▶│  Anthropic  │
                    │  (Sonnet)   │     │   Cloud     │
                    └─────────────┘     └─────────────┘

Pros: Best of both worlds
Cons: Complexity, potential information loss
```

---

## Recommendation Summary

For AEGIS with 5-6 modules needing LLM-based note parsing:

1. **Use Unified Extraction Service** (Option 3)
   - Single LLM call per note
   - 3-5x cost reduction
   - Consistent extraction across modules

2. **Implement Caching**
   - Don't re-extract notes that haven't changed
   - 24-hour TTL is reasonable for clinical notes

3. **Use Async/Parallel Processing**
   - When processing multiple notes, run extractions in parallel
   - Limit concurrency to 5-10 to avoid rate limits

4. **Consider On-Premise LLM for PHI**
   - If using cloud API, implement de-identification
   - Llama 3, Mistral, or similar can run on local GPUs

5. **Design for Module Independence**
   - Modules consume from shared extraction
   - Each module filters for relevant note types
   - Easy to add new modules without changing extraction
