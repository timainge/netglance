# VPN Tool

## What it does

The `vpn` subcommand detects active VPN connections on your system and tests for three types of leaks that indicate your VPN may not be protecting your traffic:

- **DNS leaks**: DNS queries being resolved outside the VPN tunnel
- **IPv6 leaks**: IPv6 traffic bypassing the VPN entirely
- **Split tunneling**: Some traffic routed through the VPN and some not, even intentionally

VPN leaks are serious security issues—they expose your IP address, location, or browsing activity even when you believe the VPN is protecting you.

## Quick start

Run a full VPN check to see if your VPN is active and detect any leaks:

```bash
netglance vpn check
```

Check for DNS leaks only:

```bash
netglance vpn dns
```

Check if IPv6 traffic is leaking:

```bash
netglance vpn ipv6
```

Show which VPN interface is currently active (if any):

```bash
netglance vpn status
```

Get results as JSON:

```bash
netglance vpn check --json
```

## Commands

### `vpn check`

Run all VPN leak detection tests in one command.

```bash
netglance vpn check [--json]
```

**Options:**
- `--json` — Output the report as JSON instead of a formatted panel

**Output example:**
- Shows whether a VPN tunnel interface is detected (e.g., `utun1`, `wg0`, `tun0`)
- Reports DNS leak status and any outside resolver IPs
- Reports IPv6 leak status and exposed IPv6 addresses
- Reports split-tunnel detection
- Uses color coding: green for secure, red for leaks detected, yellow for no VPN active

### `vpn dns`

Test specifically for DNS leaks.

```bash
netglance vpn dns [--json]
```

**Options:**
- `--json` — Output as JSON with format `{"dns_leak": boolean, "resolvers": [ips]}`

**How it works:**
1. Queries a known hostname via your system resolver
2. Compares the answering resolver IPs to Google's known IPs (8.8.8.8, 8.8.4.4, 2001:4860:4860::8888, 2001:4860:4860::8844)
3. Any non-Google IPs indicate queries are leaking to a resolver outside the VPN

### `vpn ipv6`

Test specifically for IPv6 leaks.

```bash
netglance vpn ipv6 [--json]
```

**Options:**
- `--json` — Output as JSON with format `{"ipv6_leak": boolean, "addresses": [ipv6_addrs]}`

**How it works:**
1. Scans all network interfaces for global IPv6 addresses
2. If a VPN is active but a non-VPN interface has a global IPv6 address, that traffic can bypass the tunnel
3. Link-local and loopback addresses are ignored (safe)

### `vpn status`

Show the active VPN interface (if one exists).

```bash
netglance vpn status [--json]
```

**Options:**
- `--json` — Output as JSON with format `{"vpn_detected": boolean, "vpn_interface": "string"}`

**Output example:**
```
VPN active — interface: utun1
```

Recognized VPN interface patterns:
- `utun*` — macOS/iOS standard tunnel (most VPN clients)
- `tun*` — Linux TUN device
- `wg*` — WireGuard
- `ppp*` — PPP, PPTP, L2TP
- `tap*` — TAP device
- `nordlynx*` — NordVPN WireGuard
- `proton0*` — ProtonVPN

## Understanding the output

### VPN Interface status

- **Active (utun1)** — A VPN tunnel interface is detected and online
- **Not detected** — No VPN tunnel interface found on the system

### DNS Leak

- **No leak** — All DNS queries are being answered by Google's resolvers (expected when a properly configured VPN is protecting your DNS)
- **Leak detected** — Some queries are being answered by resolvers outside the VPN. The IPs shown are the outside resolvers (your ISP, or other public DNS services)

**What it means:** If DNS is leaking, an observer can see which domains you visit even with the VPN active.

### IPv6 Leak

- **No leak** — No global IPv6 addresses found on non-VPN interfaces
- **Leak detected** — Your system has a global IPv6 address that is not on the VPN interface. The addresses shown are your exposed IPv6 addresses.

**What it means:** If you have both IPv4 (protected) and IPv6 (unprotected), websites can contact your IPv6 address directly, bypassing the VPN.

### Split Tunnel

- **Not detected** — All traffic is being routed through the VPN (expected)
- **Detected** — Some traffic is being routed outside the VPN. This may be intentional (many VPN apps offer a split-tunnel feature to exclude certain apps), or it may indicate misconfiguration.

**What it means:** Split-tunneled traffic is not protected by the VPN and can expose your real IP to those destinations.

## Related concepts

- [VPN Fundamentals](../../guide/concepts/vpn-fundamentals.md) — How VPNs work, what leaks mean, and common attack scenarios
- [DNS Tool](dns.md) — General DNS health and configuration

## Troubleshooting

### WireGuard shows as active but DNS still leaks

This is a common misconfiguration. WireGuard does not automatically change your DNS settings—you must configure your system or VPN client to use a DNS server inside the tunnel (or a hardened resolver). Check your VPN client's DNS settings.

### macOS reports `utun` interface but I don't recognize it

macOS uses `utun*` for all tunnel interfaces (VPN, local tunnels, etc.). If you're unsure whether it's your VPN:
1. Disable your VPN and run `netglance vpn status` again
2. The interface should disappear if it was your VPN
3. If it persists, it may be a system tunnel (like Proxy or VPN profiles you forgot about)

### IPv6 leak detected but I don't use IPv6

If you want to completely block IPv6 leaks, disable IPv6 at the OS level (most home networks don't use it). Many VPN providers have a "block IPv6" option in their client settings.

### Split tunneling detected but I didn't enable it

Some VPN clients enable split tunneling by default for local network access (to reach your printer, NAS, etc.). Check your VPN client settings under "Split Tunneling" or "Local Network Access" and disable if not needed.

### Checks fail with "timeout" or "connection error"

The VPN check requires internet access to query public DNS and test routes. If you're running behind a proxy or firewall:
1. Verify the VPN is actually connected
2. Try running `netglance vpn status` (interface check) in isolation—it doesn't need internet
3. For DNS/IPv6/split-tunnel tests, ensure your firewall allows outbound DNS and ICMP probes
