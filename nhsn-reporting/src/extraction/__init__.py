"""Clinical information extraction module.

This module provides LLM-based extraction of clinical information from
notes. The extracted data is used by the rules engine to apply NHSN
criteria deterministically.

Architecture:
    Notes → ClinicalExtractor (LLM) → ClinicalExtraction → RulesEngine
"""

from .clabsi_extractor import CLABSIExtractor

__all__ = ["CLABSIExtractor"]
