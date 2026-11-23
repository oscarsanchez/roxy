"""The Settings Root: the user's Target Devices, the LAN subnets allowed to use the lab and
the secrets, as `roxy device` and `roxy setup` change them, and the Rokus on the LAN
`roxy device discover` could add. The one place that writes them:

    <settings root>/devices.json   {"<name>": {"ip": ...} | {"ip": ..., "kind": "proxied"}
                                              | {"rce_device_name": ..., "slug": ...}, ...}
    <settings root>/settings.json  {"lan_subnets": ["<CIDR>", ...], ...}
    <settings root>/secrets.env    NAME=value lines, which the lab's scripts source

Writes keep every key and entry they don't own (grid_devices, unknown keys); secrets.env
keeps its other lines and comments, and stays private to the user. A secret is never in
what a change says. The outside world comes in through ports passed to SettingsRoot: a
Roku's ECP device-info answer, `rce device resolve`, this Mac's address, the random
source, the SSDP search for Rokus, the tools on the PATH and `rce token status`;
ecp_device_info, rce_knows, this_mac, new_secret, ssdp_rokus, has_tool and rce_token_works,
below, are the real ones.
"""

import json
import os
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import time
from ipaddress import ip_address, ip_interface, ip_network
from pathlib import Path
from typing import NamedTuple
from xml.etree import ElementTree

# The examples roxy 0.2.0's install.sh seeded a settings root with: their values are no settings.
EXAMPLES = Path(__file__).resolve().parents[2] / "settings.example"
PHYSICAL_DEVICE = "Physical Device"
CLOUD_DEVICE = "Cloud Device"
PROXIED_DEVICE = "Proxied Device"
PROXIED_KINDS = ("proxied", "mobile")  # "mobile": as roxy 0.2.0 wrote it
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SSDP_GROUP = "239.255.255.250:1900"  # every SSDP device on the LAN; ROXY_SSDP_ADDRESS overrides it (tests)
SSDP_SECONDS = 3  # how long Rokus get to answer
NO_ROKU_FOUND = (
    "no Roku answered (a network can block discovery): a Roku shows its IP in"
    " Settings → Network → About; then roxy device add NAME --ip IP"
)
RCE_CLI ="https://github.com/oscarsanchez/rce-cli"  # the rce CLI, which the lab runs Cloud Devices through


class SettingsRootError(Exception):
    """A change to the Settings Root the lab refuses; the message says why, for the user."""


class DeviceExists(SettingsRootError):
    pass


class BadDevice(SettingsRootError):
    pass


class UnknownDevice(SettingsRootError):
    pass


class Device(NamedTuple):
    name: str
    kind: str  # PHYSICAL_DEVICE, CLOUD_DEVICE or PROXIED_DEVICE
    ip: str | None
    rce_device_name: str | None
    slug: str | None


class Change(NamedTuple):
    """What a change did beyond its own entry (notes), and what it found wrong but did anyway
    (warnings): a line each, for the user."""

    notes: list
    warnings: list


class SetupValues(NamedTuple):
    lan_subnets: list | None
    this_mac_only: str | None
    this_mac_network: str | None
    roku_user: str | None
    roku_password_set: bool


class FoundRoku(NamedTuple):
    """A Roku discover found: its own name, model and developer mode, from its ECP
    device-info (None each when it did not answer), and the Target Device with its IP."""

    ip: str
    name: str | None
    model: str | None
    developer_mode: bool | None
    registered_as: str | None

    @property
    def add_command(self):
        """The roxy device add line that registers it under its own name (NAME, for the user
        to fill in, when it did not say); None once registered."""
        if self.registered_as:
            return None
        return f"roxy device add {_double_quoted(self.name) if self.name else 'NAME'} --ip {self.ip}"


