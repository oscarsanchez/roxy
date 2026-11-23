"""The Settings Root: the user's Target Devices and the LAN subnets allowed to use the lab,
as `roxy device` changes them, and the Rokus on the LAN it could add. The one place that
writes them:

    <settings root>/devices.json   {"<name>": {"ip": ...} | {"ip": ..., "kind": "proxied"}
                                              | {"rce_device_name": ..., "slug": ...}, ...}
    <settings root>/settings.json  {"lan_subnets": ["<CIDR>", ...], ...}

Writes keep every key and entry they don't own (grid_devices, unknown keys). The outside
world comes in through ports passed to SettingsRoot: a Roku's ECP device-info answer,
`rce device resolve` and the SSDP search for Rokus; ecp_device_info, rce_knows and
ssdp_rokus, below, are the real ones.
"""

import json
import os
import re
import socket
import subprocess
import time
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import NamedTuple
from xml.etree import ElementTree

PHYSICAL_DEVICE = "Physical Device"
CLOUD_DEVICE = "Cloud Device"
PROXIED_DEVICE = "Proxied Device"
PROXIED_KINDS = ("proxied", "mobile")  # "mobile": as roxy 0.2.0 wrote it
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SSDP_GROUP = "239.255.255.250:1900"  # every SSDP device on the LAN; ROXY_SSDP_ADDRESS overrides it (tests)
SSDP_SECONDS = 3  # how long Rokus get to answer


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
    def __init__(self, root, *, ecp_device_info, rce_knows, ssdp_rokus):
        """ROOT is the settings root. The ports: ECP_DEVICE_INFO(ip), the Roku's device-info
        fields (None: it did not answer); RCE_KNOWS(rce_device_name), whether
        `rce device resolve` knows it; SSDP_ROKUS(), the IPs answering an SSDP search for
        roku:ecp on the LAN."""
        self.devices_file = Path(root) / "devices.json"
        self.settings_file = Path(root) / "settings.json"
        self.ecp_device_info = ecp_device_info
        self.rce_knows = rce_knows
        self.ssdp_rokus = ssdp_rokus

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

    def discover(self):
        """The Rokus on the LAN, in the order they answered the SSDP search. Changes nothing."""
        names = {entry.get("ip"): name for name, entry in self._read(self.devices_file).items()}
        return [_found(ip, self.ecp_device_info(ip) or {}, names.get(ip)) for ip in self.ssdp_rokus()]

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
