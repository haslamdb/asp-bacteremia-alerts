"""Pydantic-style schemas for LLM output validation.

Note: Using dataclasses to match existing codebase pattern, but these
could be converted to Pydantic models if needed for stricter validation.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class EvidenceItem:
    """A piece of supporting or contradicting evidence."""
    text: str
    source: str
    relevance: str | None = None


@dataclass
class CLABSIClassificationOutput:
    """Expected output schema for CLABSI classification.

    This mirrors the JSON schema used in the prompt.
    """
    decision: Literal["hai_confirmed", "not_hai", "pending_review"]
    confidence: float
    reasoning: str
    alternative_source: str | None = None
    is_mbi_lcbi: bool = False
    supporting_evidence: list[EvidenceItem] = field(default_factory=list)
    contradicting_evidence: list[EvidenceItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CLABSIClassificationOutput":
        """Parse from LLM JSON response."""
        supporting = [
            EvidenceItem(**e) for e in data.get("supporting_evidence", [])
        ]
        contradicting = [
            EvidenceItem(**e) for e in data.get("contradicting_evidence", [])
        ]

        return cls(
            decision=data.get("decision", "pending_review"),
            confidence=data.get("confidence", 0.5),
            reasoning=data.get("reasoning", ""),
            alternative_source=data.get("alternative_source"),
            is_mbi_lcbi=data.get("is_mbi_lcbi", False),
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "alternative_source": self.alternative_source,
            "is_mbi_lcbi": self.is_mbi_lcbi,
            "supporting_evidence": [
                {"text": e.text, "source": e.source, "relevance": e.relevance}
                for e in self.supporting_evidence
            ],
            "contradicting_evidence": [
                {"text": e.text, "source": e.source, "relevance": e.relevance}
                for e in self.contradicting_evidence
            ],
        }


# JSON Schema for LLM structured output
CLABSI_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["hai_confirmed", "not_hai", "pending_review"],
            "description": "The classification decision",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in the decision (0.0 to 1.0)",
        },
        "alternative_source": {
            "type": ["string", "null"],
            "description": "Alternative infection source if not CLABSI",
        },
        "is_mbi_lcbi": {
            "type": "boolean",
            "description": "Whether this qualifies as MBI-LCBI",
        },
        "supporting_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source": {"type": "string"},
                    "relevance": {"type": "string"},
                },
                "required": ["text", "source"],
            },
            "description": "Evidence supporting the decision",
        },
        "contradicting_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source": {"type": "string"},
                    "relevance": {"type": "string"},
                },
                "required": ["text", "source"],
            },
            "description": "Evidence contradicting the decision",
        },
        "reasoning": {
            "type": "string",
            "description": "Detailed reasoning for the classification",
        },
    },
    "required": ["decision", "confidence", "reasoning"],
}
