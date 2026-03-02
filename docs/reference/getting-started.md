# Getting Started with netglance

> Discover devices on your network, monitor connectivity, and get a complete health report in minutes.

## What it does

netglance is a command-line tool for understanding your home network. It finds all connected devices, checks DNS resolution, measures speed and latency, scans for open ports, and gives you a complete health report. Think of it as a diagnostic toolkit for your router and the devices connected to it.

**When to use it**: When something feels slow, you want to find a mysterious device on your network, diagnose Wi-Fi problems, check if DNS is leaking, or just understand what's on your network and how it's performing.

!!! tip "Multiple ways to use netglance"
    This guide covers interactive CLI usage. netglance also works as an
    [MCP server for AI assistants](usage-modes/mcp.md),
    a [background daemon](usage-modes/daemon.md), or a
    [dedicated network monitor](usage-modes/dedicated.md).
    See **[Usage Modes](usage-modes/index.md)** to pick the right setup.

## How netglance fits into your workflow

netglance adapts to how you work. This guide covers the CLI. Once you're comfortable, explore other modes:

<div class="card-grid">
<a class="card" href="usage-modes/mcp/">
<p class="card-title">AI Agent (MCP)</p>
<p class="card-desc">Ask Claude or Cursor about your network in plain English.</p>
</a>
<a class="card" href="usage-modes/daemon/">
<p class="card-title">Background Daemon</p>
<p class="card-desc">Scheduled checks, alerting, and trend data — runs silently on your Mac.</p>
</a>
<a class="card" href="usage-modes/dedicated/">
<p class="card-title">Dedicated Monitor</p>
<p class="card-desc">24/7 on a Raspberry Pi, Mac Mini, or Docker container.</p>
</a>
<a class="card" href="usage-modes/scheduled/">
<p class="card-title">Scheduled Checks</p>
<p class="card-desc">Lightweight cron jobs — no persistent process.</p>
</a>
</div>

See **[Usage Modes](usage-modes/index.md)** for the full comparison.

## Installation

### With `uv` (recommended)

