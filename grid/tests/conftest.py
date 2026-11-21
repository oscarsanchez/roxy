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


@pytest.fixture(autouse=True)
def out_dir(tmp_path, monkeypatch):
    """Where the grid writes its evidence (scripts/lib.sh ROXY_OUT_DIR): a temp folder, never
    the checkout's out/."""
    out = tmp_path / "out"
    monkeypatch.setenv("ROXY_OUT_DIR", str(out))
    return out
