import shutil
import socket
from pathlib import Path

import pytest

PUBLIC_IP = "93.184.215.14"
SETTINGS_EXAMPLE = Path(__file__).resolve().parents[2] / "settings.example"


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    """The user's roxy settings: a temp settings root seeded from the repo's examples,
    never the real one. A test may rewrite a file in it before it starts the lab."""
    root = tmp_path / "roxy-settings"
    shutil.copytree(SETTINGS_EXAMPLE, root)
    monkeypatch.setenv("ROXY_CONFIG_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """Stubbed DNS: every host resolves to a public IP unless a test sets
    dns[host] = [ip, ...]; an empty list means the host does not resolve.
    Covers loop.getaddrinfo too (it calls socket.getaddrinfo)."""
    answers = {}

    def getaddrinfo(host, port, *args, **kwargs):
        if answers.get(host) == []:
            raise socket.gaierror(socket.EAI_NONAME, "nodename nor servname provided, or not known")
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))
            if ":" in ip
            else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
            for ip in answers.get(host, [PUBLIC_IP])
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return answers


@pytest.fixture
def scenarios(tmp_path):
    """Write scenario files into a scenarios dir; returns lab options that activate one."""

    def write(name, toml):
        (tmp_path / f"{name}.toml").write_text(toml)
        return {"lab_scenarios_dir": str(tmp_path), "lab_scenario": name}

    return write