If you have [uv](https://docs.astral.sh/uv/) installed:

```bash
uv tool install netglance
```

This installs netglance globally and updates it easily later.

### With `pip`

If you prefer pip:

```bash
pip install netglance
```

### Requirements

- **Python 3.11 or later** — check your version with `python --version`
- **Administrator or sudo access** — many network operations (ARP scanning, packet capture) require elevated privileges
- **macOS, Linux, or WSL** — netglance works on Unix-like systems

### Verify installation

```bash
netglance --version
netglance --help
```

You should see the version and a list of available commands.

## First run: Discover your network

The easiest way to start is to discover what devices are on your network:

```bash
sudo netglance discover
```

(Use `sudo` because ARP scanning requires root on most systems.)

### What it shows

You'll see a table with each device found:

```
IP Address      Hostname        MAC Address              Vendor
─────────────────────────────────────────────────────────────────────────────
192.168.1.1     router.local    aa:bb:cc:dd:ee:ff       Apple
192.168.1.42    macbook.local   aa:bb:cc:dd:ee:00       Apple
192.168.1.100   tv.local        aa:bb:cc:dd:ee:01       Samsung Electronics
192.168.1.101   camera          aa:bb:cc:dd:ee:02       Unknown
```

**Columns explained**:
- **IP Address** — the device's current network address
- **Hostname** — the device's name on the network (if available via mDNS)
- **MAC Address** — the unique hardware identifier
- **Vendor** — the manufacturer, looked up from the MAC prefix

## First run: Network health report

Once you know your network, get a complete health check:

```bash
netglance report
```

This runs checks across all modules and gives you a quick status:

```
Network Health Report
─────────────────────────────────────────────────────────────────
Discover         ✓ 8 devices found
DNS              ✓ No leaks detected
Ping             ✓ All devices responsive (avg 5ms)
Speed            ⚠ Download 45 Mbps (expected 100+)
HTTP             ✓ No proxies detected
WiFi             ⚠ Signal strength: -68 dBm (fair)
TLS              ✓ All certificates valid
Traffic          ✓ <1 GB today
```

**Status indicators**:
- **✓ Green** — everything is good
- **⚠ Yellow** — something to pay attention to (maybe not urgent)
- **✗ Red** — something that needs fixing

## Understanding the output

netglance uses **Rich formatting** to make output readable. Here's what to look for:

### Colors

- **Green text or ✓** — healthy, expected result
- **Yellow text or ⚠** — warning, degraded but working
- **Red text or ✗** — problem, needs investigation
- **Blue/cyan text** — informational, neutral

### Tables and lists

Most commands show output as formatted tables with aligned columns. Scan down to find the row you care about. Sort or filter with flags like `--filter` if available.

### Units

- **Latency**: milliseconds (ms). Under 50 ms is good; over 100 ms suggests slowness.
- **Speed**: Megabits per second (Mbps). Compare against your ISP plan.
- **Signal**: dBm (decibels). -30 to -50 dBm is excellent; -70+ is weak.
- **Bandwidth**: bytes (B), KB, MB, GB per time period.

## What to try next

Once you've run `discover` and `report`, explore these commands:

### `ping` — Check latency to a device

```bash
netglance ping 192.168.1.1
```

Measures response time. Good for finding which device is slow. See [Ping & Latency](tools/ping.md).

### `dns` — Check DNS health

```bash
netglance dns
```

Tests if DNS is working and if your queries are leaking outside your ISP. See [DNS](tools/dns.md).

### `scan` — Find open ports and services

```bash
sudo netglance scan 192.168.1.100
```

Discover what services are running on a device. See [Port Scanning](tools/scan.md).

### `wifi` — Analyze wireless environment

```bash
netglance wifi
```

Shows signal strength, channel congestion, neighboring networks. See [Wi-Fi](tools/wifi.md).

### `speed` — Measure internet speed

```bash
netglance speed
```

Tests download/upload via speedtest and gives you consistent metrics. See [Speed](tools/speed.md).

### `tls` — Check TLS certificate validity

```bash
netglance tls
```

Verifies HTTPS certificates on your devices and domains. See [TLS](tools/tls.md).

### Other useful commands

- **`traffic`** — Monitor real-time bandwidth per host
- **`route`** — Trace the path packets take to reach a destination
- **`arp`** — Watch for ARP spoofing and MITM attacks
- **`http`** — Detect proxies and analyze HTTP headers
- **`baseline`** — Snapshot your network state and diff against it later
- **`daemon`** — Run continuous monitoring in the background
- **`export`** — Export results to JSON/CSV for analysis

Run `netglance <command> --help` to see all options for any command.

## Configuration

netglance stores two things in `~/.config/netglance/`:

### `config.yaml` — Settings

Customize defaults here: which interfaces to use, DNS servers to check, speed test server, etc.

### `netglance.db` — Database

SQLite database storing historical data: devices seen, latency averages, speed trends. Used by `baseline` and `daemon` to track changes over time.

**You don't need to edit these manually to get started.** They'll be created automatically on first run with sensible defaults.

## Getting help

- **`netglance --help`** — Show all available commands
- **`netglance <command> --help`** — Show options for a specific command (e.g., `netglance ping --help`)
- **Each guide page** — Links and examples for deeper dives

## Troubleshooting

### "Permission denied" on discover/scan

Network operations need root. Run with `sudo`:

```bash
sudo netglance discover
```

### "No devices found" on discover

- Check that you're connected to the network (wired or Wi-Fi)
- Try specifying an interface: `sudo netglance discover --interface en0`
- On Linux, you may need to install `arp-scan` or `nmap`: `apt-get install arp-scan`

### "Connection refused" on ping

The target device may be offline or blocking ICMP (ping). Try `netglance scan` or `netglance http` to probe for services instead.

### DNS lookups are slow

Check your DNS server: `netglance dns --servers 8.8.8.8 1.1.1.1`. Compare against your ISP's default.

### macOS-specific notes

- netglance works with Homebrew Python and system Python on macOS
- Some commands (ARP, packet capture) require `sudo`
- Use interface names like `en0` (Wi-Fi) or `en1` (Ethernet); find them with `ifconfig`

## Next steps

- Read the [Discover & Inventory](tools/discover.md) guide for deep device enumeration
- Set up `daemon` mode for continuous monitoring
- Create a baseline with `baseline save` to track changes over time
- Explore the API reference if you want to use netglance as a Python library

Happy monitoring!
