from pathlib import Path
import sys

PROJECT_APP_DIR = Path(__file__).resolve().parents[1] / "predictelligence-property"
if str(PROJECT_APP_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_APP_DIR))

from app import app  # noqa: E402

# Vercel Python runtime expects `app`
