# Traffic & Bandwidth Monitoring

Monitor real-time bandwidth usage across network interfaces, track cumulative data transfer, and identify bandwidth patterns. The traffic tool reads system network counters and displays throughput in human-readable units.

## What it does

The traffic tool provides:

- **Live bandwidth dashboard** — Real-time TX (upload) and RX (download) rates for a single interface
- **Interface stats snapshot** — Cumulative bytes and packets sent/received since last system boot
- **Per-interface breakdown** — See traffic stats for all interfaces or filter to a specific one
- **Automatic unit scaling** — Bandwidth displayed in B/s, KB/s, MB/s, or GB/s

The tool uses system network I/O counters (via `psutil`), so it works on all platforms without requiring packet capture or root privileges (except for advanced packet-level features not yet exposed in the CLI).

## Quick start

Show cumulative traffic on all interfaces:

```bash
netglance traffic stats
```

Filter to a specific interface (macOS example):

```bash
netglance traffic stats --interface en0
```

Live bandwidth monitor for 10 seconds (updates twice per second):

```bash
netglance traffic live en0
```

Monitor with custom sampling interval (2-second samples):

```bash
netglance traffic live eth0 --interval 2.0
```

## Commands

### `traffic stats`

Display cumulative network interface traffic counters since last boot.

**Options:**

| Option | Alias | Description |
|--------|-------|-------------|
| `--interface NAME` | `-i` | Filter to a specific interface (e.g. `en0`, `eth0`). If not provided, shows all interfaces. |

**Output columns:**

- **Interface** — Network interface name
- **Bytes Sent** — Cumulative bytes transmitted (auto-scaled)
- **Bytes Recv** — Cumulative bytes received (auto-scaled)
- **Pkts Sent** — Total packets transmitted
- **Pkts Recv** — Total packets received

**Example:**

```bash
netglance traffic stats
```

```
Interface Traffic Stats
┌───────────┬────────────┬────────────┬──────────┬──────────┐
│ Interface │ Bytes Sent │ Bytes Recv │ Pkts Sent│ Pkts Recv│
├───────────┼────────────┼────────────┼──────────┼──────────┤
│ en0       │ 2.34 GB    │ 8.12 GB    │ 1,245,678│ 987,654  │
│ lo0       │ 156.78 MB  │ 156.78 MB  │ 45,123   │ 45,123   │
└───────────┴────────────┴────────────┴──────────┴──────────┘
```

### `traffic live`

Live bandwidth dashboard for a network interface. Updates in real-time (2x per second).

**Arguments:**

- `INTERFACE` (required) — Network interface name to monitor (e.g. `en0`, `eth0`, `wlan0`)

**Options:**

| Option | Alias | Description |
|--------|-------|-------------|
| `--interval SECONDS` | `-n` | Sampling interval in seconds. Default: 1.0. Lower values = more responsive, higher CPU. |

**Output:**

Live table showing:

- **TX (upload)** — Bytes per second transmitted
- **RX (download)** — Bytes per second received

Press `Ctrl+C` to stop.

**Example:**

```bash
netglance traffic live en0 --interval 0.5
```

Updates live:

```
Live Bandwidth: en0
┌──────────────┬──────────┐
│ Direction    │ Rate     │
├──────────────┼──────────┤
│ TX (upload)  │ 1.23 MB/s│
│ RX (download)│ 45.67 MB/s
└──────────────┴──────────┘
```

## Understanding the output

### Bandwidth units

Bandwidth is displayed in bytes per second with automatic scaling:

- **B/s** — Bytes per second (< 1 KB/s)
- **KB/s** — Kilobytes per second (≥ 1 KB/s, < 1 MB/s)
- **MB/s** — Megabytes per second (≥ 1 MB/s, < 1 GB/s)
- **GB/s** — Gigabytes per second (≥ 1 GB/s)

Note: 1 KB = 1024 bytes (binary, not decimal).

### TX vs RX

- **TX** — Transmit (upload). Bytes your device sent out.
- **RX** — Receive (download). Bytes your device received.

### Throughput vs cumulative transfer

The `live` command shows **instantaneous bandwidth** (bytes per second right now). The `stats` command shows **cumulative transfer** (total since boot or last reset), useful for checking daily/monthly limits.

### Interface names

Common interface names by OS:

- **macOS** — `en0` (Wi-Fi), `en1` (Ethernet), `lo0` (loopback)
- **Linux** — `eth0`, `wlan0`, `lo` (loopback)
- **Windows** — Interface numbers or descriptive names

List all interfaces on your system:

```bash
netglance traffic stats
```

The interface names shown are the ones available on your system.

## Related concepts

- **Speed test** (`netglance speed`) — Measure maximum download/upload capacity. Compare this to current bandwidth from `traffic live` to see utilization.
- **Performance analysis** (`netglance perf`) — Measure latency, jitter, and packet loss alongside bandwidth.
- **Daemon & monitoring** (`netglance daemon`) — Collect continuous traffic samples in the background for historical trending.

## Troubleshooting

### Interface not found

**Error:** `Interface 'en0' not found. Available: ...`

**Fix:** Check your system's actual interface names:

```bash
netglance traffic stats
```

The first column lists all available interfaces. Use that name with `--interface`.

### Live monitor shows zero or very low bandwidth

**Cause:** Interface is idle or sampling interval is too short to capture traffic.

**Fix:**
- Ensure traffic is actually flowing on that interface (e.g., open a browser tab and stream a video)
- Increase the sampling interval: `--interval 2.0` instead of `--interval 1.0`

### Counters reset unexpectedly

**Cause:** System reboot, or the interface was disabled and re-enabled.

**Behavior:** `netglance traffic stats` shows cumulative counters from the OS kernel. These reset on reboot or device restart.

**Fix:** For historical tracking, use the daemon (`netglance daemon`) to log snapshots to the database before reboots.

### VPN or tunnel traffic appears twice

**Cause:** Some VPN software creates virtual interfaces that duplicate traffic from physical interfaces.

**Behavior:** Total traffic from `traffic stats` exceeds actual WAN usage.

**Fix:** Monitor only your physical interface (e.g., `en0` for Wi-Fi, not `utun0` for VPN), or subtract tunnel interface counts manually.
