"""Ollama LLM client for local inference.

Ollama provides local LLM inference, keeping PHI on-premise without
requiring a BAA.
"""

import json
import logging
import time
from typing import Any

import requests

from ..config import Config
from .base import BaseLLMClient, LLMResponse

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Ollama API client for local LLM inference."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 300,  # Increased for large models like 70b
    ):
        """Initialize Ollama client.

        Args:
            base_url: Ollama API base URL. Uses config if None.
            model: Model to use. Uses config if None.
            timeout: Request timeout in seconds.
        """
        self.base_url = (base_url or Config.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or Config.OLLAMA_MODEL
        self.timeout = timeout
        self.session = requests.Session()

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response using Ollama."""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            start_time = time.time()
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            elapsed_ms = int((time.time() - start_time) * 1000)

            data = response.json()

            return LLMResponse(
                content=data.get("message", {}).get("content", ""),
                raw_response=data,
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                model=self.model,
                finish_reason=data.get("done_reason"),
            )

        except requests.RequestException as e:
            logger.error(f"Ollama request failed: {e}")
            raise

    def generate_structured(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate a structured JSON response.

        Uses Ollama's format parameter for JSON output.
        """
        # Build system prompt with JSON schema
        schema_prompt = f"""You must respond with valid JSON matching this schema:
{json.dumps(output_schema, indent=2)}

{system_prompt or ''}"""

        messages = [
            {"role": "system", "content": schema_prompt},
            {"role": "user", "content": prompt},
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
            },
        }

        try:
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            content = data.get("message", {}).get("content", "{}")

            # Parse JSON response
            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Ollama JSON response: {e}")
            raise ValueError(f"Invalid JSON response: {e}")
        except requests.RequestException as e:
            logger.error(f"Ollama request failed: {e}")
            raise

    def is_available(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            response = self.session.get(
                f"{self.base_url}/api/tags",
                timeout=5,
            )
            response.raise_for_status()

            # Check if our model is in the list
            data = response.json()
            models = [m.get("name") for m in data.get("models", [])]

            # Handle model names with and without tags
            model_base = self.model.split(":")[0]
            return any(
                m == self.model or m.startswith(model_base)
                for m in models
            )

        except requests.RequestException:
            return False

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self.model

    def pull_model(self) -> bool:
        """Pull the model if not available."""
        try:
            logger.info(f"Pulling model {self.model}...")
            response = self.session.post(
                f"{self.base_url}/api/pull",
                json={"name": self.model},
                timeout=3600,  # Long timeout for model download
                stream=True,
            )
            response.raise_for_status()

            # Stream progress
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    if "status" in data:
                        logger.info(f"Pull status: {data['status']}")

            return True

        except requests.RequestException as e:
            logger.error(f"Failed to pull model: {e}")
            return False
