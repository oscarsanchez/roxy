"""The Settings Root module: the Target Devices and lan_subnets in the user's settings root,
as `roxy device add`, `list` and `remove` change them and `roxy device discover` finds
Rokus. Against the temp settings root (conftest's `settings`, seeded from the examples:
lan_subnets 192.0.2.0/24), with a Roku's ECP answer, `rce device resolve` and the SSDP
search faked."""

import json
import subprocess

import pytest

from lab.settings_root import BadDevice, DeviceExists, SettingsRoot, SettingsRootError, UnknownDevice

DEVELOPER_MODE = {"user-device-name": "Den", "model-name": "Roku Ultra", "developer-enabled": "true"}


@pytest.fixture
def ecp():
    """Each IP's ECP device-info answer; an IP missing from it does not answer."""
    return {}


@pytest.fixture
def rce():
    """The rce Device Names `rce device resolve` knows."""
    return set()


@pytest.fixture
def ssdp():
    """The IPs answering the SSDP search for roku:ecp, in the order they answered."""
    return []


@pytest.fixture
def root(settings, ecp, rce, ssdp):
    return SettingsRoot(settings, ecp_device_info=ecp.get, rce_knows=rce.__contains__, ssdp_rokus=lambda: ssdp)


def devices_file(settings):
    return json.loads((settings / "devices.json").read_text())


def test_add_registers_a_roku_by_its_ip_and_list_shows_it(root, settings, ecp):
    ecp["192.0.2.70"] = DEVELOPER_MODE

    root.add_device("Den", "192.0.2.70")

    assert devices_file(settings)["Den"] == {"ip": "192.0.2.70"}
    assert ("Den", "Physical Device", "192.0.2.70") in [(d.name, d.kind, d.ip) for d in root.devices()]


def settings_file(settings):
    return json.loads((settings / "settings.json").read_text())


def test_add_allows_an_uncovered_ip_in_lan_subnets_as_a_32_and_says_so(root, settings):
    change = root.add_device("Den", "198.51.100.7")

    assert settings_file(settings)["lan_subnets"] == ["192.0.2.0/24", "198.51.100.7/32"]
    assert "allowed 198.51.100.7/32 in lan_subnets" in change.notes


def test_add_leaves_lan_subnets_alone_for_an_ip_they_cover(root, settings):
    before = (settings / "settings.json").read_text()

    change = root.add_device("Den", "192.0.2.70")

    assert (settings / "settings.json").read_text() == before
    assert not [line for line in change.notes if "lan_subnets" in line]


def test_a_roku_that_does_not_answer_ecp_is_registered_with_a_warning(root, settings):
    change = root.add_device("Den", "192.0.2.70")

    assert devices_file(settings)["Den"] == {"ip": "192.0.2.70"}
    assert change.warnings == ["Den (192.0.2.70) did not answer ECP: registered anyway (is it on, and on this network?)"]


def test_a_roku_not_in_developer_mode_is_registered_with_a_warning(root, settings, ecp):
    ecp["192.0.2.70"] = {**DEVELOPER_MODE, "developer-enabled": "false"}

    change = root.add_device("Den", "192.0.2.70")

    assert devices_file(settings)["Den"] == {"ip": "192.0.2.70"}
    assert change.warnings == ["Den (192.0.2.70) is not in developer mode: registered anyway (deploy and launch need it)"]


def test_a_roku_in_developer_mode_is_registered_without_a_warning(root, ecp):
    ecp["192.0.2.70"] = DEVELOPER_MODE

    assert root.add_device("Den", "192.0.2.70").warnings == []


def test_add_keeps_the_other_devices_and_the_settings_it_does_not_own(root, settings):
    (settings / "settings.json").write_text(
        '{"lan_subnets": ["192.0.2.0/24"], "grid_devices": {"physical": "Living Room"}, "later": 1}'
    )
    before = devices_file(settings)

    root.add_device("Den", "198.51.100.7")

    assert devices_file(settings) == {**before, "Den": {"ip": "198.51.100.7"}}
    assert settings_file(settings) == {
        "lan_subnets": ["192.0.2.0/24", "198.51.100.7/32"],
        "grid_devices": {"physical": "Living Room"},
        "later": 1,
    }


@pytest.mark.parametrize("name, refusal", [("Living Room", DeviceExists), ("", BadDevice), ("  ", BadDevice)])
def test_add_refuses_a_name_that_exists_or_is_blank(root, settings, name, refusal):
    before = devices_file(settings)

    with pytest.raises(refusal):
        root.add_device(name, "192.0.2.70")

    assert devices_file(settings) == before


