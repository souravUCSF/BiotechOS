"""Central paths and constants."""
from pathlib import Path

# repo_root/backend/biotechos/config.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]
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

for _d in (CURATED_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
