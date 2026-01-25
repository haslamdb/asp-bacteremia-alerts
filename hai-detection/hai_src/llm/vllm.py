"""vLLM client for high-throughput local inference.

vLLM provides optimized LLM inference with:
- PagedAttention for efficient memory management
- Continuous batching for high throughput
- OpenAI-compatible API
"""

import json
import logging
import time
from typing import Any

import requests

from ..config import Config
from .base import BaseLLMClient, LLMResponse

logger = logging.getLogger(__name__)


class VLLMClient(BaseLLMClient):
    """vLLM API client using OpenAI-compatible endpoint.

    vLLM serves models with an OpenAI-compatible API at /v1/chat/completions.
    This client communicates directly with that endpoint.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int = 300,
    ):
        """Initialize vLLM client.

        Args:
            base_url: vLLM API base URL (e.g., http://localhost:8000).
                     Uses VLLM_BASE_URL config if None.
            model: Model name. Uses VLLM_MODEL config if None.
            timeout: Request timeout in seconds.
        """
        self.base_url = (base_url or getattr(Config, 'VLLM_BASE_URL', 'http://localhost:8000')).rstrip("/")
        self.model = model or getattr(Config, 'VLLM_MODEL', 'Qwen/Qwen2.5-72B-Instruct')
        self.timeout = timeout
        self.session = requests.Session()

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a response using vLLM's OpenAI-compatible API."""
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            start_time = time.time()
            response = self.session.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            elapsed = time.time() - start_time

            data = response.json()
            choice = data.get("choices", [{}])[0]
            usage = data.get("usage", {})

            logger.debug(
                f"vLLM response in {elapsed:.1f}s: "
                f"{usage.get('prompt_tokens', 0)} in, "
                f"{usage.get('completion_tokens', 0)} out"
            )

            return LLMResponse(
                content=choice.get("message", {}).get("content", ""),
                raw_response=data,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                model=data.get("model", self.model),
                finish_reason=choice.get("finish_reason"),
            )

        except requests.RequestException as e:
            logger.error(f"vLLM request failed: {e}")
            raise

    def generate_structured(
        self,
        prompt: str,
        output_schema: dict[str, Any],
        system_prompt: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Generate a structured JSON response.

        Uses guided generation if available, otherwise prompts for JSON.
        """
        # Build system prompt with JSON schema instruction
        schema_prompt = f"""You must respond with valid JSON matching this schema:
{json.dumps(output_schema, indent=2)}

Respond ONLY with the JSON object, no other text.

{system_prompt or ''}"""

        messages = [
            {"role": "system", "content": schema_prompt},
            {"role": "user", "content": prompt},
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4096,
        }

        # Try to use vLLM's guided decoding if available
        # This ensures valid JSON output
        try:
            # vLLM supports guided_json parameter for structured output
            payload["extra_body"] = {
                "guided_json": output_schema,
            }
        except Exception:
            # Fall back to regular generation with JSON prompt
            pass

        try:
            response = self.session.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            data = response.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")

            # Clean up response (remove markdown code blocks if present)
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            return json.loads(content)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse vLLM JSON response: {e}")
            logger.debug(f"Raw content: {content}")
            raise ValueError(f"Invalid JSON response: {e}")
        except requests.RequestException as e:
            logger.error(f"vLLM request failed: {e}")
            raise

    def is_available(self) -> bool:
        """Check if vLLM server is running and model is loaded."""
        try:
            # Check the /v1/models endpoint
            response = self.session.get(
                f"{self.base_url}/v1/models",
                timeout=5,
            )
            response.raise_for_status()

            data = response.json()
            models = [m.get("id") for m in data.get("data", [])]

            # Check if our model is available
            return any(
                m == self.model or self.model in m or m in self.model
                for m in models
            )

        except requests.RequestException:
            return False

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self.model

    def get_model_info(self) -> dict[str, Any]:
        """Get information about the loaded model."""
        try:
            response = self.session.get(
                f"{self.base_url}/v1/models",
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get model info: {e}")
            return {}
