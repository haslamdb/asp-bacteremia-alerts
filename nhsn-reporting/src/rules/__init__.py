"""NHSN rules engine for HAI classification.

This module provides deterministic classification logic based on NHSN criteria.
The rules engine takes structured LLM extraction output and applies NHSN criteria
to produce a final classification.

Architecture:
    Notes → LLM Extraction → Rules Engine → Classification

The LLM's job is information extraction (what symptoms are documented, is there
an alternate source mentioned, etc). The rules engine applies the actual NHSN
criteria deterministically.
"""

from .schemas import (
    ConfidenceLevel,
    DocumentedInfectionSite,
    SymptomExtraction,
    MBIFactors,
    LineAssessment,
    ContaminationAssessment,
    ClinicalExtraction,
    StructuredCaseData,
    CLABSIClassification,
    ClassificationResult,
)
from .clabsi_engine import CLABSIRulesEngine

__all__ = [
    "ConfidenceLevel",
    "DocumentedInfectionSite",
    "SymptomExtraction",
    "MBIFactors",
    "LineAssessment",
    "ContaminationAssessment",
    "ClinicalExtraction",
    "StructuredCaseData",
    "CLABSIClassification",
    "ClassificationResult",
    "CLABSIRulesEngine",
]
