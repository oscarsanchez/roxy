import shutil
from pathlib import Path

import pytest

SETTINGS_EXAMPLE = Path(__file__).resolve().parents[2] / "settings.example"


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    """The user's roxy settings: a temp settings root seeded from the repo's examples,
    never the real one. A test may rewrite a file in it."""
    root = tmp_path / "roxy-settings"
    shutil.copytree(SETTINGS_EXAMPLE, root)
    monkeypatch.setenv("ROXY_CONFIG_DIR", str(root))
    return root
