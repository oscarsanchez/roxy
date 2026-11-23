"""The Settings Root module: the Target Devices, lan_subnets and secrets in the user's settings
root, as `roxy device add`, `list` and `remove` and `roxy setup` change them, and the Rokus
`roxy device discover` finds. Against the temp settings root (conftest's `settings`, seeded from
the examples: lan_subnets 192.0.2.0/24), with a Roku's ECP answer, `rce device resolve`, this
Mac's address, the random source, the SSDP search, the tools on the PATH and
`rce token status` faked; this Mac's address itself (this_mac) against the Mac's network commands
faked."""

import itertools
import json
import os
import subprocess
from ipaddress import ip_interface
from pathlib import Path

import pytest

from lab.settings_root import BadDevice, DeviceExists, SettingsRoot, SettingsRootError, UnknownDevice, this_mac

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
    """This Mac's address on its network, as mac[0]; None: it is on no network."""
    return [ip_interface("10.0.0.23/24")]


@pytest.fixture
def ssdp():
    """The IPs answering the SSDP search for roku:ecp, in the order they answered."""
    return []


@pytest.fixture
def on_path():
    """The tools Cloud Devices need that are on the PATH."""
    return {"rce", "cloudflared"}


@pytest.fixture
def rce_token():
    """Whether `rce token status` works, as rce_token[0]."""
    return [True]


