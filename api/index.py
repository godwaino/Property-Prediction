from pathlib import Path
import sys

# Root-level premium app (Rightmove URL dashboard + enrichment + Claude AI)
ROOT_DIR = Path(__file__).resolve().parents[1]
# predictelligence-property still needed for the ML engine package
PRED_PROP_DIR = ROOT_DIR / "predictelligence-property"

for _p in [str(ROOT_DIR), str(PRED_PROP_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import app  # noqa: E402  (picks up root/app.py)

# Vercel Python runtime expects `app`
