from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ppd_sqlite import get_data_dir

CACHE_PATH = get_data_dir() / "analysis_cache.json"


def load_cache() -> Dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text())


def save_cache(data: Dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2))
