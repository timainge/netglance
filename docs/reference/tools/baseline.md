# Baseline Tool

## What It Does

The `baseline` tool captures snapshots of your network's complete state — devices, ARP table, DNS resolution, and open ports — then compares them over time to detect unauthorized or unexpected changes. This is your primary tool for detecting intrusions, configuration drift, or compromised devices.

Each baseline captures:
- **Devices** discovered on the network (IP, MAC, hostname, vendor)
- **ARP table** (IP-to-MAC mappings)
- **DNS consistency** (resolution results across all configured resolvers)
- **Open ports** on all discovered hosts
- **Gateway MAC** address for spoofing detection

Baselines are stored in SQLite and can be compared against each other or automatically against the most recent capture.

## Quick Start

Capture your first baseline:

```bash
netglance baseline capture --subnet 192.168.1.0/24
```

Later, diff the current state against that saved baseline:

```bash
netglance baseline diff --subnet 192.168.1.0/24
```

List all saved baselines:

```bash
netglance baseline list
```

View details of a specific baseline:

```bash
netglance baseline show 1
```

## Commands

### `baseline capture`

Captures a complete snapshot of the current network state.

**Flags:**
- `--subnet`, `-s` — CIDR subnet to scan (default: `192.168.1.0/24`)
- `--label`, `-l` — Optional label for this baseline (e.g., "post-patch", "after-config-change")
- `--interface`, `-i` — Network interface to use (default: auto-detect)

**Output:**
Prints summary counts and a table of discovered devices with IP, MAC, hostname, vendor, and discovery method.

**Example:**
```bash
netglance baseline capture --subnet 192.168.1.0/24 --label "initial-setup"
```

### `baseline diff`

Compares the current network state against the most recently saved baseline. Useful for periodic audits — run this after network events to see what changed.

**Flags:**
- `--subnet`, `-s` — CIDR subnet to scan (default: `192.168.1.0/24`)
- `--interface`, `-i` — Network interface to use

**Output:**
Colored diff showing:
- New devices (red)
- Missing devices (yellow)
- Changed devices (yellow)
- ARP alerts (red/yellow by severity)
- DNS changes (yellow)
- Port changes (new ports in red, closed ports dimmed)

**Example:**
```bash
netglance baseline diff --subnet 192.168.1.0/24
```

### `baseline list`

Lists all saved baselines with their IDs, labels, and timestamps.

**Flags:**
- None (except hidden `--db` override)

**Output:**
Table with ID, label, and ISO timestamp for each baseline.

**Example:**
```bash
netglance baseline list
```

### `baseline show`

Displays full details of a specific baseline: devices, open ports, and ARP table.

**Arguments:**
- `baseline_id` — Numeric ID of the baseline to display

**Flags:**
- None (except hidden `--db` override)

**Output:**
Summary (label, timestamp, counts) followed by formatted tables of devices, open ports, and ARP entries.

**Example:**
```bash
netglance baseline show 2
```

## Understanding the Output

### Device Changes

In `diff` output, devices are prefixed with symbols and colors:
- **`[red]+[/red]`** — New device (not seen before)
- **`[yellow]-[/yellow]`** — Missing device (was present, now gone)
- **`[yellow]~[/yellow]`** — Changed device (same IP, but MAC or hostname changed)

**Interpretation:** A changed MAC on the same IP suggests MAC spoofing, address recycling, or device replacement. New devices may be guests, temporary IoT devices, or attackers.

### ARP Alerts

ARP alerts are color-coded by severity:
- **Red** — Critical (e.g., gateway spoofing, ARP anomaly)
- **Yellow** — Warning (e.g., unusual patterns)

Alerts include the alert type and description explaining what was detected.

### DNS Changes

DNS changes indicate that a resolver's answers changed between baselines. Types:
- **`new_resolver`** — A resolver appeared (new configuration or interface)
- **`answers_changed`** — A resolver's answers differ (poisoning, misconfiguration, or legitimate updates)

### Port Changes

Port changes per host:
- **`[red]+[/red]`** — New open port (potential vulnerability or service added)
- **`[dim]-[/dim]`** — Closed port (service stopped or firewall change)

## Related Concepts

- **[Discover](discover.md)** — Device discovery methods (ARP, mDNS, uPnP) that baseline uses
- **[ARP Tool](arp.md)** — ARP table monitoring and spoofing detection
- **[Scan Tool](scan.md)** — Port scanning that baseline integrates
- **[DNS Tool](dns.md)** — DNS consistency checking included in baselines
- **[Report Tool](report.md)** — Aggregate health summary that can reference baseline data

## Troubleshooting

### Noisy Diffs from Transient Devices

Phones, guest laptops, and IoT devices that disconnect cause false positives in diffs. Mitigation:
- Use a label to document expected changes: `netglance baseline capture --label "after-guest-wifi-reset"`
- Run multiple baselines and compare against the appropriate one: `netglance baseline show <id>`
- Consider excluding known transient MAC prefixes from analysis (not yet automated)

### Large Baseline Storage

Baselines include all port scan results. Large networks with many open ports will grow the database. To manage:
- Periodically archive old baselines by exporting and deleting rows (manual SQL)
- Use a custom database path for long-term archival: `--db /path/to/archive.db`

### Baseline Portability

Baselines are stored as JSON in SQLite's `baselines` table. To export or transfer:
```bash
sqlite3 ~/.config/netglance/netglance.db "SELECT label, data FROM baselines WHERE id = 1;" > baseline-1.json
```

### Missing Gateway MAC

If the baseline shows "N/A" for gateway MAC, the tool could not find the gateway in the ARP table. This is usually harmless and indicates the gateway is unreachable or using a non-standard MAC.
