"""Entity-name normalization for the knowledge layer.

Facts and aliases about the same real-world entity arrive under many surface
forms — "Vendor 1", "Vendor 1, Inc.", "vendor-1  INC" — and under different
predicate names. `normalize_key` collapses those variants to one stable key so
callers (KB profile auto-fill, alias promotion) can dedupe/group them. There is
no separate `entities` table today, so `resolve_entity` simply returns that key
as the entity's stable identifier.
"""
from __future__ import annotations

import re

# Legal-form / boilerplate suffixes stripped when comparing organization names.
_LEGAL_SUFFIXES = (
    "incorporated", "inc", "corporation", "corp", "company", "co",
    "limited", "ltd", "llc", "llp", "lp", "plc", "gmbh", "ag", "sa",
    "srl", "bv", "pvt", "private", "pte", "kk", "kg", " aps",
)
_LEGAL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in _LEGAL_SUFFIXES) + r")\b", re.IGNORECASE
)


def normalize_key(entity_type: str, name: str) -> str:
    """Stable dedupe key for an entity of a given type. Case/punctuation/legal-form
    insensitive: normalize_key('vendor', 'Vendor 1, Inc.') == normalize_key('vendor',
    'vendor-1')."""
    n = (name or "").lower()
    n = _LEGAL_RE.sub(" ", n)              # drop Inc./Ltd./LLC/… tokens
    n = re.sub(r"[^a-z0-9]+", " ", n)      # punctuation -> space
    n = re.sub(r"\s+", " ", n).strip()
    return f"{(entity_type or '').lower()}:{n}"


def resolve_entity(conn, program_id: str, entity_type: str, name: str) -> str:
    """Resolve an entity to a stable identifier. No dedicated entity table exists,
    so the normalized key IS the identity. Kept as a hook for a future entities
    table; callers must not assume it is an integer row id."""
    return normalize_key(entity_type, name)
