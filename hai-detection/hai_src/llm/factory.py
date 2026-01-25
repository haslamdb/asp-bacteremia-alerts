"""Factory for LLM client creation."""

import logging

from ..config import Config
from .base import BaseLLMClient
from .ollama import OllamaClient
from .vllm import VLLMClient

logger = logging.getLogger(__name__)


def get_llm_client(backend: str | None = None) -> BaseLLMClient:
    """Get the configured LLM client.

    Args:
        backend: Override backend selection. Uses config if None.

    Returns:
        Configured LLM client instance.

    Raises:
        ValueError: If backend is not configured or not available.
    """
    backend = backend or Config.LLM_BACKEND

    if backend == "ollama":
        if not Config.is_ollama_configured():
            raise ValueError("Ollama is not configured")

        client = OllamaClient()

        if not client.is_available():
            logger.warning(
                f"Ollama model {client.model} not available. "
                "You may need to pull it first."
            )

        return client

    elif backend == "vllm":
        if not Config.is_vllm_configured():
            raise ValueError("vLLM is not configured")

        client = VLLMClient()

        if not client.is_available():
            logger.warning(
                f"vLLM model {client.model} not available. "
                "Make sure the vLLM server is running."
            )

        return client

    elif backend == "claude":
        if not Config.is_claude_configured():
            raise ValueError("Claude API is not configured")

        # Future: Import and return ClaudeClient
        raise NotImplementedError("Claude client not yet implemented")

    else:
        raise ValueError(f"Unknown LLM backend: {backend}")


def check_llm_availability() -> tuple[bool, str]:
    """Check if any LLM backend is available.

    Returns:
        Tuple of (is_available, status_message)
    """
    try:
        client = get_llm_client()
        if client.is_available():
            return True, f"LLM available: {client.model_name}"
        else:
            return False, f"LLM not available: {client.model_name}"
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"LLM check failed: {e}"