@pytest.fixture
def ports(ecp, rce, mac, ssdp, on_path, rce_token):
    """SettingsRoot's ports, faked; new_secret gives secret-1, secret-2, ..."""
    secrets = (f"secret-{n}" for n in itertools.count(1))
    return {
        "ecp_device_info": ecp.get,
        "rce_knows": rce.__contains__,
        "this_mac": lambda: mac[0],
        "new_secret": lambda: next(secrets),
        "has_tool": on_path.__contains__,
        "rce_token_works": lambda: rce_token[0],
        "ssdp_rokus": lambda: ssdp,
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


def test_add_of_a_name_registered_at_another_ip_says_where_and_how_to_move_it(root, settings):
    before = devices_file(settings)

    with pytest.raises(DeviceExists) as refused:
        root.add_device("Living Room", "192.0.2.70")

    assert str(refused.value) == (
        "the device 'Living Room' is registered at 192.0.2.54: roxy device remove \"Living Room\" first,"
        " then add it at 192.0.2.70"
    )
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


def private(file):
    return file.stat().st_mode & 0o777 == 0o600


def test_every_settings_file_a_change_writes_is_private_to_the_user(tmp_path, ports):
    empty = tmp_path / "empty-root"
    root = SettingsRoot(empty, **ports)

    root.add_device("Den", "198.51.100.7")
    assert private(empty / "devices.json") and private(empty / "settings.json")
    root.remove_device("Den")
    assert private(empty / "devices.json") and private(empty / "settings.json")
    root.setup()
    assert all(private(empty / name) for name in ("devices.json", "settings.json", "secrets.env"))


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


# roxy setup: the secrets and lan_subnets for this Mac (faked: 10.0.0.23/24), keeping what
# is there and replacing the examples' values.

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

    assert settings_file(settings)["lan_subnets"] == ["10.0.0.23/32"]
    assert settings_file(settings)["grid_devices"]["physical"] == "Living Room"
    assert "lan_subnets: 10.0.0.23/32 (this Mac only)" in change.notes


def test_setup_on_a_trusted_network_allows_this_macs_whole_subnet(root, settings):
    change = root.setup(trusted_network=True)

    assert settings_file(settings)["lan_subnets"] == ["10.0.0.0/24"]
    assert "lan_subnets: 10.0.0.0/24 (this Mac's network, trusted)" in change.notes


def test_a_rerun_keeps_the_lan_subnets_there_are(root, settings, mac):
    root.setup(trusted_network=True)
    mac[0] = ip_interface("10.2.0.5/24")

    change = root.setup()

    assert settings_file(settings)["lan_subnets"] == ["10.0.0.0/24"]
    assert "kept lan_subnets: 10.0.0.0/24" in change.notes


def test_setup_replaces_the_examples_subnet_keeping_each_devices_32_beside_it(root, settings):
    root.add_device("Den", "10.1.0.9")

    root.setup()

    assert settings_file(settings)["lan_subnets"] == ["10.0.0.23/32", "10.1.0.9/32"]


def test_a_network_choice_replaces_lan_subnets_keeping_each_devices_32(root, settings):
    root.setup(trusted_network=True)
    root.add_device("Den", "10.1.0.9")

    root.setup(trusted_network=False)

    assert settings_file(settings)["lan_subnets"] == ["10.0.0.23/32", "10.1.0.9/32"]


def test_setup_removes_the_examples_devices_and_says_so(root, settings):
    root.add_device("Den", "10.1.0.9")

    change = root.setup()

    assert devices_file(settings) == {"Den": {"ip": "10.1.0.9"}}
    assert {
        "removed the example device 'Living Room'",
        "removed the example device 'Cloud Device'",
        "removed the example device 'Phone'",
    } <= set(change.notes)


def test_a_device_on_a_documentation_range_or_the_examples_cloud_device_is_an_example(root, settings):
    (settings / "devices.json").write_text(
        json.dumps({
            "Den": {"ip": "203.0.113.9"},
            "Kids": {"ip": "198.51.100.7", "kind": "proxied"},
            "Player": {"rce_device_name": "player", "slug": "cloud-device"},
            "Office": {"ip": "10.1.0.9"},
            "Stick": {"rce_device_name": "office-player", "slug": "stick"},
        })
    )

    root.setup()

    assert list(devices_file(settings)) == ["Office", "Stick"]


def test_a_rerun_with_nothing_left_of_the_examples_keeps_the_devices(root, settings):
    root.setup()
    root.add_device("Den", "10.1.0.9")
    before = (settings / "devices.json").read_text()

    change = root.setup()

    assert (settings / "devices.json").read_text() == before
    assert not [note for note in change.notes if "example" in note]


@pytest.mark.parametrize("subnet", ["203.0.113.0/25", "198.51.100.7/32", "192.0.2.0/24"])
def test_a_lan_subnets_entry_inside_a_documentation_range_is_an_example(root, settings, subnet):
    (settings / "settings.json").write_text(json.dumps({"lan_subnets": ["10.0.0.0/24", subnet]}))

    root.setup()

    assert settings_file(settings)["lan_subnets"] == ["10.0.0.23/32"]


def test_setup_off_any_network_leaves_lan_subnets_and_warns(root, settings, mac):
    mac[0] = None
    before = settings_file(settings)

    change = root.setup()

    assert settings_file(settings) == before
    assert "could not find this Mac's address: lan_subnets left as they are" in change.warnings


def test_setup_takes_the_roku_developer_login_and_never_says_the_password(root, settings):
    password = "p a$s'w\"rd"

    change = root.setup(roku_user="dev", roku_password=password)

    assert (secrets_env(settings)["ROKU_DEV_USER"], secrets_env(settings)["ROKU_DEV_PASSWORD"]) == ("dev", password)
    assert password not in said(change)
    assert {"ROKU_DEV_USER: dev", "set ROKU_DEV_PASSWORD"} <= set(change.notes)


def test_setup_without_a_roku_password_hands_that_step_to_the_user(root, settings):
    change = root.setup()

    assert secrets_env(settings)["ROKU_DEV_PASSWORD"] == ""
    assert change.warnings == [
        "no Roku developer password (ROKU_DEV_PASSWORD): the user runs roxy setup in a terminal, or pipes it to roxy setup"
    ]


def test_a_rerun_keeps_the_roku_login(root, settings):
    root.setup(roku_user="dev", roku_password="first")

    change = root.setup()

    assert (secrets_env(settings)["ROKU_DEV_USER"], secrets_env(settings)["ROKU_DEV_PASSWORD"]) == ("dev", "first")
    assert {"kept ROKU_DEV_USER: dev", "kept ROKU_DEV_PASSWORD"} <= set(change.notes)
    assert change.warnings == []


def test_setup_gives_the_roku_user_its_default_when_there_is_none(root, settings):
    (settings / "secrets.env").write_text("MITMWEB_PASSWORD=\n")

    root.setup()

    assert secrets_env(settings)["ROKU_DEV_USER"] == "rokudev"


def test_setup_for_cloud_devices_generates_the_lab_secret_and_never_says_it(root, settings):
    change = root.setup(cloud=True)

    assert secrets_env(settings)["LAB_SECRET"] == "secret-2"
    assert "secret-2" not in said(change)
    assert "generated LAB_SECRET" in said(change)


def test_a_rerun_for_cloud_devices_keeps_the_lab_secret(root, settings):
    root.setup(cloud=True)

    change = root.setup(cloud=True)

    assert secrets_env(settings)["LAB_SECRET"] == "secret-2"
    assert "kept LAB_SECRET" in change.notes


CLOUDFLARED_MISSING = "cloudflared is not installed: brew install cloudflared (the Public Endpoint is its tunnel)"
RCE_MISSING = "rce is not installed: install it as its README says, https://github.com/oscarsanchez/rce-cli"
RCE_TOKEN_FAILS = "rce token status fails: the user runs rce token set (pbpaste | rce token set)"


@pytest.mark.parametrize(
    "missing, warnings",
    [
        ({"cloudflared"}, [CLOUDFLARED_MISSING]),
        ({"rce token"}, [RCE_TOKEN_FAILS]),
        ({"rce", "rce token"}, [RCE_MISSING]),
        ({"rce", "rce token", "cloudflared"}, [RCE_MISSING, CLOUDFLARED_MISSING]),
    ],
)
def test_setup_for_cloud_devices_warns_of_each_missing_tool_or_token_and_still_sets_up(
    root, settings, on_path, rce_token, missing, warnings
):
    on_path -= missing
    rce_token[0] = "rce token" not in missing
    root.setup(roku_password="first")

    change = root.setup(cloud=True)

    assert change.warnings == warnings
    assert secrets_env(settings)["LAB_SECRET"] == "secret-2"


def test_setup_for_cloud_devices_says_their_tools_and_token_are_there(root):
    change = root.setup(cloud=True)

    assert "rce and cloudflared installed, and rce token status works" in change.notes


def test_setup_without_cloud_devices_says_nothing_of_them(root, settings, on_path, rce_token):
    on_path.clear()
    rce_token[0] = False

    change = root.setup()

    assert secrets_env(settings)["LAB_SECRET"] == ""
    assert not [line for line in change.notes + change.warnings if any(w in line for w in ("LAB_SECRET", "rce", "cloudflared"))]


def test_the_values_setup_would_keep_show_no_secret_and_no_example(root, settings):
    assert root.setup_values() == (None, "10.0.0.23/32", "10.0.0.0/24", "rokudev", False)

    root.setup(roku_password="first")

    values = root.setup_values()
    assert values == (["10.0.0.23/32"], "10.0.0.23/32", "10.0.0.0/24", "rokudev", True)
    assert "first" not in repr(values)


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


# roxy setup in a terminal offers each Roku discover finds that is not registered: the person
# names it (its own name by default) or skips it (None).


def test_setup_offers_each_unregistered_roku_found_and_registers_it_as_device_add_does(root, settings, ssdp, ecp):
    ssdp += ["192.0.2.54", "198.51.100.7", "198.51.100.8"]
    ecp["192.0.2.54"] = {**DEVELOPER_MODE, "user-device-name": "Lounge"}
    ecp["198.51.100.7"] = DEVELOPER_MODE
    offered = []

    def name_for(found):
        offered.append((found.ip, found.name))
        return found.name

    change = root.add_found_rokus(name_for)

    assert offered == [("198.51.100.7", "Den"), ("198.51.100.8", None)]
    assert devices_file(settings)["Den"] == {"ip": "198.51.100.7"}
    assert "198.51.100.8" not in [d.ip for d in root.devices()]
    assert settings_file(settings)["lan_subnets"] == ["192.0.2.0/24", "198.51.100.7/32"]
    assert change == (["registered 'Den' (198.51.100.7)", "allowed 198.51.100.7/32 in lan_subnets"], [])


def test_a_roku_found_is_registered_under_the_name_given_with_device_adds_warnings(root, settings, ssdp, ecp):
    ssdp.append("198.51.100.7")
    ecp["198.51.100.7"] = {**DEVELOPER_MODE, "developer-enabled": "false"}

    change = root.add_found_rokus(lambda found: "Kids")

    assert devices_file(settings)["Kids"] == {"ip": "198.51.100.7"}
    assert change.warnings == ["Kids (198.51.100.7) is not in developer mode: registered anyway (deploy and launch need it)"]


def test_a_roku_found_under_a_name_that_exists_is_left_with_a_warning_and_the_next_is_offered(root, settings, ssdp):
    ssdp += ["198.51.100.7", "198.51.100.8"]

    change = root.add_found_rokus(lambda found: {"198.51.100.7": "Living Room", "198.51.100.8": "Kids"}[found.ip])

    assert devices_file(settings)["Living Room"] == {"ip": "192.0.2.54"}
    assert devices_file(settings)["Kids"] == {"ip": "198.51.100.8"}
    assert change.warnings[0] == (
        "198.51.100.7 not registered: the device 'Living Room' is registered at 192.0.2.54:"
        ' roxy device remove "Living Room" first, then add it at 198.51.100.7'
    )


def test_setup_with_no_roku_answering_says_where_to_read_a_rokus_ip(root):
    change = root.add_found_rokus(lambda found: pytest.fail("nothing to offer"))

    assert change == (
        [
            "no Roku answered (a network can block discovery): a Roku shows its IP in"
            " Settings → Network → About; then roxy device add NAME --ip IP"
        ],
        [],
    )


@pytest.fixture
def mac_network(tmp_path, monkeypatch):
    """The Mac's network commands, faked on the PATH (scripts/tests/fake-mac-network.sh): the
    services in the order VPN (utun4), Thunderbolt Bridge (bridge0), USB LAN (en5), Wi-Fi (en0)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = Path(__file__).resolve().parents[2] / "scripts" / "tests" / "fake-mac-network.sh"
    subprocess.run(["bash", "-c", '. "$1"; fake_mac_network "$2"', "-", fake, bin_dir], check=True)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return monkeypatch


def test_this_mac_is_its_wi_fi_address_past_a_vpn_holding_the_default_route(mac_network):
    mac_network.setenv("FAKE_DEFAULT_ROUTE", "utun4")
    mac_network.setenv("FAKE_MAC_ADDRESSES", "utun4=203.0.113.5 bridge0=203.0.113.6 en0=192.0.2.10")

    assert this_mac() == ip_interface("192.0.2.10/24")


def test_this_mac_with_ethernet_and_wi_fi_up_is_the_first_in_the_service_order(mac_network):
    mac_network.setenv("FAKE_MAC_ADDRESSES", "en0=192.0.2.10 en5=192.0.2.20")

    assert this_mac() == ip_interface("192.0.2.20/24")


def test_this_mac_with_only_a_vpn_up_is_on_no_network(mac_network):
    mac_network.setenv("FAKE_DEFAULT_ROUTE", "utun4")
    mac_network.setenv("FAKE_MAC_ADDRESSES", "utun4=203.0.113.5")

    assert this_mac() is None