class SettingsRoot:
    def __init__(
        self, root, *, ecp_device_info, rce_knows, this_mac, new_secret, ssdp_rokus, has_tool, rce_token_works
    ):
        """ROOT is the settings root. The ports: ECP_DEVICE_INFO(ip), the Roku's device-info
        fields (None: it did not answer); RCE_KNOWS(rce_device_name), whether
        `rce device resolve` knows it; THIS_MAC(), this Mac's address and netmask (None: it
        is on no network); NEW_SECRET(), a new random secret; SSDP_ROKUS(), the IPs
        answering an SSDP search for roku:ecp on the LAN; HAS_TOOL(command), whether COMMAND
        is on the PATH; RCE_TOKEN_WORKS(), whether `rce token status` works."""
        self.devices_file = Path(root) / "devices.json"
        self.settings_file = Path(root) / "settings.json"
        self.secrets_file = Path(root) / "secrets.env"
        self.ecp_device_info = ecp_device_info
        self.rce_knows = rce_knows
        self.this_mac = this_mac
        self.new_secret = new_secret
        self.ssdp_rokus = ssdp_rokus
        self.has_tool = has_tool
        self.rce_token_works = rce_token_works

    def devices(self):
        """The registered Target Devices, in file order."""
        return [
            Device(name, _kind(entry), entry.get("ip"), entry.get("rce_device_name"), entry.get("slug"))
            for name, entry in self._read(self.devices_file).items()
        ]

    def add_device(self, name, ip, *, proxied=False):
        """Register the Roku NAME at IP (with PROXIED, the Proxied Device), allowing IP in
        lan_subnets if they don't cover it. A Roku that does not answer ECP, or is not in
        developer mode, is registered with a warning: it may merely be off today. Returns
        the Change."""
        registry = self._new_name(name)
        try:
            ip = str(ip_address(ip))
        except ValueError:
            raise BadDevice(f"not an IP address: {ip!r}") from None
        settings, notes = self._allowing(ip)
        registry[name] = {"ip": ip, "kind": "proxied"} if proxied else {"ip": ip}
        self._save(registry, settings)
        return Change(notes, [] if proxied else self._roku_warnings(name, ip))

    def add_cloud_device(self, name, rce_device_name, *, slug=None):
        """Register the Cloud Device NAME, rce's RCE_DEVICE_NAME, with SLUG in its Proxy Base
        (default: NAME lowercased, with dashes). A Device Name `rce device resolve` does not
        know is registered with a warning. Returns the Change."""
        registry = self._new_name(name)
        slug = slug or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not SLUG.fullmatch(slug):
            raise BadDevice(f"a slug is lowercase letters, digits and single dashes, not {slug!r}")
        taken = [other for other, entry in registry.items() if entry.get("slug") == slug]
        if taken:
            raise BadDevice(f"the slug {slug!r} is taken, by {taken[0]!r}")
        registry[name] = {"rce_device_name": rce_device_name, "slug": slug}
        self._save(registry, None)
        if self.rce_knows(rce_device_name):
            return Change([], [])
        return Change([], [
            f"rce device resolve does not know {rce_device_name!r}: registered anyway (rce device list shows the Device Names)"
        ])

    def remove_device(self, name):
        """Unregister the device NAME, dropping the /32 equal to its IP from lan_subnets when
        no other device has that IP; a broader entry is never touched. Returns the Change."""
        registry = self._read(self.devices_file)
        if name not in registry:
            raise UnknownDevice(f"unknown device {name!r} (roxy device list shows them)")
        ip = registry.pop(name).get("ip")
        shared = ip in (entry.get("ip") for entry in registry.values())
        settings, notes = self._disallowing(ip) if ip and not shared else (None, [])
        self._save(registry, settings)
        return Change(notes, [])

    def setup(self, *, trusted_network=None, roku_user=None, roku_password=None, cloud=False):
        """Fill the settings this Mac needs, keeping what is there: a new MITMWEB_PASSWORD
        when there is none; lan_subnets for the network this Mac is on, when there are
        none, they are the examples', or TRUSTED_NETWORK (True: the Mac's whole subnet;
        False: the Mac's /32) chooses; the Roku developer login, ROKU_USER (default: the
        examples') and ROKU_PASSWORD, each when given. A Roku password there is none of is
        a warning: only the user can give it. With CLOUD, for Cloud Devices too: a new
        LAB_SECRET when there is none. Returns the Change."""
        settings, notes, warnings = self._lan_setup(trusted_network)
        if settings is not None:
            _write(self.settings_file, settings)
        env = _read_env(self.secrets_file)
        changes = {}
        if not env.get("MITMWEB_PASSWORD"):
            changes["MITMWEB_PASSWORD"] = self.new_secret()
            notes.append(f"generated MITMWEB_PASSWORD (in {self.secrets_file}; the mitmweb UI asks for it)")
        else:
            notes.append("kept MITMWEB_PASSWORD")
        if roku_user or not env.get("ROKU_DEV_USER"):
            changes["ROKU_DEV_USER"] = roku_user or _example_roku_user()
            notes.append(f"ROKU_DEV_USER: {changes['ROKU_DEV_USER']}")
        else:
            notes.append(f"kept ROKU_DEV_USER: {env['ROKU_DEV_USER']}")
        if roku_password:
            changes["ROKU_DEV_PASSWORD"] = roku_password
            notes.append("set ROKU_DEV_PASSWORD")
        elif env.get("ROKU_DEV_PASSWORD"):
            notes.append("kept ROKU_DEV_PASSWORD")
        else:
            warnings.append(
                "no Roku developer password (ROKU_DEV_PASSWORD): the user runs roxy setup in a terminal, or pipes it to roxy setup"
            )
        if cloud and not env.get("LAB_SECRET"):
            changes["LAB_SECRET"] = self.new_secret()
            notes.append(f"generated LAB_SECRET (in {self.secrets_file}; the Public Endpoint's secret path segment)")
        elif cloud:
            notes.append("kept LAB_SECRET")
        _write_env(self.secrets_file, changes)
        if cloud:
            missing = self._cloud_tools_missing()
            warnings += missing
            if not missing:
                notes.append("rce and cloudflared installed, and rce token status works")
        return Change(notes, warnings)

    def _cloud_tools_missing(self):
        """A warning for each tool Cloud Devices need that is not installed, and for an RCE
        token rce does not take (asked only of an installed rce), with what installs it."""
        missing = []
        if not self.has_tool("rce"):
            missing.append(f"rce is not installed: install it as its README says, {RCE_CLI}")
        elif not self.rce_token_works():
            missing.append("rce token status fails: the user runs rce token set (pbpaste | rce token set)")
        if not self.has_tool("cloudflared"):
            missing.append("cloudflared is not installed: brew install cloudflared (the Public Endpoint is its tunnel)")
        return missing

    def setup_values(self):
        """What setup would keep, for a person to confirm or change: the lan_subnets (None:
        none, or the examples'), this Mac's /32 and its whole subnet (None: on no network),
        ROKU_DEV_USER (default: the examples') and whether there is a ROKU_DEV_PASSWORD.
        Never a secret."""
        settings, networks = self._lan_subnets()
        mac = self._mac()
        env = _read_env(self.secrets_file)
        return SetupValues(
            settings["lan_subnets"] if self._set_up(networks) else None,
            mac and str(ip_network(mac.ip)),
            mac and str(mac.network),
            env.get("ROKU_DEV_USER") or _example_roku_user(),
            bool(env.get("ROKU_DEV_PASSWORD")),
        )

    def _set_up(self, networks):
        """Whether the lan_subnets NETWORKS are the user's own: some, and none the examples'."""
        examples = [ip_network(subnet) for subnet in self._read(EXAMPLES / "settings.json")["lan_subnets"]]
        return bool(networks) and not set(networks) & set(examples)

    def _mac(self):
        """This Mac's address on its network, as an interface (None: on no network)."""
        mac = self.this_mac()
        return mac and ip_interface("/".join(mac))

    def _lan_setup(self, trusted_network):
        """settings.json with lan_subnets for this Mac (None: kept as they are), and the
        note and warnings saying so. The Mac's entry replaces them, keeping each registered
        device's /32 it does not cover."""
        settings, networks = self._lan_subnets()
        if trusted_network is None and self._set_up(networks):
            return None, [f"kept lan_subnets: {', '.join(settings['lan_subnets'])}"], []
        mac = self._mac()
        if mac is None:
            return None, [], ["could not find this Mac's address: lan_subnets left as they are"]
        entry = mac.network if trusted_network else ip_network(mac.ip)
        device_ips = {ip_address(device.ip) for device in self.devices() if device.ip}
        kept = [
            str(network)
            for network in networks
            if network.prefixlen == network.max_prefixlen
            and network[0] in device_ips
            and network[0] not in entry
        ]
        settings["lan_subnets"] = [str(entry), *kept]
        scope = "this Mac's network, trusted" if trusted_network else "this Mac only"
        return settings, [f"lan_subnets: {entry} ({scope})"], []

    def discover(self):
        """The Rokus on the LAN, in the order they answered the SSDP search. Changes nothing."""
        names = {entry.get("ip"): name for name, entry in self._read(self.devices_file).items()}
        return [_found(ip, self.ecp_device_info(ip) or {}, names.get(ip)) for ip in self.ssdp_rokus()]

    def add_found_rokus(self, name_for):
        """Offer each Roku discover finds that is not registered to NAME_FOR(found), which
        gives the name to register it under (None: skip it), and register it as add_device
        does. A name add_device refuses leaves that Roku unregistered, with a warning.
        Returns the Change of them all."""
        found = self.discover()
        if not found:
            return Change([NO_ROKU_FOUND], [])
        notes, warnings = [], []
        for roku in found:
            name = None if roku.registered_as else name_for(roku)
            if name is None:
                continue
            try:
                change = self.add_device(name, roku.ip)
            except (DeviceExists, BadDevice) as e:
                warnings.append(f"{roku.ip} not registered: {e}")
                continue
            notes += [f"registered {name!r} ({roku.ip})", *change.notes]
            warnings += change.warnings
        return Change(notes, warnings)

    def _save(self, registry, settings):
        """Write devices.json, then settings.json unless SETTINGS is None."""
        _write(self.devices_file, registry)
        if settings is not None:
            _write(self.settings_file, settings)

    def _roku_warnings(self, name, ip):
        info = self.ecp_device_info(ip)
        if info is None:
            return [f"{name} ({ip}) did not answer ECP: registered anyway (is it on, and on this network?)"]
        if info.get("developer-enabled") != "true":
            return [f"{name} ({ip}) is not in developer mode: registered anyway (deploy and launch need it)"]
        return []

    def _new_name(self, name):
        """The device registry, once NAME is known to be a new device name."""
        if not name.strip():
            raise BadDevice("a device needs a name")
        registry = self._read(self.devices_file)
        if name in registry:
            raise DeviceExists(f"the device {name!r} already exists (roxy device list shows them)")
        return registry

    def _allowing(self, ip):
        """settings.json with IP's /32 appended to lan_subnets, and the note saying so; (None,
        []) when an entry covers IP already."""
        settings, networks = self._lan_subnets()
        if any(ip_address(ip) in network for network in networks):
            return None, []
        network = str(ip_network(ip))
        settings["lan_subnets"] = [*settings.get("lan_subnets", []), network]
        return settings, [f"allowed {network} in lan_subnets"]

    def _disallowing(self, ip):
        """settings.json with the lan_subnets entry equal to IP's /32 dropped, and the note
        saying so; (None, []) when there is none."""
        settings, networks = self._lan_subnets()
        network = ip_network(ip)
        if network not in networks:
            return None, []
        settings["lan_subnets"] = [s for s, n in zip(settings["lan_subnets"], networks) if n != network]
        return settings, [f"dropped {network} from lan_subnets"]

    def _lan_subnets(self):
        """settings.json, and its lan_subnets as networks."""
        settings = self._read(self.settings_file)
        try:
            return settings, [ip_network(subnet, strict=False) for subnet in settings.get("lan_subnets", [])]
        except (TypeError, ValueError) as e:
            raise SettingsRootError(f"lan_subnets must be a list of CIDR subnets, in {self.settings_file}: {e}") from None

    @staticmethod
    def _read(file):
        """The JSON object FILE holds ({} when there is no FILE)."""
        try:
            doc = json.loads(file.read_text())
        except FileNotFoundError:
            return {}
        except ValueError as e:
            raise SettingsRootError(f"{file} is not JSON: {e}") from None
        if not isinstance(doc, dict):
            raise SettingsRootError(f"{file} must hold a JSON object")
        return doc


