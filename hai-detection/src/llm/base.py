"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    """Response from an LLM call."""
    content: str
    raw_response: dict[str, Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    finish_reason: str | None = None


class BaseLLMClient(ABC):
    """Abstract base class for LLM API clients."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            prompt: The user prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens in response

        Returns:
            LLMResponse with content and metadata
        """
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate a structured response matching a JSON schema.

        Args:
            prompt: The user prompt
            output_schema: JSON schema for the expected output
            system_prompt: Optional system prompt
            temperature: Sampling temperature

        Returns:
            Parsed JSON response matching the schema
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the LLM backend is available."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the model name being used."""
        pass
