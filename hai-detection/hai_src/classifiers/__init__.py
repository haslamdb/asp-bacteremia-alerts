"""HAI classification using LLM extraction + rules engine.

Classifiers available:
- CLABSIClassifier: Legacy LLM-only classification
- CLABSIClassifierV2: Extraction + Rules architecture (recommended)
- SSIClassifierV2: SSI classification with extraction + rules
- VAEClassifier: VAE classification with extraction + rules
- CAUTIClassifier: CAUTI classification with extraction + rules
- CDIClassifier: CDI classification with extraction + rules
"""

from .base import BaseHAIClassifier
from .clabsi_classifier import CLABSIClassifier
from .clabsi_classifier_v2 import CLABSIClassifierV2
from .ssi_classifier import SSIClassifierV2
from .vae_classifier import VAEClassifier
from .cauti_classifier import CAUTIClassifier
from .cdi_classifier import CDIClassifier

__all__ = [
    "BaseHAIClassifier",
    "CLABSIClassifier",
    "CLABSIClassifierV2",
    "SSIClassifierV2",
    "VAEClassifier",
    "CAUTIClassifier",
    "CDIClassifier",
]
