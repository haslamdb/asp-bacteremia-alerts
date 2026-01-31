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
    EvidenceSource,
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
from .clabsi_engine import CLABSIRulesEngine, StrictnessLevel, classify_clabsi
from .discrepancy_logger import DiscrepancyLogger, check_and_log_discrepancy
from .ssi_schemas import (
    SSIType,
    SSIClassification,
    SSIExtraction,
    SSIStructuredData,
    SSIClassificationResult,
    WoundAssessmentExtraction,
    SuperficialSSIFindings,
    DeepSSIFindings,
    OrganSpaceSSIFindings,
    ReoperationFindings,
)
from .ssi_engine import SSIRulesEngine
from .vae_schemas import (
    VAEClassification,
    VAETier,
    VAEExtraction,
    VAEStructuredData,
    VAEClassificationResult,
    TemperatureExtraction,
    WBCExtraction,
    AntimicrobialExtraction,
    RespiratorySecretionsExtraction,
    RespiratoryCultureExtraction,
    VentilatorStatusExtraction,
)
from .vae_engine import VAERulesEngine
from .cauti_schemas import (
    CAUTIClassification,
    CAUTIExtraction,
    CAUTIStructuredData,
    CAUTIClassificationResult,
    UrinarySymptomExtraction,
    UrineCultureExtraction,
    CatheterStatusExtraction,
)
from .cauti_engine import CAUTIRulesEngine
from .cdi_schemas import (
    CDIClassification,
    CDIOnsetType,
    CDIRecurrenceStatus,
    CDIExtraction,
    CDIStructuredData,
    CDIClassificationResult,
    DiarrheaExtraction,
    CDIHistoryExtraction,
    CDITreatmentExtraction,
    CDIPriorEpisode,
)
from .cdi_engine import CDIRulesEngine

__all__ = [
    # CLABSI
    "ConfidenceLevel",
    "EvidenceSource",
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
    "StrictnessLevel",
    "classify_clabsi",
    # Discrepancy logging
    "DiscrepancyLogger",
    "check_and_log_discrepancy",
    # SSI
    "SSIType",
    "SSIClassification",
    "SSIExtraction",
    "SSIStructuredData",
    "SSIClassificationResult",
    "WoundAssessmentExtraction",
    "SuperficialSSIFindings",
    "DeepSSIFindings",
    "OrganSpaceSSIFindings",
    "ReoperationFindings",
    "SSIRulesEngine",
    # VAE
    "VAEClassification",
    "VAETier",
    "VAEExtraction",
    "VAEStructuredData",
    "VAEClassificationResult",
    "TemperatureExtraction",
    "WBCExtraction",
    "AntimicrobialExtraction",
    "RespiratorySecretionsExtraction",
    "RespiratoryCultureExtraction",
    "VentilatorStatusExtraction",
    "VAERulesEngine",
    # CAUTI
    "CAUTIClassification",
    "CAUTIExtraction",
    "CAUTIStructuredData",
    "CAUTIClassificationResult",
    "UrinarySymptomExtraction",
    "UrineCultureExtraction",
    "CatheterStatusExtraction",
    "CAUTIRulesEngine",
    # CDI
    "CDIClassification",
    "CDIOnsetType",
    "CDIRecurrenceStatus",
    "CDIExtraction",
    "CDIStructuredData",
    "CDIClassificationResult",
    "DiarrheaExtraction",
    "CDIHistoryExtraction",
    "CDITreatmentExtraction",
    "CDIPriorEpisode",
    "CDIRulesEngine",
]
