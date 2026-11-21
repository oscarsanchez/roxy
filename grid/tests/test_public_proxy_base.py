"""A Cloud Device cell launches with the running tunnel's public Proxy Base, as scripts/launch
does, unless --proxy-base names another. Fakes on PATH: curl answers for cloudflared's metrics
(FAKE_TUNNEL_HOST set: a tunnel is up), rce knows every Device Name. Each run stops before it
touches a Target Device: no lab answers roxy status."""

import os

import pytest

from run_cell import main

CELL = ["classic", "cloud", "json"]
FAKE_CURL = """#!/usr/bin/env bash
for a in "$@"; do url="$a"; done
case "$url" in
  */quicktunnel) [ -n "${FAKE_TUNNEL_HOST:-}" ] || { echo "curl: (7) Failed to connect" >&2; exit 7; }
    printf '{"hostname": "%s"}\\n' "$FAKE_TUNNEL_HOST" ;;
  *) exit 7 ;;
esac
"""


@pytest.fixture(autouse=True)
def fakes(settings, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(FAKE_CURL)
    (bin_dir / "rce").write_text("#!/usr/bin/env bash\n")
    for fake in bin_dir.iterdir():
        fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("FAKE_TUNNEL_HOST", raising=False)
    (settings / "secrets.env").write_text("LAB_SECRET=s3cret\nMITMWEB_PASSWORD=\n")


def test_a_cloud_cell_uses_the_running_tunnels_public_proxy_base_and_prints_no_secret(monkeypatch, capfd):
    monkeypatch.setenv("FAKE_TUNNEL_HOST", "example.trycloudflare.com")
    with pytest.raises(SystemExit):
        main(CELL)
    out, err = capfd.readouterr()
    assert "Proxy Base https://example.trycloudflare.com/<secret>, separator /)" in out
    assert "s3cret" not in out + err


def test_a_cloud_cell_without_a_tunnel_says_how_to_start_one(capfd):
    with pytest.raises(SystemExit):
        main(CELL)
    out, err = capfd.readouterr()
    assert "roxy start --tunnel" in err
    assert "cell:" not in out


def test_proxy_base_overrides_the_tunnels(monkeypatch, capfd):
    monkeypatch.setenv("FAKE_TUNNEL_HOST", "example.trycloudflare.com")
    with pytest.raises(SystemExit):
        main([*CELL, "--proxy-base", "https://203.0.113.5/other"])
    assert "Proxy Base https://203.0.113.5/other, separator /)" in capfd.readouterr().out
