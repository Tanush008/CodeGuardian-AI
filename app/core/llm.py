"""Thin wrapper around the Groq API.

Centralized here so agents don't each roll their own retry/error handling,
and so swapping models (or providers, later) is a one-file change.
"""
import json

from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

_client = AsyncGroq(api_key=settings.groq_api_key)


@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
async def complete(system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 2000) -> str:
    """Plain text completion. Low default temperature — this is a review
    tool, not a creative one; we want consistent, reproducible triage."""
    resp = await _client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
async def complete_json(system_prompt: str, user_prompt: str, temperature: float = 0.0, max_tokens: int = 2000) -> dict:
    """JSON-mode completion for structured agent outputs (findings lists,
    severity scores, etc). Raises ValueError if the model doesn't return
    valid JSON after retries — callers should treat that as a hard failure,
    not silently fall back to guessing at unstructured text.
    """
    resp = await _client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": system_prompt + "\n\nRespond with valid JSON only, no prose, no markdown fences."},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("llm_json_parse_failed", raw=raw[:500])
        raise ValueError(f"LLM did not return valid JSON: {exc}") from exc
