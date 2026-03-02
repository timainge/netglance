# IPv6 Network Audit

## What it does

The `ipv6` command suite analyzes your IPv6 configuration and checks for network security concerns. It discovers IPv6 neighbors on your network via NDP (Neighbor Discovery Protocol), identifies your local IPv6 addresses and their types, detects whether privacy extensions are enabled, and checks for potential IPv6 DNS leaks when a VPN is active.

IPv6 deployment varies widely—some networks have full dual-stack support while others don't provide IPv6 at all. This tool helps you understand your IPv6 posture and spot configuration issues like MAC address exposure or privacy vulnerabilities.

## Quick start

Check your full IPv6 configuration:
```bash
netglance ipv6 audit
```

List only your local IPv6 addresses:
```bash
netglance ipv6 addresses
```

Discover IPv6 neighbors on your network (requires sudo):
```bash
sudo netglance ipv6 neighbors
```

## Commands

### `netglance ipv6 audit`

Runs a complete IPv6 audit: scans for neighbors, lists your local addresses, checks privacy extension status, and tests for DNS leaks if a VPN is detected.

**Options:**
- `--interface, -i <interface>` — Specify a network interface for neighbor discovery (e.g., `en0`, `eth0`). If not provided, uses the default interface.
- `--json` — Output results as JSON instead of formatted tables.

**Example:**
```bash
netglance ipv6 audit --interface en0
netglance ipv6 audit --json
```

**Output includes:**
- **Neighbors table** — IPv6 addresses discovered on the network, their MAC addresses, classification (link-local, global, etc.), and interface.
- **Local Addresses table** — Your system's IPv6 addresses with their classification.
- **Summary panel** — High-level status for dual-stack, privacy extensions, EUI-64 exposure, and DNS leak detection.

### `netglance ipv6 addresses`

Shows all IPv6 addresses configured on your system, classified by type. Also displays privacy extension status and EUI-64 MAC exposure in a summary.

**Options:**
- `--json` — Output as JSON.

**Example:**
```bash
netglance ipv6 addresses
netglance ipv6 addresses --json
```

**Output:**
- **Local IPv6 Addresses table** — Interface name, IPv6 address, and type classification.
- **Privacy Status panel** — Whether privacy extensions are detected (temporary addresses) and whether EUI-64-derived addresses are exposed.

### `netglance ipv6 neighbors`

Discovers IPv6 neighbors on your local network by sending ICMPv6 Neighbor Solicitation messages. **Requires root or sudo.**

**Options:**
- `--interface, -i <interface>` — Specify a network interface (default: auto-detect).
- `--timeout, -t <seconds>` — Time to wait for responses (default: 5 seconds).
- `--json` — Output as JSON.

**Example:**
```bash
sudo netglance ipv6 neighbors
sudo netglance ipv6 neighbors --interface en0 --timeout 10
```

## Understanding the output

### IPv6 Address Types

Each IPv6 address is classified into one of these types:

- **link-local** — Address in the `fe80::/10` range, used only on the local link. These addresses always exist but are not routable beyond your LAN.
- **global** — Public, globally routable unicast address (typically `2000::/3`). Indicates ISP-provided IPv6.
- **eui64** — Global address derived from your MAC address using IEEE EUI-64. The pattern `ff:fe` appears in the address. These can leak your hardware MAC if monitored.
- **temporary** — Global address with a random host ID (no EUI-64 pattern). Used for privacy; typically expires and is replaced. Modern operating systems use these by default.
- **unique-local** — Private address in the `fc00::/7` range, similar to IPv4 RFC 1918 ranges. Used on internal networks without Internet routing.
- **multicast** — Addresses starting with `ff::`; used for group communication.
- **loopback** — The `::1` address, only for local communication.

### Privacy Status

- **Privacy extensions: enabled** — Your system has temporary IPv6 addresses in use. This is good; your MAC address is not exposed.
- **Privacy extensions: not detected** — Only EUI-64 or link-local addresses are present. Your MAC may be identifiable.
- **EUI-64 addresses: not exposed** — No EUI-64-derived global addresses detected; privacy is good.
- **EUI-64 addresses: exposed** — Your system uses EUI-64 global addresses. Your MAC address can be inferred from the address.

### Dual-Stack

- **Dual-Stack Active: YES** — Your system has both IPv4 and IPv6 global addresses. Services can reach you over either protocol.
- **Dual-Stack Active: NO** — Either IPv4 or IPv6 is unavailable or not globally routable.

### IPv6 DNS Leak

This check only runs if a VPN is detected:

- **IPv6 DNS Leak: N/A (no VPN)** — No VPN interface found; test is skipped.
- **IPv6 DNS Leak: No leak** — VPN is active, but IPv6 DNS queries are properly isolated.
- **IPv6 DNS Leak: LEAK DETECTED** — VPN is active, but IPv6 DNS queries can escape to the ISP's DNS or other external resolvers, bypassing the VPN tunnel.

## Related concepts

- **[IPv6 Primer](../../guide/concepts/ipv6-primer.md)** — Background on IPv6 addressing, NDP, and privacy extensions.
- **[VPN Tool](./vpn.md)** — Comprehensive VPN testing including IPv6 leak detection.
- **[Firewall Tool](./firewall.md)** — Check firewall rules for IPv6 traffic.

## Troubleshooting

### "No IPv6 addresses found on this system"

Your network does not provide IPv6, or your system has not been assigned one:

- Check with your ISP whether they support IPv6.
- On macOS, verify in System Settings > Network > Wi-Fi > Details > TCP/IP to see if an IPv6 address is shown.
- On Linux, run `ip -6 addr show` to confirm.

### "No IPv6 neighbors discovered"

The neighbor discovery command requires elevated privileges and uses raw sockets:

- Run `sudo netglance ipv6 neighbors` instead of the non-elevated version.
- If still no results, check whether IPv6 is enabled on the interface: `ip -6 route show` or `netstat -rn | grep inet6` (Linux).
- Router may not be advertising IPv6 prefixes; check router settings or contact ISP.

### "EUI-64 addresses exposed"

Your system is using your MAC address in IPv6 addresses, making your hardware identifiable:

- **On macOS:** System Preferences > Network > Wi-Fi > Advanced > TCP/IP > Configure IPv6 > set to "Automatic" (or check for privacy address support).
- **On Linux:** Run `sysctl net.ipv6.conf.all.use_tempaddr=2` (1 or 2 enables privacy extensions).
- Once enabled, the system will generate temporary addresses for new connections.

### "IPv6 DNS leak detected"

Your VPN does not isolate IPv6 DNS queries:

- Reconfigure your VPN client to explicitly block IPv6 traffic, or use IPv6 blocking rules in your firewall.
- Some VPNs have an option to "disable IPv6" to prevent leaks; check your VPN settings.
- Consider using a VPN that fully supports IPv6-in-IPv6 tunneling or forces IPv6 queries over the VPN interface.
