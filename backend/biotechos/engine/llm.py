"""Thin Anthropic SDK wrapper with graceful no-API-key degradation.

Every LLM-backed feature calls through here and passes a `fallback` so the demo
runs end-to-end without ANTHROPIC_API_KEY (deterministic canned output). When a
key is present, we use the real model with structured (schema-validated) output.
"""
from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_client = None


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def structured(
    *,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    fallback: T,
    max_tokens: int = 4096,
) -> tuple[T, bool]:
    """Return (result, used_llm). Falls back to `fallback` if no key or on error."""
    if not has_api_key():
        return fallback, False
    try:
        client = _get_client()
        resp = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        return resp.parsed_output, True
    except Exception as e:  # network, auth, parse — demo must not hard-fail
        print(f"[llm] structured() falling back ({type(e).__name__}: {e})")
        return fallback, False


def text(
    *,
    model: str,
    system: str,
    user: str,
    fallback: str,
    max_tokens: int = 4096,
) -> tuple[str, bool]:
    """Return (text, used_llm). Falls back to `fallback` if no key or on error."""
    if not has_api_key():
        return fallback, False
    try:
        client = _get_client()
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        out = next((b.text for b in resp.content if b.type == "text"), "")
        return out or fallback, True
    except Exception as e:
        print(f"[llm] text() falling back ({type(e).__name__}: {e})")
        return fallback, False
