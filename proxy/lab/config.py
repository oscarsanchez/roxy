"""The lab's defaults: proxy/config/<name>.json, editable without code changes."""

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_config(name):
    return json.loads((CONFIG_DIR / f"{name}.json").read_text())
