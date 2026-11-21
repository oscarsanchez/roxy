"""A grid cell runs in either Prefixed URL form: the Lab App's `separator` launch param,
`/` (the lab's own, the default) or `/;` (the Charles-style form)."""

import shlex

import pytest

import run_cell
from run_cell import Console, Session, launch_once, main
from verdict import Cell

PROXY_BASE = "http://192.0.2.10:8080"
CELL = ["classic", "physical", "json", "--proxy-base", PROXY_BASE]


@pytest.fixture
def launches(tmp_path, monkeypatch):
    """A fake scripts/launch in place of the real one, and a fake roxy whose lab has no flows;
    return a reader of the launch's argument lists."""
    scripts, bin_dir = tmp_path / "scripts", tmp_path / "bin"
    scripts.mkdir()
    bin_dir.mkdir()
    log = tmp_path / "launch.log"
    (scripts / "launch").write_text(f'#!/usr/bin/env bash\nprintf "%q " "$@" >> {log}; echo >> {log}\necho run=7\n')
    (bin_dir / "roxy").write_text("#!/usr/bin/env bash\necho '[]'\n")
    for fake in (scripts / "launch", bin_dir / "roxy"):
        fake.chmod(0o755)
    monkeypatch.setattr(run_cell, "SCRIPTS", scripts)
    monkeypatch.setattr(run_cell, "REPO", tmp_path)  # its evidence goes to tmp_path/out
    return lambda: [shlex.split(line) for line in log.read_text().splitlines()]


def launch(cell: Cell) -> None:
    console = Console(iter(()), lambda: None)
    config = {"run_timeout_s": 0, "settle_s": 0}
    launch_once(Session("Den", cell, PROXY_BASE, console, config), "json-503")


def json_cell(**changes) -> Cell:
    return Cell("classic", "physical", "json", "json_get", "json-503", ["httpbin.org"], {"status": "200"}, **changes)


def test_a_cell_launches_its_case_in_the_labs_own_form_by_default(launches):
    launch(json_cell())
    assert launches() == [
        ["--scenario", "json-503", "--proxy-base", PROXY_BASE, "Den", "case=json_get", "separator=/"]
    ]


def test_a_cell_in_the_charles_style_form_launches_with_that_separator(launches):
    launch(json_cell(separator="/;"))
    assert launches()[0][-1] == "separator=/;"


def test_the_grid_option_picks_the_form_the_cell_runs_in(settings, capfd):
    """It stops before the Target Device: no lab answers. The cell line comes first."""
    with pytest.raises(SystemExit):
        main([*CELL, "--separator", "/;"])
    assert f"Proxy Base {PROXY_BASE}, separator /;)" in capfd.readouterr().out


def test_a_ca_routing_cell_has_no_prefixed_url_form_to_pick(settings, capfd):
    with pytest.raises(SystemExit):
        main(["classic", "physical", "json", "--ca-routing", "--separator", "/;"])
    assert "--separator is for Prefix Routing" in capfd.readouterr().err


def test_a_cell_runs_in_the_labs_own_form_unless_asked(settings, capfd):
    with pytest.raises(SystemExit):
        main(CELL)
    assert f"Proxy Base {PROXY_BASE}, separator /)" in capfd.readouterr().out
