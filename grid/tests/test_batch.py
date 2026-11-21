"""scripts/grid fills several cells in one call: each of flavour, Target Device kind and
traffic class takes a comma list or `all`, and --separator takes / , /; or both. The cells
run in a fixed order: Physical Device cells first, then by flavour, separator and class."""

import tomllib

import pytest

from run_cell import GRID, parse_args

CONFIG = tomllib.loads((GRID / "cells.toml").read_text())


def cells(*argv: str) -> list[tuple[str, str, str, str]]:
    return [(c.device_kind, c.flavour, c.separator, c.traffic_class) for c in parse_args(list(argv), CONFIG).cells]


def test_single_values_make_one_cell():
    assert cells("classic", "physical", "json") == [("physical", "classic", "/", "json")]


def test_comma_lists_run_in_the_fixed_order_whatever_order_they_are_given_in():
    assert cells("rsg,classic", "cloud,physical", "hls,json", "--separator", "/;,/") == [
        ("physical", "classic", "/", "json"),
        ("physical", "classic", "/", "hls"),
        ("physical", "classic", "/;", "json"),
        ("physical", "classic", "/;", "hls"),
        ("physical", "rsg", "/", "json"),
        ("physical", "rsg", "/", "hls"),
        ("physical", "rsg", "/;", "json"),
        ("physical", "rsg", "/;", "hls"),
        ("cloud", "classic", "/", "json"),
        ("cloud", "classic", "/", "hls"),
        ("cloud", "classic", "/;", "json"),
        ("cloud", "classic", "/;", "hls"),
        ("cloud", "rsg", "/", "json"),
        ("cloud", "rsg", "/", "hls"),
        ("cloud", "rsg", "/;", "json"),
        ("cloud", "rsg", "/;", "hls"),
    ]


def test_all_takes_every_value_in_the_order_of_cells_toml():
    assert cells("all", "all", "all") == [
        (kind, flavour, "/", traffic_class)
        for kind in ("physical", "cloud")
        for flavour in ("classic", "rsg")
        for traffic_class in ("json", "json_post", "image", "hls", "dash", "widevine", "raf", "raf_vmap")
    ]


def test_a_value_given_twice_makes_its_cells_once():
    assert cells("classic,classic", "physical", "json") == [("physical", "classic", "/", "json")]


def test_an_unknown_value_is_named(capsys):
    with pytest.raises(SystemExit):
        parse_args(["classic,tvos", "physical", "json"], CONFIG)
    assert "tvos" in capsys.readouterr().err


def test_ca_routing_takes_physical_devices_only(capsys):
    with pytest.raises(SystemExit):
        parse_args(["classic", "physical,cloud", "json", "--ca-routing"], CONFIG)
    assert "CA Routing is for Physical Devices only" in capsys.readouterr().err


def test_a_ca_routing_batch_has_ca_routing_cells():
    batch = parse_args(["all", "physical", "image", "--ca-routing"], CONFIG)
    assert [c.ca_routing for c in batch.cells] == [True, True]
