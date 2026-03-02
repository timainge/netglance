# Firewall

Test your firewall rules by probing outbound (egress) and inbound (ingress) ports to discover which services can connect in and out of your network.

## What it does

The firewall tool audits your network's port access policies:

- **Egress testing** — Checks which outbound ports your network allows. Useful for detecting restrictive corporate/ISP policies or verifying intentional blocking rules.
- **Ingress testing** — Checks which inbound ports are reachable from the internet. Helps discover unintended exposure or verify that sensitive ports are properly shielded.
- **Common port profiles** — Tests standard ports used by web, email, SSH, DNS, and other services without requiring manual port selection.
- **Actionable recommendations** — Flags security concerns like open SMTP relays or unexpected internet-facing ports.

## Quick start

Test common egress ports (SSH, SMTP, DNS, HTTP, HTTPS, etc.):

```bash
netglance firewall egress
```

Check a specific outbound port (e.g., port 3000):

```bash
netglance firewall egress --port 3000
```

Test an inbound port for internet reachability (e.g., HTTP):

```bash
netglance firewall ingress --port 80
```

Run a full firewall audit (egress + ingress common ports):

```bash
netglance firewall audit
```

Get results as JSON:

```bash
netglance firewall egress --json
```

## Commands

### `audit`

Full firewall assessment covering common egress ports and generating security recommendations.

**Options:**
- `--json` — Output results as JSON

**Example:**
```bash
netglance firewall audit
netglance firewall audit --json
```

### `egress`

Test outbound port reachability. Tests common ports by default; specify `--port` to test a single port.

**Options:**
- `--port <PORT>`, `-p <PORT>` — Test a specific outbound port (optional; if omitted, tests common ports: 22, 25, 53, 80, 443, 587, 993, 8080, 8443)
- `--json` — Output results as JSON

**Examples:**
```bash
netglance firewall egress                    # Test all common ports
netglance firewall egress --port 443         # Test HTTPS only
netglance firewall egress -p 8080 --json     # Test port 8080 as JSON
```

### `ingress`

Test inbound port reachability from the internet. Requires specifying a port.

**Options:**
- `--port <PORT>`, `-p <PORT>` — Port to probe (required)
- `--protocol <PROTOCOL>` — Protocol to test (default: `tcp`; allowed: `tcp`, `udp`)
- `--json` — Output results as JSON

**Examples:**
```bash
netglance firewall ingress --port 22         # Test SSH inbound
netglance firewall ingress --port 443 --protocol tcp --json
```

## Understanding the output

### Port status

Each port test returns one of these statuses:

- **OPEN** (green) — The port accepted a connection. For egress, your network allows outbound traffic on this port. For ingress, the port is reachable from the internet.
- **BLOCKED** (red) — The port did not accept a connection. For egress, your firewall or ISP blocks outbound traffic on this port. For ingress, the port is not reachable from the internet (either blocked locally or by your ISP's CGNAT/firewall).
- **UNKNOWN** (yellow) — Typically for ingress tests when no external probe service is available. netglance cannot test inbound reachability without a service outside your network.

### Output columns

- **Port** — The port number tested
- **Protocol** — Protocol used (TCP or UDP)
- **Status** — OPEN, BLOCKED, or UNKNOWN
- **Latency** — Round-trip time in milliseconds (or `--` if not measured)
- **Target** — For egress, the external host probed (default: portquiz.net)

### Egress vs ingress

- **Egress** — Your computer probes an external service. If successful, your network allows outbound traffic on that port.
- **Ingress** — An external service probes your computer. If successful, the port is reachable from the internet.

## Related concepts

- **[Firewalls and NAT](../../guide/concepts/firewalls-and-nat.md)** — How firewalls work, stateful vs stateless, and why ingress testing is tricky behind CGNAT
- **[Scan](./scan.md)** — Port scanning for internal networks and service discovery
- **[IPv6](./ipv6.md)** — Test IPv6 connectivity and address configuration

## Troubleshooting

### Egress ports show all blocked

This suggests your ISP or corporate network enforces strict egress filtering. Most networks allow ports 80 and 443 (HTTP/HTTPS); if those are blocked, contact your network administrator. Some ISPs block port 25 (SMTP) to prevent spam but allow 587 (SMTP TLS).

### Ingress shows "UNKNOWN" status

No external probe service is configured. To verify inbound reachability, you can:
- Set up a simple probe service on a VPS
- Use online port check services manually
- Check your router's port forwarding rules

### Ingress ports show blocked but I forwarded them in my router

Several layers can block inbound traffic:
1. **Host firewall** (Windows Defender, macOS, ufw, etc.) — Check local firewall rules
2. **Router firewall** — Verify port forwarding and firewall rules on the router
3. **ISP firewall/CGNAT** — If behind CGNAT, your public IP is shared; contact your ISP to open ports
4. **Rate limiting** — Some firewalls may show "blocked" on repeated probes due to rate limiting; wait a minute and retry

### Latency shows extremely high values or `--`

- `--` means the connection timed out or failed before measuring latency
- High latency (500+ ms) typically indicates the target is distant or the connection is being routed through a proxy. For egress, consider using a faster target or increasing timeout.

### SMTP (port 25) is open but I didn't intend it

If port 25 shows open outbound, verify you're not unknowingly running a mail server or relay. This is a security risk—attackers can use your network to send spam. Consider blocking it at your firewall.
