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


def has_api_key(api_key: str | None = None) -> bool:
    return bool(api_key or os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _get_client(api_key: str | None = None):
    """A per-key client (user-supplied keys aren't cached) or the cached env client."""
    import anthropic
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    global _client
    if _client is None:
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
    api_key: str | None = None,
    timeout: float | None = None,
) -> tuple[T, bool]:
    """Return (result, used_llm). Falls back to `fallback` if no key or on error.
    `timeout` (seconds) is worth raising for slower models (Opus) on large inputs."""
    if not has_api_key(api_key):
        return fallback, False
    try:
        client = _get_client(api_key)
        if timeout is not None:
            client = client.with_options(timeout=timeout)
        resp = client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        # a malformed/empty completion can parse to None — never propagate that
        return (resp.parsed_output, True) if resp.parsed_output is not None else (fallback, False)
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
    api_key: str | None = None,
) -> tuple[str, bool]:
    """Return (text, used_llm). Falls back to `fallback` if no key or on error."""
    if not has_api_key(api_key):
        return fallback, False
    try:
        client = _get_client(api_key)
        resp = _create_with_retry(
            client,
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


def _create_with_retry(client, tries: int = 4, **kw):
    """messages.create with backoff on transient 'overloaded' (529) errors."""
    import time
    last = None
    for i in range(tries):
        try:
            return client.messages.create(**kw)
        except Exception as e:                       # noqa: BLE001
            last = e
            if "overload" in str(e).lower() or "529" in str(e):
                time.sleep(1.5 * (i + 1))
                continue
            raise
    raise last


def document_json(
    *,
    model: str,
    system: str,
    user: str,
    files: list[tuple[str, bytes, str]],   # (media_type, bytes, filename)
    fallback: dict,
    max_tokens: int = 4096,
    api_key: str | None = None,
    timeout: float | None = None,
) -> tuple[dict, bool]:
    """Send real attachment binaries to Claude NATIVELY (PDF via document blocks,
    images via image blocks) and parse a JSON object from the reply. For reading
    figures/plots/scanned pages that text extraction can't see."""
    import base64 as _b64
    import json as _json
    import re as _re
    if not has_api_key(api_key) or not files:
        return fallback, False
    try:
        client = _get_client(api_key)
        if timeout is not None:
            client = client.with_options(timeout=timeout)
        content: list = [{"type": "text", "text": user}]
        for media_type, data, _name in files:
            b64 = _b64.standard_b64encode(data).decode()
            if media_type.startswith("image/"):
                content.append({"type": "image",
                                "source": {"type": "base64", "media_type": media_type, "data": b64}})
            else:  # application/pdf
                content.append({"type": "document",
                                "source": {"type": "base64", "media_type": media_type, "data": b64}})
        resp = _create_with_retry(
            client,
            model=model, max_tokens=max_tokens,
            system=system + "\n\nReturn ONLY a single JSON object, no prose, no code fences.",
            messages=[{"role": "user", "content": content}])
        txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        m = _re.search(r"\{.*\}", txt, _re.S)
        return (_json.loads(m.group(0)) if m else fallback), True
    except Exception as e:
        print(f"[llm] document_json() falling back ({type(e).__name__}: {e})")
        return fallback, False


def json_object(
    *,
    model: str,
    system: str,
    user: str,
    fallback: dict,
    max_tokens: int = 4096,
    api_key: str | None = None,
    timeout: float | None = None,
) -> tuple[dict, bool]:
    """Extract a JSON object via an UNCONSTRAINED completion + parse — for schemas too
    rich for grammar-constrained decoding (which can 400 'grammar compilation timed
    out'). Returns (obj, used_llm); falls back to `fallback` on no key / parse error."""
    import json as _json
    import re as _re
    if not has_api_key(api_key):
        return fallback, False
    try:
        client = _get_client(api_key)
        if timeout is not None:
            client = client.with_options(timeout=timeout)
        resp = _create_with_retry(
            client,
            model=model, max_tokens=max_tokens,
            system=system + "\n\nReturn ONLY a single JSON object, no prose, no code fences.",
            messages=[{"role": "user", "content": user}],
        )
        txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        m = _re.search(r"\{.*\}", txt, _re.S)      # tolerate stray text/fences around it
        return (_json.loads(m.group(0)) if m else fallback), True
    except Exception as e:
        print(f"[llm] json_object() falling back ({type(e).__name__}: {e})")
        return fallback, False


def chat(
    *,
    model: str,
    system: str,
    messages: list[dict],
    fallback: str,
    max_tokens: int = 2048,
    api_key: str | None = None,
) -> tuple[str, bool]:
    """Multi-turn conversation. `messages` is a list of {role, content}. Returns
    (assistant_text, used_llm). Falls back to a canned reply if no key/on error."""
    if not has_api_key(api_key):
        return fallback, False
    try:
        client = _get_client(api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
        )
        out = next((b.text for b in resp.content if b.type == "text"), "")
        return out or fallback, True
    except Exception as e:
        print(f"[llm] chat() falling back ({type(e).__name__}: {e})")
        return fallback, False
