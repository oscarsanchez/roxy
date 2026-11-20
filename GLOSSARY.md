# roxy

A lab for inspecting and manipulating the network traffic that a Roku app sends and receives, on both real Roku hardware and Roku's cloud-hosted emulator.

## Targets

**Lab App**:
A disposable Roku app built only to exercise traffic through the lab; exists in a classic BrightScript/SceneGraph flavour and an RSG 2.0 SDK flavour. Third-party and store apps are out of scope.
_Avoid_: test channel, sample app, client

**Product App**:
A Roku app you develop, run as a dev-mode sideloaded build that has opted in to the lab. Its store and production builds are out of scope.
_Avoid_: real app, my app, customer app

**Physical Device**:
A real Roku player or TV on the same Wi-Fi network as the lab.
_Avoid_: box, hardware, real device

**Cloud Device**:
A virtual Roku player or TV running in Roku Cloud Emulator (RCE), reachable only over the public internet.
_Avoid_: emulator, RCE instance, simulator

**Target Device**:
Either a Physical Device or a Cloud Device: whatever is running the Lab App or Product App right now.
_Avoid_: device (unqualified), Roku

## Traffic

**Outbound Traffic**:
Every request a Lab App or Product App causes to leave the Target Device, and its response: API calls, images, manifests, segments, DRM licenses, ad requests and beacons.
_Avoid_: network calls, requests (unqualified)

**Origin**:
The real server a request was meant for before the lab got in the way.
_Avoid_: upstream, backend, target server

**Prefix Routing**:
Getting Outbound Traffic to the lab by having a Lab App or Product App use Prefixed URLs; works for every Target Device.
_Avoid_: URL rewriting, reverse mode

**CA Routing**:
Getting Outbound Traffic to the lab by having DNS point Origins at the lab while a Lab App or Product App trusts the lab's certificate authority; Physical Devices only.
_Avoid_: DNS mode, custom CA mode, transparent mode

**Proxy Base**:
The address of the lab that a Lab App or Product App puts in front of an Origin URL; differs per Target Device kind (LAN address for a Physical Device, Public Endpoint plus secret segment and device slug for a Cloud Device).
_Avoid_: proxy URL, proxy host, prefix

**Prefixed URL**:
An Origin URL with the Proxy Base in front of it, joined by `/` or, in the Charles convention, `/;`, so the request reaches the lab and the lab can recover the Origin from the path.
_Avoid_: proxied URL, wrapped URL, rewritten URL

**Public Endpoint**:
The internet-reachable hostname that lets Cloud Devices reach the lab; never exposes the lab's own UI.
_Avoid_: tunnel URL, ngrok URL

**Inspection**:
Seeing Outbound Traffic as it happens, without changing it.
_Avoid_: sniffing, capture, monitoring

**Manipulation**:
Changing Outbound Traffic in flight: mocked or rewritten responses, injected faults or latency, edited manifests, held-and-edited requests, and replayed recordings.
_Avoid_: tampering, mocking (unqualified)

**Scenario**:
A named set of Manipulation rules. Any number of Scenarios can be active at once, in an order you choose; their rules apply in that order, for every Target Device the lab serves.
_Avoid_: mock set, rule file

**App Profile**:
What the lab keeps for one Product App, in your own lab settings and outside every repo: its repo location, the Origins it may reach through the Public Endpoint, its Scenarios and their mocks. Optional; at most one is loaded per Lab Session.
_Avoid_: app config, app settings

**Lab Session**:
One run of the lab, from the moment it starts until it stops. It loads at most one App Profile and has an ordered set of active Scenarios (possibly none); switching App Profile means a new Lab Session.
_Avoid_: lab instance, proxy session
