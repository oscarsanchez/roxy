# Mobile Devices

How a Product App's iOS or Android debug build reaches the lab: the Mobile Device sets the lab as its HTTP proxy and trusts the lab's certificate authority. This is Proxy Routing. Vocabulary: [GLOSSARY.md](../GLOSSARY.md).

```
Mobile Device --HTTP proxy 192.0.2.10:8090--> Mac (mitmweb, certificate signed by the lab's CA) --> the real Origin
```

The flows keep their Origin URLs: there is no Proxy Base and no Prefixed URL, so the app needs no change beyond trusting the CA. They show in mitmweb and `roxy flows --json` next to your Roku's, and the active Scenarios act on them.

The addresses in this guide are documentation examples: Mac `192.0.2.10`, LAN `192.0.2.0/24`. Use your own.

For an iOS Simulator or Android Emulator on the Mac that runs the lab, see [iOS Simulator and Android Emulator on this Mac](#ios-simulator-and-android-emulator-on-this-mac).

## Before you start

- The Mobile Device and the Mac are on the same LAN, and that LAN is in `lan_subnets` in your `settings.json` ([Settings](settings.md)). A client outside it is refused `client-ip`.
- The app is a debug build of your Product App. Store builds are out of scope, and so is an app that pins its certificates: it refuses the lab's.
- The lab is running. `roxy start` (or `roxy status`, from another terminal) prints the address to use:
  ```
  Proxy Routing:     192.0.2.10:8090  (a Mobile Device's HTTP proxy)
  ```
  The Proxy Routing listener runs whenever the lab does, on port 8090 (`LAB_PROXY_ROUTING_PORT` in `scripts/lib.sh`), with no flag.

Check it from the Mac first, no Mobile Device needed:

```sh
curl -x http://192.0.2.10:8090 http://httpbin.org/json             # httpbin's JSON
curl -x http://192.0.2.10:8090 --cacert ~/.mitmproxy/mitmproxy-ca-cert.pem https://httpbin.org/json
roxy flows --json --limit 2                                         # both, as https://httpbin.org/json and http://...
```

## 1. Set the lab as the HTTP proxy

On the Mobile Device, in the Wi-Fi network's settings, set a manual HTTP proxy: server `192.0.2.10`, port `8090`, no authentication.

- **iOS and iPadOS**: Settings → Wi-Fi → ⓘ next to the network → Configure Proxy → Manual.
- **Android**: Settings → Network & internet → Internet → ⚙ next to the network → ✎ (Edit) → Advanced options → Proxy → Manual. The menu names vary by vendor.

The proxy setting is per Wi-Fi network: it stays until you turn it off, and the Mobile Device loses its connection whenever the lab is not running. Set it back to Off when you are done.

## 2. Install and trust the lab's CA

The lab signs a certificate for every HTTPS Origin with its own CA, the same one CA Routing uses (`~/.mitmproxy/mitmproxy-ca-cert.pem`, made by the lab's first start). With the proxy set, open `http://mitm.it` in the Mobile Device's browser: the lab answers it itself and offers the CA for each platform. A page saying traffic is not passing through mitmproxy means the proxy is not set.

### iOS and iPadOS

1. In Safari, open `http://mitm.it` and tap the iOS certificate. Allow the download of the configuration profile.
2. Settings → General → VPN & Device Management → the mitmproxy profile → Install.
3. Settings → General → About → Certificate Trust Settings → turn on full trust for mitmproxy. Without this step the profile is installed but no HTTPS request is trusted.

### Android

1. In Chrome, open `http://mitm.it` and tap the Android certificate.
2. Install it as a CA certificate: Settings → Security → Encryption & credentials → Install a certificate → CA certificate (or open the downloaded file). The menu names vary by vendor and Android version.
3. Since Android 7, apps ignore CAs the user installed unless they opt in, so the debug build must trust them. In its network security config (`res/xml/network_security_config.xml`, named by `android:networkSecurityConfig` in the manifest), add the user CAs for debug builds only:
   ```xml
   <network-security-config>
     <debug-overrides>
       <trust-anchors>
         <certificates src="user" />
       </trust-anchors>
     </debug-overrides>
   </network-security-config>
   ```
   `debug-overrides` applies only when the build is debuggable, so release builds keep the system CAs alone.

## 3. See its flows

Open the app. Its requests show in mitmweb (`http://127.0.0.1:8081`) and in `roxy flows --json` under their Origin URLs, HTTP and HTTPS alike, with every follow-up request (images, segments, beacons) as the app sends it.

To tell them from your Roku's, register the Mobile Device by its IP in your `devices.json` ([Settings](settings.md)), with `"kind": "mobile"`:

```json
"Phone": {"ip": "192.0.2.60", "kind": "mobile"}
```

Restart the lab: its flows are then named `Phone` in mitmweb's comment column (filter `~comment "Phone"`) and in `device` in `roxy flows --json`. A Mobile Device is no Roku: `scripts/deploy`, `roxy launch` and `roxy console` refuse it.

- **Scenarios** act on them as on any flow: filter on the Origin (`~d api.example.com`) to reach both your Roku's and the Mobile Device's requests. A rule with `{proxy_base}` placeholders leaves them alone, as they have no Proxy Base ([Scenarios](scenarios.md)).
- **No rewriting**: the lab never rewrites URLs in their headers or bodies; the app sees each response as the Origin sent it.
- **Throttle**: a Mobile Device's HTTPS flows are usually HTTP/2, which a `throttle` rule leaves unpaced (the mitmweb event log says so); plain HTTP flows are paced. A `latency` rule slows both ([Scenarios](scenarios.md)).
- **Guards**: the LAN's. The client must be on `lan_subnets`, a private Origin is refused `origin-address`, and any public Origin is allowed: the Origin allowlist is the Public Endpoint's only ([Guards](guards.md)).
- **Native only**: the listener is never reachable through the Public Endpoint, and Docker Compose does not publish it ([Docker Compose](compose.md)).

## iOS Simulator and Android Emulator on this Mac

An iOS Simulator or Android Emulator on the Mac that runs the lab reaches the Proxy Routing listener from loopback, `127.0.0.1:8090`. The lab allows loopback on this listener only (the 8080 and 8888 listeners still refuse it `client-ip`), and names its flows `This Mac`, with no `devices.json` entry and no `lan_subnets` change.

### iOS Simulator

The iOS Simulator has no proxy setting of its own: it uses the Mac's.

1. Set the Mac's web proxies to the lab: System Settings → Network → the active service (Wi-Fi) → Details → Proxies → turn on Web proxy (HTTP) and Secure web proxy (HTTPS), each with server `127.0.0.1`, port `8090`. Or from a terminal:
   ```sh
   networksetup -setwebproxy Wi-Fi 127.0.0.1 8090
   networksetup -setsecurewebproxy Wi-Fi 127.0.0.1 8090
   ```
   Add `127.0.0.1` and `localhost` to "Bypass proxy settings for these hosts & domains" (macOS's default list holds only `*.local` and `169.254/16`), so mitmweb and `roxy` reach the lab directly: through the proxy they would be refused `origin-address`, which `roxy` reports as a wrong password. From a terminal:
   ```sh
   networksetup -setproxybypassdomains Wi-Fi '*.local' 169.254/16 127.0.0.1 localhost
   ```
2. Trust the lab's CA in the booted iOS Simulator:
   ```sh
   xcrun simctl keychain booted add-root-cert ~/.mitmproxy/mitmproxy-ca-cert.pem
   ```
   Or open `http://mitm.it` in its Safari and follow the iOS steps above, full trust included.

Every app on the Mac now goes through the lab, and its flows are named `This Mac` too. Turn the proxies off when you are done (`networksetup -setwebproxystate Wi-Fi off` and `-setsecurewebproxystate Wi-Fi off`): with the lab stopped, the Mac has no web access through them.

### Android Emulator

1. Start the Android Emulator with the lab as its HTTP proxy (the Android SDK at Android Studio's default location):
   ```sh
   ~/Library/Android/sdk/emulator/emulator -avd <avd-name> -http-proxy 127.0.0.1:8090
   ```
   Or, while it runs: Extended controls (⋯) → Settings → Proxy → Manual proxy configuration, host `127.0.0.1`, port `8090` → Apply. `127.0.0.1` here is the Mac: the Android Emulator itself makes the proxy connection.
2. Install and trust the lab's CA as on an Android device (step 2, Android, above): open `http://mitm.it` in its Chrome, install the CA certificate, and let the debug build trust user CAs.
