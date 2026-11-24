"""Where the lab's settings come from.

- The lab's own defaults, the same for every user: proxy/config/<name>.json.
- The user's own settings: the settings root, ROXY_CONFIG_DIR, which scripts/lib.sh
  resolves and exports; it is never in the repo. lab.settings_root reads and writes its
  devices, LAN subnets and secrets; lab.app_profiles its App Profiles (<settings root>/apps/).
"""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SETTINGS_ROOT_VAR = "ROXY_CONFIG_DIR"


def load_config(name):
    return json.loads((CONFIG_DIR / f"{name}.json").read_text())


def settings_root():
    root = os.environ.get(SETTINGS_ROOT_VAR)
    if not root:
        raise RuntimeError(f"{SETTINGS_ROOT_VAR} is not set: start the lab with scripts/start-lab")
    return Path(root)

