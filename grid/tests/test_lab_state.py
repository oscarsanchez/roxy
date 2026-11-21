"""A cell runs only through this checkout's lab, and a CA Routing cell only through a lab in
CA Routing, as `roxy status --json` reports it. A fake roxy answers; each run stops before it
touches a Target Device."""

import json

import pytest

import run_cell
from run_cell import main


@pytest.fixture
def lab_state(tmp_path, monkeypatch):
    """Make the running lab's state, as a fake roxy reports it, the dict given (over the
    state of this checkout's lab, not in CA Routing)."""
    (tmp_path / "bin").mkdir()
    monkeypatch.setattr(run_cell, "REPO", tmp_path)

    def answer(**state):
        state = {"app": None, "scenarios": [], "ca_routing": False,
                 "scenarios_dir": str(tmp_path / "proxy" / "scenarios"), **state}
        roxy = tmp_path / "bin" / "roxy"
        roxy.write_text(f"#!/usr/bin/env bash\n[ \"$*\" = 'status --json' ] && echo '{json.dumps(state)}'\n")
        roxy.chmod(0o755)

    return answer


def test_a_lab_started_from_another_checkout_is_not_used(lab_state):
    lab_state(scenarios_dir="/elsewhere/proxy/scenarios")

    with pytest.raises(SystemExit, match=r"not this checkout's \(its scenarios: /elsewhere/proxy/scenarios\)"):
        main(["classic", "physical", "json", "--proxy-base", "http://192.0.2.10:8080"])


def test_a_ca_routing_cell_needs_the_lab_in_ca_routing(lab_state):
    lab_state(ca_routing=False)

    with pytest.raises(SystemExit, match="the lab is not in CA Routing"):
        main(["classic", "physical", "json", "--ca-routing"])
