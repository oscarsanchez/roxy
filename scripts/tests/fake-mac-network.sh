# Sourced by the tests that look up the Mac's LAN IP (scripts/lan-interface): fakes of the
# Mac's network commands, so a test never depends on the network this Mac is on.

# The warning roxy start and roxy setup give when a VPN holds the default route.
VPN_WARNING="warning: a VPN holds the default route: Rokus reach the lab only if it allows local LAN access (split tunnel); otherwise disconnect it while you use the lab"

# fake_mac_network DIR : writes route, networksetup and ipconfig into DIR, for DIR on PATH.
# networksetup lists the network services in this order: a VPN on utun4, Thunderbolt Bridge
# (bridge0), iPhone USB (en8), Bluetooth PAN (en6), an L2TP VPN (ppp0), USB 10/100/1000 LAN
# (en5), Wi-Fi (en0), and a VPN with no device.
# FAKE_MAC_ADDRESSES: each active interface and its IPv4 address, netmask 255.255.255.0
# (default "en0=192.0.2.10": Wi-Fi alone). FAKE_DEFAULT_ROUTE: the default route's
# interface (default en0).
fake_mac_network() {
  cat > "$1/route" <<'EOF'
#!/usr/bin/env bash
printf '   route to: default\ndestination: default\n  interface: %s\n' "${FAKE_DEFAULT_ROUTE:-en0}"
EOF
  cat > "$1/networksetup" <<'EOF'
#!/usr/bin/env bash
[ "$*" = -listnetworkserviceorder ] || { echo "fake networksetup: $*" >&2; exit 1; }
cat <<'ORDER'
An asterisk (*) denotes that a network service is disabled.
(1) Office VPN
(Hardware Port: IPSec, Device: utun4)

(2) Thunderbolt Bridge
(Hardware Port: Thunderbolt Bridge, Device: bridge0)

(3) iPhone USB
(Hardware Port: iPhone USB, Device: en8)

(4) Bluetooth PAN
(Hardware Port: Bluetooth PAN, Device: en6)

(5) Travel VPN
(Hardware Port: L2TP, Device: ppp0)

(6) USB 10/100/1000 LAN
(Hardware Port: USB 10/100/1000 LAN, Device: en5)

(7) Wi-Fi
(Hardware Port: Wi-Fi, Device: en0)

(8) Home VPN
(Hardware Port: com.example.vpn, Device: )

ORDER
EOF
  cat > "$1/ipconfig" <<'EOF'
#!/usr/bin/env bash
for entry in ${FAKE_MAC_ADDRESSES-en0=192.0.2.10}; do
  [ "${entry%%=*}" = "${2:-}" ] || continue
  case "$1 ${3:-}" in
    "getifaddr ") echo "${entry#*=}"; exit 0 ;;
    "getoption subnet_mask") echo 255.255.255.0; exit 0 ;;
  esac
done
exit 1
EOF
  chmod +x "$1/route" "$1/networksetup" "$1/ipconfig"
}
