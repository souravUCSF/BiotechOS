"""Map raw target identifiers to their preferred names so the app reads like a
real biotech's data, not a public-database dump.

Preferred names come from the dataset's own `target_name` column (e.g.
CHEMBL612558 -> "ADMET"). The map is built once and cached to
data/reference/target_names.json.
"""
from __future__ import annotations

import json

import pandas as pd

from ..config import DATA_DIR, RAW_DEMO

MAP_PATH = DATA_DIR / "reference" / "target_names.json"

# on/anti-target canonical display names
_CANONICAL = {
    "TGTA": "TGTA",
    "TGTB": "TGTB",
    "TGTA/TGTB": "TGTA / TGTB",
}

# ChEMBL "target_name" values that aren't real protein targets: assay organisms
# and curation placeholders. These read as noise in the app, so collapse them to
# a clean, honest label instead of exposing the raw string or a CHEMBL id.
_ORGANISMS = {
    "homo sapiens", "rattus norvegicus", "mus musculus", "canis familiaris",
    "oryctolagus cuniculus", "cavia porcellus", "bos taurus", "sus scrofa",
    "macaca mulatta", "macaca fascicularis", "gallus gallus",
}
_PLACEHOLDERS = {
    "unchecked", "no relevant target", "no target assigned", "unclassified",
    "unknown", "none", "non-protein target", "non-molecular target",
}


def _clean_name(name: str) -> str:
    """Collapse non-target ChEMBL labels to an honest display value."""
    low = name.strip().lower()
    if low in _ORGANISMS or low in _PLACEHOLDERS:
        return "off-target"
    if low in ("admet", "adme"):
        return "ADME"
    return name


_cache: dict[str, str] | None = None


def build_map() -> dict[str, str]:
    """Scan the dataset once for target_chembl_id -> target_name; cache to JSON."""
    m: dict[str, str] = {}
    for chunk in pd.read_csv(RAW_DEMO, usecols=["target_chembl_id", "target_name"],
                             chunksize=200_000, low_memory=False):
        for cid, name in zip(chunk["target_chembl_id"], chunk["target_name"]):
            if isinstance(cid, str) and cid.startswith("CHEMBL") and isinstance(name, str) and name:
                m.setdefault(cid, name)
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAP_PATH.write_text(json.dumps(m, indent=0))
    return m


def load_map() -> dict[str, str]:
    global _cache
    if _cache is None:
        if MAP_PATH.exists():
            _cache = json.loads(MAP_PATH.read_text())
        else:
            _cache = {}
    return _cache


def pretty_target(target: str | None) -> str | None:
    """Preferred display name for a target label."""
    if not target:
        return target
    if target in _CANONICAL:
        return _CANONICAL[target]
    if target.startswith("CHEMBL"):
        name = load_map().get(target)
        return _clean_name(name) if name else "off-target"
    return target


if __name__ == "__main__":
    m = build_map()
    print(f"cached {len(m)} target names -> {MAP_PATH}")