def ecp_device_info(ip):
    """The ECP device-info fields of the Roku at IP (developer-enabled, model-name, ...), or
    None if it does not answer. Through curl, as every lab script reaches ECP, and never
    through a proxy: the Mac's own may be the lab."""
    url = f"http://{ip}:8060/query/device-info"
    answer = subprocess.run(["curl", "-fsS", "--noproxy", "*", "--max-time", "3", url], capture_output=True, text=True)
    if answer.returncode:
        return None
    try:
        return {field.tag: field.text for field in ElementTree.fromstring(answer.stdout)}
    except ElementTree.ParseError:
        return None


def rce_knows(rce_device_name):
    """Whether `rce device resolve` knows RCE_DEVICE_NAME (False without rce on the PATH)."""
    try:
        return not subprocess.run(["rce", "device", "resolve", rce_device_name], capture_output=True).returncode
    except FileNotFoundError:
        return False


def has_tool(command):
    """Whether COMMAND is on the PATH."""
    return shutil.which(command) is not None


def rce_token_works():
    """Whether `rce token status` works: rce has a token RCE takes."""
    try:
        return not subprocess.run(["rce", "token", "status"], capture_output=True).returncode
    except FileNotFoundError:
        return False


def this_mac():
    """This Mac's address and netmask on its default-route interface, as `route` and
    `ipconfig` give them (lab scripts find the Mac's LAN IP the same way: lan_ip in
    scripts/lib.sh); None when it is on no network."""

    def run(*command):
        answer = subprocess.run(command, capture_output=True, text=True)
        return answer.stdout.strip() if not answer.returncode else ""

    interface = re.search(r"interface:\s*(\S+)", run("route", "-n", "get", "default"))
    address = interface and run("ipconfig", "getifaddr", interface[1])
    netmask = address and run("ipconfig", "getoption", interface[1], "subnet_mask")
    return (address, netmask) if netmask else None