@pytest.mark.parametrize("ip", ["192.0.2", "192.0.2.300", "192.0.2.0/24", "den.local"])
def test_add_refuses_an_invalid_ip(root, settings, ip):
    before = devices_file(settings), settings_file(settings)

    with pytest.raises(BadDevice, match="IP"):
        root.add_device("Den", ip)

    assert (devices_file(settings), settings_file(settings)) == before


def test_a_proxied_device_is_registered_as_kind_proxied_without_asking_ecp(root, settings):
    change = root.add_device("Tablet", "198.51.100.8", proxied=True)

    assert devices_file(settings)["Tablet"] == {"ip": "198.51.100.8", "kind": "proxied"}
    assert change == (["allowed 198.51.100.8/32 in lan_subnets"], [])
    assert ("Tablet", "Proxied Device", "198.51.100.8") in [(d.name, d.kind, d.ip) for d in root.devices()]


def test_list_shows_a_device_of_kind_mobile_as_0_2_0_wrote_it_as_a_proxied_device(root, settings):
    (settings / "devices.json").write_text('{"Old Phone": {"ip": "192.0.2.61", "kind": "mobile"}}')

    assert [(d.name, d.kind) for d in root.devices()] == [("Old Phone", "Proxied Device")]


def test_a_cloud_device_is_registered_with_a_slug_made_from_its_name(root, settings, rce):
    rce.add("office-player")
    before = settings_file(settings)

    change = root.add_cloud_device("Office  Stick 2", "office-player")

    assert devices_file(settings)["Office  Stick 2"] == {"rce_device_name": "office-player", "slug": "office-stick-2"}
    assert change == ([], [])
    assert settings_file(settings) == before
    listed = {d.name: d for d in root.devices()}["Office  Stick 2"]
    assert (listed.kind, listed.rce_device_name, listed.slug) == ("Cloud Device", "office-player", "office-stick-2")


def test_a_cloud_device_takes_the_slug_it_is_given(root, settings):
    root.add_cloud_device("Office", "office-player", slug="desk-2")

    assert devices_file(settings)["Office"]["slug"] == "desk-2"


def test_a_cloud_device_rce_does_not_know_is_registered_with_a_warning(root, settings):
    change = root.add_cloud_device("Office", "office-player")

    assert devices_file(settings)["Office"] == {"rce_device_name": "office-player", "slug": "office"}
    assert change.warnings == [
        "rce device resolve does not know 'office-player': registered anyway (rce device list shows the Device Names)"
    ]


@pytest.mark.parametrize(
    "name, slug, refusal",
    [
        ("Office", "cloud-device", "the slug 'cloud-device' is taken, by 'Cloud Device'"),
        ("Office", "Desk 2", "a slug is lowercase letters, digits and single dashes"),
        ("Office", "-desk", "a slug is lowercase letters, digits and single dashes"),
        ("★", None, "a slug is lowercase letters, digits and single dashes"),
        ("Cloud Device", None, "already exists"),
    ],
)
def test_a_cloud_device_needs_a_new_name_and_a_free_valid_slug(root, settings, name, slug, refusal):
    before = devices_file(settings)

    with pytest.raises(SettingsRootError, match=refusal):
        root.add_cloud_device(name, "office-player", slug=slug)

    assert devices_file(settings) == before


def test_remove_drops_the_device_and_the_32_that_allowed_it(root, settings):
    root.add_device("Den", "198.51.100.7")
    before = devices_file(settings)

    change = root.remove_device("Den")

    assert devices_file(settings) == {name: entry for name, entry in before.items() if name != "Den"}
    assert settings_file(settings)["lan_subnets"] == ["192.0.2.0/24"]
    assert change == (["dropped 198.51.100.7/32 from lan_subnets"], [])


def test_remove_keeps_a_32_another_device_still_has(root, settings):
    root.add_device("Den", "198.51.100.7")
    root.add_device("Den Phone", "198.51.100.7", proxied=True)

    change = root.remove_device("Den")

    assert settings_file(settings)["lan_subnets"] == ["192.0.2.0/24", "198.51.100.7/32"]
    assert change == ([], [])


