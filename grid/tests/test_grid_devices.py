"""Which Target Device a cell runs on is the user's setting, not the repo's. Each run stops
before it touches a Target Device: no lab answers, or not this checkout's."""

import json

import pytest

from run_cell import main

CELL = ["classic", "physical", "json", "--proxy-base", "http://192.0.2.10:8080"]


def test_a_cell_runs_on_the_target_device_the_settings_name_for_its_kind(settings, capfd):
    (settings / "settings.json").write_text(
        json.dumps({"lan_subnets": ["192.0.2.0/24"], "grid_devices": {"physical": "Den"}})
    )
    (settings / "devices.json").write_text(json.dumps({"Den": {"ip": "192.0.2.77"}}))

    with pytest.raises(SystemExit):
        main(CELL)

    assert "(device Den," in capfd.readouterr().out


def test_a_missing_grid_device_setting_is_named(settings, capfd):
    (settings / "settings.json").write_text(json.dumps({"lan_subnets": ["192.0.2.0/24"]}))

    with pytest.raises(SystemExit):
        main(CELL)

    assert "grid_devices.physical" in capfd.readouterr().err