def new_secret():
    """A new random secret, safe unquoted in a URL path and a shell."""
    return secrets.token_urlsafe(24)


def ssdp_rokus():
    """The IPs answering an SSDP search for roku:ecp, sent to the SSDP group (or
    ROXY_SSDP_ADDRESS, host:port), in the order they answered within SSDP_SECONDS. Each Roku
    on the LAN answers, unless the network drops multicast."""
    host, port = os.environ.get("ROXY_SSDP_ADDRESS", SSDP_GROUP).rsplit(":", 1)
    search = f'M-SEARCH * HTTP/1.1\r\nHost: {SSDP_GROUP}\r\nMan: "ssdp:discover"\r\nST: roku:ecp\r\n\r\n'
    found = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as search_socket:
        search_socket.sendto(search.encode(), (host, int(port)))
        deadline = time.monotonic() + SSDP_SECONDS
        while (left := deadline - time.monotonic()) > 0:
            search_socket.settimeout(left)
            try:
                answer, (ip, _) = search_socket.recvfrom(4096)
            except TimeoutError:
                break
            if b"roku:ecp" in answer.lower() and ip not in found:
                found.append(ip)
    return found


def _found(ip, info, registered_as):
    """The FoundRoku at IP, from its device-info fields INFO ({}: it did not answer)."""
    developer = info.get("developer-enabled")
    return FoundRoku(
        ip,
        info.get("user-device-name") or info.get("friendly-device-name"),
        info.get("model-name"),
        None if developer is None else developer == "true",
        registered_as,
    )


