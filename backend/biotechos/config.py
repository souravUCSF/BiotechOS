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

for _d in (CURATED_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
