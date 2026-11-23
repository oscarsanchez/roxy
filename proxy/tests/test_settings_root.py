"""The Settings Root module: the Target Devices, lan_subnets and secrets in the user's settings
root, as `roxy device add`, `list` and `remove` and `roxy setup` change them. Against the temp
settings root (conftest's `settings`, seeded from the examples: lan_subnets 192.0.2.0/24), with
a Roku's ECP answer, `rce device resolve`, this Mac's address and the random source faked."""

import itertools
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
def mac():
    """This Mac's address and netmask, as mac[0]; None: it is on no network."""
    return [("198.51.100.23", "255.255.255.0")]


@pytest.fixture
def ports(ecp, rce, mac):
    """SettingsRoot's ports, faked; new_secret gives secret-1, secret-2, ..."""
    secrets = (f"secret-{n}" for n in itertools.count(1))
    return {
        "ecp_device_info": ecp.get,
        "rce_knows": rce.__contains__,
        "this_mac": lambda: mac[0],
        "new_secret": lambda: next(secrets),
    }


@pytest.fixture
def root(settings, ports):
    return SettingsRoot(settings, **ports)


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


def test_add_into_a_settings_root_without_its_files_creates_them(tmp_path, ports):
    empty = tmp_path / "empty-root"
    root = SettingsRoot(empty, **ports)

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


# roxy setup: the secrets and lan_subnets for this Mac (faked: 198.51.100.23, netmask
# 255.255.255.0), keeping what is there and replacing the examples' values.

SECRET_NAMES = ("MITMWEB_PASSWORD", "LAB_SECRET", "ROKU_DEV_USER", "ROKU_DEV_PASSWORD")


def secrets_env(settings):
    """secrets.env as bash reads it (the lab sources it): each secret's value."""
    script = '. "$1"; printf "%s\\0" ' + " ".join(f'"${name}"' for name in SECRET_NAMES)
    out = subprocess.run(["bash", "-c", script, "-", settings / "secrets.env"], capture_output=True, text=True, check=True)
    return dict(zip(SECRET_NAMES, out.stdout.split("\0")))


def said(change):
    """Everything a Change says, as one text."""
    return "\n".join(change.notes + change.warnings)


def test_setup_generates_the_mitmweb_password_into_a_private_file_and_never_says_it(root, settings):
    change = root.setup()

    assert secrets_env(settings)["MITMWEB_PASSWORD"] == "secret-1"
    assert (settings / "secrets.env").stat().st_mode & 0o777 == 0o600
    assert "secret-1" not in said(change)
    assert "generated MITMWEB_PASSWORD" in said(change)


def test_setup_keeps_the_other_lines_and_comments_of_secrets_env(root, settings):
    before = (settings / "secrets.env").read_text().splitlines()

    root.setup()

    after = (settings / "secrets.env").read_text().splitlines()
    assert [line for line in after if not line.startswith("MITMWEB_PASSWORD=")] == [
        line for line in before if not line.startswith("MITMWEB_PASSWORD=")
    ]


def test_a_rerun_keeps_the_mitmweb_password(root, settings):
    root.setup()

    change = root.setup()

    assert secrets_env(settings)["MITMWEB_PASSWORD"] == "secret-1"
    assert "kept MITMWEB_PASSWORD" in said(change)


def test_setup_into_a_settings_root_without_secrets_env_creates_it_private(tmp_path, ports):
    empty = tmp_path / "empty-root"

    SettingsRoot(empty, **ports).setup()

    assert secrets_env(empty)["MITMWEB_PASSWORD"] == "secret-1"
    assert (empty / "secrets.env").stat().st_mode & 0o777 == 0o600


def test_setup_allows_only_this_mac_by_default_in_place_of_the_examples_subnet(root, settings):
    change = root.setup()

    assert settings_file(settings)["lan_subnets"] == ["198.51.100.23/32"]
    assert settings_file(settings)["grid_devices"]["physical"] == "Living Room"
    assert "lan_subnets: 198.51.100.23/32 (this Mac only)" in change.notes


def test_setup_on_a_trusted_network_allows_this_macs_whole_subnet(root, settings):
    change = root.setup(trusted_network=True)

    assert settings_file(settings)["lan_subnets"] == ["198.51.100.0/24"]
    assert "lan_subnets: 198.51.100.0/24 (this Mac's network, trusted)" in change.notes


def test_a_rerun_keeps_the_lan_subnets_there_are(root, settings, mac):
    root.setup(trusted_network=True)
    mac[0] = ("203.0.113.5", "255.255.255.0")

    change = root.setup()

    assert settings_file(settings)["lan_subnets"] == ["198.51.100.0/24"]
    assert "kept lan_subnets: 198.51.100.0/24" in change.notes


def test_setup_replaces_the_examples_subnet_keeping_each_devices_32_beside_it(root, settings):
    root.add_device("Den", "203.0.113.9")

    root.setup()

    assert settings_file(settings)["lan_subnets"] == ["198.51.100.23/32", "203.0.113.9/32"]


def test_a_network_choice_replaces_lan_subnets_keeping_each_devices_32(root, settings):
    root.setup(trusted_network=True)
    root.add_device("Den", "203.0.113.9")

    root.setup(trusted_network=False)

    assert settings_file(settings)["lan_subnets"] == ["198.51.100.23/32", "203.0.113.9/32"]


def test_setup_off_any_network_leaves_lan_subnets_and_warns(root, settings, mac):
    mac[0] = None
    before = settings_file(settings)

    change = root.setup()

    assert settings_file(settings) == before
    assert "could not find this Mac's address: lan_subnets left as they are" in change.warnings