def test_remove_never_touches_a_broader_entry(root, settings):
    (settings / "settings.json").write_text('{"lan_subnets": ["192.0.2.54/31", "192.0.2.0/24"], "grid_devices": {}}')

    root.remove_device("Living Room")

    assert settings_file(settings) == {"lan_subnets": ["192.0.2.54/31", "192.0.2.0/24"], "grid_devices": {}}


def test_remove_of_a_cloud_device_leaves_lan_subnets_alone(root, settings):
    before = settings_file(settings)

    assert root.remove_device("Cloud Device") == ([], [])

    assert "Cloud Device" not in devices_file(settings)
    assert settings_file(settings) == before


def test_remove_refuses_an_unknown_name(root, settings):
    before = devices_file(settings)

    with pytest.raises(UnknownDevice, match="Den"):
        root.remove_device("Den")

    assert devices_file(settings) == before


def test_add_into_a_settings_root_without_its_files_creates_them(tmp_path, ecp, rce):
    empty = tmp_path / "empty-root"
    root = SettingsRoot(empty, ecp_device_info=ecp.get, rce_knows=rce.__contains__, ssdp_rokus=list)

    root.add_device("Den", "198.51.100.7")

    assert devices_file(empty) == {"Den": {"ip": "198.51.100.7"}}
    assert settings_file(empty) == {"lan_subnets": ["198.51.100.7/32"]}
    assert [d.name for d in root.devices()] == ["Den"]


def test_a_settings_file_that_is_not_json_is_refused_naming_it(root, settings):
    (settings / "devices.json").write_text('{"Den": ')

    with pytest.raises(SettingsRootError, match="devices.json"):
        root.add_device("Office", "192.0.2.71")

    assert (settings / "devices.json").read_text() == '{"Den": '


def test_a_lan_subnets_entry_that_is_no_subnet_is_refused_changing_nothing(root, settings):
    (settings / "settings.json").write_text('{"lan_subnets": ["my LAN"]}')
    before = devices_file(settings)

    with pytest.raises(SettingsRootError, match="lan_subnets"):
        root.add_device("Den", "198.51.100.7")

    assert devices_file(settings) == before
    assert settings_file(settings) == {"lan_subnets": ["my LAN"]}


def test_discover_lists_each_roku_that_answers_with_its_own_name_model_and_developer_mode(root, ssdp, ecp):
    ssdp += ["198.51.100.7", "192.0.2.54"]
    ecp["198.51.100.7"] = DEVELOPER_MODE
    ecp["192.0.2.54"] = {"friendly-device-name": "Roku Express - X1", "model-name": "Roku Express", "developer-enabled": "false"}

    found = root.discover()

    assert [(r.ip, r.name, r.model, r.developer_mode) for r in found] == [
        ("198.51.100.7", "Den", "Roku Ultra", True),
        ("192.0.2.54", "Roku Express - X1", "Roku Express", False),
    ]


def test_discover_marks_a_registered_roku_by_its_device_name_and_gives_the_others_an_add_line(root, ssdp, ecp):
    ssdp += ["192.0.2.54", "198.51.100.7"]
    ecp["192.0.2.54"] = {**DEVELOPER_MODE, "user-device-name": "Lounge"}
    ecp["198.51.100.7"] = DEVELOPER_MODE

    found = root.discover()

    assert [(r.registered_as, r.add_command) for r in found] == [
        ("Living Room", None),
        (None, 'roxy device add "Den" --ip 198.51.100.7'),
    ]


def test_an_add_line_gives_the_shell_the_rokus_own_name_whatever_it_holds(root, ssdp, ecp):
    name = 'Kid\'s 55" TV $HOME `x` \\'
    ssdp.append("198.51.100.7")
    ecp["198.51.100.7"] = {**DEVELOPER_MODE, "user-device-name": name}

    [found] = root.discover()

    typed = subprocess.run(
        ["bash", "-c", f"roxy() {{ printf '%s\\n' \"$@\"; }}; {found.add_command}"], capture_output=True, text=True
    )
    assert typed.stdout.splitlines() == ["device", "add", name, "--ip", "198.51.100.7"]


def test_a_roku_that_answers_the_search_but_not_ecp_is_listed_with_an_add_line_to_name_it(root, ssdp):
    ssdp.append("198.51.100.7")

    [found] = root.discover()

    assert found == ("198.51.100.7", None, None, None, None)
    assert found.add_command == "roxy device add NAME --ip 198.51.100.7"


def test_discover_with_no_roku_answering_finds_none(root):
    assert root.discover() == []
