"""Where the lab's settings come from.

- The lab's own defaults, the same for every user: proxy/config/<name>.json.
- The user's own settings (devices, LAN subnets): <settings root>/<name>.json. The settings
  root is ROXY_CONFIG_DIR, which scripts/lib.sh resolves and exports; it is never in the repo.
"""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SETTINGS_ROOT_VAR = "ROXY_CONFIG_DIR"


def load_config(name):
    return json.loads((CONFIG_DIR / f"{name}.json").read_text())


def load_settings(name):
    root = os.environ.get(SETTINGS_ROOT_VAR)
    if not root:
        raise RuntimeError(f"{SETTINGS_ROOT_VAR} is not set: start the lab with scripts/start-lab")
    path = Path(root) / f"{name}.json"
    if not path.is_file():
        raise RuntimeError(f"missing setting file {path} (example: settings.example/{name}.json)")
    return json.loads(path.read_text())
