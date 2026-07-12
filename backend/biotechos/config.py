"""Central paths and constants."""
import os
from pathlib import Path

# repo_root/backend/biotechos/config.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_secrets() -> None:
    """Load KEY=VALUE lines from backend/secrets.env into the environment (if not
    already set). This file is gitignored — paste local keys there."""
    secrets = REPO_ROOT / "backend" / "secrets.env"
    if not secrets.exists():
        return
    for line in secrets.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if val and not os.environ.get(key):
            os.environ[key] = val


_load_secrets()
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CURATED_DIR = DATA_DIR / "curated"
CACHE_DIR = DATA_DIR / "cache"          # Boltz structures + ADME, gitignored
DB_PATH = DATA_DIR / "biotechos.db"     # gitignored

RAW_DEMO = RAW_DIR / "demo_activities_long.csv.gz"

# Hero program
DEMO_PROGRAM_ID = "demo"
PROGRAM_B_ID = "program-b"
# Real (un-anonymized) Program A archive loaded as its own program (local only).
PROGRAM_A_ID = "program-a"

# program_id → raw archive / corpus org subdir under DATASTORE_ROOT and CORPUS_DIR.
PROGRAM_ORG = {
    "demo": "Program A",
    "program-b": "Program B",
    "program-a": "Program A",   # real archive at DATASTORE_ROOT/Program A (un-anonymized)
}


def org_for_program(program_id: str) -> str:
    return PROGRAM_ORG.get(program_id, CORPUS_ORG)
PRIMARY_TARGET = "TGTA"          # CHEMBL1824 / P04626
PRIMARY_TARGET_CHEMBL = "CHEMBL1824"
TGTB_ANTITARGET = "TGTB"       # CHEMBL203 / P00533
TGTB_ANTITARGET_CHEMBL = "CHEMBL203"

DEMO_SET_SIZE = 50
HELD_OUT_COUNT = 25

# --- LLM model tiers (see plan). Centralized so they're tunable in one place. ---
# TPP Builder is the genuine hard-reasoning step -> best available model.
# Artifact drafting (memos/PO/email) -> quality/latency balance.
# Doc extraction -> high-volume, well-scoped.
MODEL_TPP_BUILDER = "claude-opus-4-8"
MODEL_ARTIFACTS = "claude-sonnet-4-6"
MODEL_EXTRACTION = "claude-haiku-4-5-20251001"

# --- Corpus / mailbox ingestion (Inbox v2) --------------------------------
# Raw real archive: LOCAL ONLY, lives OUTSIDE the repo, never committed.
DATASTORE_ROOT = Path(os.environ.get("DATASTORE_ROOT", str(Path.home() / "DataStore")))
CORPUS_ORG = os.environ.get("CORPUS_ORG", "Program A")
# 'anonymized' (default; safe → committed, feeds TGTA) | 'real' (raw, local only)
MAILBOX_SOURCE = os.environ.get("MAILBOX_SOURCE", "anonymized")

# Anonymized corpus output — INSIDE the repo so it syncs to GitHub (safe: surrogate
# structures, TGTA/TGTB targets, masked vendors, real numbers).
CORPUS_DIR = DATA_DIR / "corpus"
# Anonymization maps (real_InChIKey→surrogate, target, vendor) — SECRET, gitignored.
CORPUS_MAPS_DIR = DATA_DIR / "corpus_maps"

for _d in (CURATED_DIR, CACHE_DIR, CORPUS_DIR, CORPUS_MAPS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