def _double_quoted(text):
    """TEXT as one shell word in double quotes, as a person would type a device name."""
    return '"' + re.sub(r'([\\"$`])', r"\\\1", text) + '"'


def _kind(entry):
    """A devices.json entry's kind of Target Device."""
    if "rce_device_name" in entry:
        return CLOUD_DEVICE
    return PROXIED_DEVICE if entry.get("kind") in PROXIED_KINDS else PHYSICAL_DEVICE


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _write(file, doc):
    """Write DOC to FILE, one top-level entry per line, as the examples are laid out: whole
    or not at all (through a temp file beside it)."""
    lines = [f"  {_json(key)}: {_json(value)}" for key, value in doc.items()]
    file.parent.mkdir(parents=True, exist_ok=True)
    draft = file.with_name(f".{file.name}.tmp")
    draft.write_text("{\n" + ",\n".join(lines) + "\n}\n" if lines else "{}\n")
    draft.replace(file)


def _example_roku_user():
    """The Roku developer web server's user the examples give, every Roku's own default."""
    return _read_env(EXAMPLES / "secrets.env")["ROKU_DEV_USER"]


ENV_LINE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)")


def _read_env(file):
    """The NAME=value lines of the env FILE, each value as bash reads it ({} when there is
    no FILE)."""
    try:
        lines = file.read_text().splitlines()
    except FileNotFoundError:
        return {}
    env = {}
    for line in lines:
        match = ENV_LINE.fullmatch(line.strip())
        if match:
            try:
                env[match[1]] = "".join(shlex.split(match[2], comments=True))
            except ValueError:
                env[match[1]] = match[2]
    return env


def _write_env(file, changes):
    """Write each of CHANGES' values into the env FILE, over its NAME=value line, else
    appended; every other line and comment kept. Private to the user (0600), and whole or
    not at all (through a temp file beside it)."""
    try:
        lines = file.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    todo = dict(changes)
    for i, line in enumerate(lines):
        match = ENV_LINE.fullmatch(line.strip())
        if match and match[1] in todo:
            lines[i] = f"{match[1]}={shlex.quote(todo.pop(match[1]))}"
    lines += [f"{name}={shlex.quote(value)}" for name, value in todo.items()]
    file.parent.mkdir(parents=True, exist_ok=True)
    draft = file.with_name(f".{file.name}.tmp")
    draft.unlink(missing_ok=True)
    with os.fdopen(os.open(draft, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
        out.write("".join(f"{line}\n" for line in lines))
    draft.replace(file)
