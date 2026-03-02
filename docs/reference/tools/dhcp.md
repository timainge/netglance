# DHCP Monitoring

Monitor DHCP traffic on your network, detect rogue DHCP servers, and inspect lease information.

## What it does

The `dhcp` tool captures and analyzes DHCP packets on your network to:

- **Monitor DHCP traffic** — Watch DHCP Discover, Offer, Request, and ACK packets in real time
- **Detect rogue servers** — Identify unexpected DHCP servers that could be attacking your network
- **Inspect leases** — See which devices are getting DHCP leases, assigned IPs, gateways, and DNS servers
- **Track lease parameters** — Display lease times, renewal settings, and DHCP options

**Note:** Packet capture requires root/sudo privileges on most systems.

## Quick start

Check for rogue DHCP servers (quick 10-second scan):

```bash
sudo netglance dhcp check
```

Monitor DHCP traffic for 60 seconds:

```bash
sudo netglance dhcp monitor --duration 60
```

View observed DHCP leases:

```bash
sudo netglance dhcp leases --duration 30
```

Specify an expected DHCP server to only flag others as rogue:

```bash
sudo netglance dhcp monitor --expected "192.168.1.1"
```

## Commands

### monitor

Listen for DHCP traffic and detect rogue servers.

```bash
sudo netglance dhcp monitor [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--duration SECONDS` | `-d` | 30.0 | How long to listen for DHCP packets (seconds) |
| `--interface NAME` | `-i` | (auto) | Network interface to listen on (uses default if omitted) |
| `--expected "IP1,IP2"` | `-e` | (auto-detect) | Comma-separated list of authorized DHCP server IPs |
| `--json` | — | false | Output results as JSON instead of formatted tables |

**Examples:**

```bash
# Monitor all interfaces for 60 seconds
sudo netglance dhcp monitor --duration 60

# Monitor a specific interface
sudo netglance dhcp monitor --interface en0 --duration 45

# Specify expected servers (any other server is flagged)
sudo netglance dhcp monitor --expected "10.0.0.1,192.168.1.1"

# Export results as JSON
sudo netglance dhcp monitor --json | jq .alerts
```

### check

Quick rogue DHCP server check (10-second sniff). Useful for rapid security scans.

```bash
sudo netglance dhcp check [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--interface NAME` | `-i` | (auto) | Network interface to listen on |
| `--expected "IP1,IP2"` | `-e` | (auto-detect) | Comma-separated list of authorized DHCP server IPs |
| `--json` | — | false | Output results as JSON |

**Examples:**

```bash
# Quick rogue server check
sudo netglance dhcp check

# Check a specific interface
sudo netglance dhcp check --interface en0

# Disable auto-detect and whitelist only known servers
sudo netglance dhcp check --expected "10.0.0.1"
```

### leases

Show observed DHCP leases from captured ACK (Acknowledgment) packets.

```bash
sudo netglance dhcp leases [OPTIONS]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--duration SECONDS` | `-d` | 30.0 | Listen duration in seconds |
| `--interface NAME` | `-i` | (auto) | Network interface to listen on |
| `--json` | — | false | Output results as JSON |

**Examples:**

```bash
# See leases observed in the last 30 seconds
sudo netglance dhcp leases

# Capture leases over 2 minutes
sudo netglance dhcp leases --duration 120

# Export as JSON for scripting
sudo netglance dhcp leases --json | jq '.[] | {client_mac, assigned_ip}'
```

## Understanding the output

### DHCP Events Table

When you run `monitor` or `check`, you see a table of DHCP packets:

| Column | Meaning |
|--------|---------|
| **Time** | When the packet was captured (HH:MM:SS) |
| **Type** | DHCP message type: `DISCOVER`, `OFFER`, `REQUEST`, `ACK`, `NAK`, `RELEASE` |
| **Client MAC** | MAC address of the device requesting/renewing a lease |
| **Client IP** | IP address already held by the client (0.0.0.0 if none) |
| **Server IP** | IP address of the DHCP server responding |
| **Offered IP** | IP address offered to the client |
| **Gateway** | Default gateway (router) from DHCP option 3 |
| **DNS** | DNS servers from DHCP option 6 |

**Example flow:**

1. Client sends **DISCOVER** (broadcasts a request for any DHCP server)
2. Server replies with **OFFER** (IP 192.168.1.100)
3. Client sends **REQUEST** (I want that IP)
4. Server replies with **ACK** (lease confirmed)

### Rogue Server Alerts

If a rogue server is detected, you see a red panel:

```
╭─ ALERT: CRITICAL ─╮
│ Type: rogue_server │
│ Server IP: 10.0.0.50 │
│ Server MAC: aa:bb:cc:dd:ee:ff │
│ Description: Unauthorized DHCP server detected… │
╰──────────────────╯
```

A "rogue" server is:
- **Any DHCP server not in your whitelist** (if you specify `--expected`)
- **Any DHCP server other than the most common one** (auto-detect mode)

### Leases Table

The `leases` command shows ACK packets formatted as a lease summary:

| Column | Meaning |
|--------|---------|
| **Client MAC** | Device MAC address |
| **Assigned IP** | IP address from the ACK packet |
| **Server IP** | DHCP server that issued the lease |
| **Gateway** | Router/default gateway |
| **DNS Servers** | Comma-separated DNS server IPs |
| **Lease Time** | Lease duration in seconds (e.g., 86400s = 1 day) |
| **Time** | When the ACK was captured |

## Related concepts

- **[DHCP Overview](../../guide/concepts/dhcp-how-it-works.md)** — How DHCP works and why monitoring matters
- **[Network Discovery](discover.md)** — Enumerate devices on your network
- **[DNS](dns.md)** — Monitor DNS queries and detect leaks

## Troubleshooting

### "Permission denied" or "Must be run with sudo"

DHCP packet capture requires raw socket access, which only root/sudo can use.

```bash
# ✓ Correct
sudo netglance dhcp monitor

# ✗ Wrong
netglance dhcp monitor
```

### Multiple DHCP servers flagged as rogue but they're legitimate

Common in enterprise networks with DHCP relay agents, failover pairs, or VLANs. Use `--expected` to whitelist known servers:

```bash
sudo netglance dhcp monitor --expected "10.0.0.1,10.0.0.2"
```

### No DHCP events captured

Reasons:
- No active DHCP traffic during the listening window (no devices renewing leases)
- Listening on the wrong interface (`--interface` to specify)
- Firewall blocking UDP port 67/68

Try a longer duration and check that devices are actively requesting leases:

```bash
sudo netglance dhcp monitor --duration 120
```

### macOS DHCP lease renewal behavior

macOS typically renews leases in the background; you may see fewer DHCP packets than on other operating systems. If you're not seeing lease activity, trigger a renewal:

```bash
# In another terminal, renew DHCP on macOS
sudo ipconfig set en0 DHCP
```

Then re-run the monitor command.
