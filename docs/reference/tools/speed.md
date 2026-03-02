# Speed Testing

## What it does

The `speed` subcommand measures your internet connection's download and upload speeds, latency, and jitter. It supports multiple test providers—Cloudflare (default), Ookla (requires `speedtest` CLI), and iperf3 (for LAN testing). Results are automatically saved to a local database, allowing you to track speed degradation over time and identify ISP throttling.

## Quick start

Run a full speed test (download, upload, latency):

```bash
netglance speed
```

Test only download speed (faster):

```bash
netglance speed --download-only
```

Test upload speed only:

```bash
netglance speed --upload-only
```

Use Ookla's speed test (requires `speedtest` CLI installed):

```bash
netglance speed --provider ookla
```

Test LAN speed to a local server using iperf3:

```bash
netglance speed --provider iperf3 --server 192.168.1.100
```

View historical speed tests from the past 7 days:

```bash
netglance speed history
```

## Commands

### Main speed test (`speed`)

Run an internet or LAN speed test.

**Options:**

- `--download-only` — Test download speed only (skips upload and latency)
- `--upload-only` — Test upload speed only (skips download and latency)
- `--provider`, `-p` — Test provider: `cloudflare` (default), `ookla`, or `iperf3`
- `--server`, `-s` — Override the test server hostname or IP (required for iperf3)
- `--duration`, `-d` — Test duration in seconds (default: 10.0; applies to Cloudflare and iperf3)
- `--json` — Output results as JSON instead of a formatted table
- `--save` / `--no-save` — Save result to the local database (default: `--save`)

**Examples:**

```bash
# Full test via Cloudflare (default)
netglance speed

# 20-second Cloudflare test
netglance speed --duration 20

# Custom Cloudflare server
netglance speed --server speed.example.com

# Ookla test (must have speedtest CLI installed)
netglance speed --provider ookla

# iperf3 LAN test (requires iperf3 server running at the given IP)
netglance speed --provider iperf3 --server 192.168.1.50 --duration 15

# Output as JSON for scripting
netglance speed --json
```

### History (`speed history`)

View recent speed test results from the local database.

**Options:**

- `--days`, `-d` — Show results from the last N days (default: 7)
- `--limit`, `-n` — Maximum number of results to show (default: 20)
- `--json` — Output as JSON

**Examples:**

```bash
# Show the last 7 days of speed tests (up to 20 results)
netglance speed history

# Show the last 30 days
netglance speed history --days 30

# Show only the last 5 tests
netglance speed history --limit 5

# Export all speed tests as JSON
netglance speed history --days 90 --limit 100 --json
```

## Understanding the output

When you run a speed test, you'll see a table with these metrics:

- **Download** — Your download speed in Mbps (megabits per second), plus total bytes downloaded. Color-coded: green ≥100 Mbps, yellow 25–99 Mbps, red <25 Mbps.
- **Upload** — Your upload speed in Mbps, plus total bytes uploaded. Color-coded using the same thresholds.
- **Latency** — Median round-trip time (RTT) to the test server in milliseconds. Color-coded: green <20 ms, yellow 20–99 ms, red ≥100 ms.
- **Jitter** — Variation in latency between requests (Cloudflare and Ookla only; iperf3 does not report jitter). Lower is better.
- **Server** — The test server hostname and location (if available).
- **Provider** — The test provider (`cloudflare`, `ookla`, or `iperf3`).
- **Tested at** — Timestamp of the test.

### Provider notes

- **Cloudflare** — Uses Cloudflare's infrastructure. Default server is `speed.cloudflare.com`. Adaptive test sizes ensure good coverage even on very fast or very slow connections. Jitter is calculated from latency samples.
- **Ookla** — Uses Ookla's global speed test network (same as speedtest.net). Requires the `speedtest` CLI tool to be installed. Automatically selects the best server based on ping, so results may vary. Includes official jitter measurement.
- **iperf3** — Tests speed over a local LAN against an iperf3 server you specify. Useful for diagnosing WiFi performance, router throughput, or client device limits. Requires `iperf3` to be installed locally and an iperf3 server running at the target address.

## Related concepts

- **Traffic monitoring** (`netglance traffic`) — Real-time bandwidth usage on your network interfaces. Useful for detecting background downloads or heavy usage affecting speed tests.
- **Latency and jitter** — Also measured by the `ping` module (`netglance ping`), which offers fine-grained ICMP echo testing and continuous monitoring.
- **Network baseline** (`netglance baseline`) — Snapshot your entire network state, including recent speed test results, for change detection over time.
- **Health report** (`netglance report`) — Aggregate summary of all network diagnostics, including speed test trends.

## Troubleshooting

**My WiFi speed is much lower than wired ethernet**

WiFi inherently has lower throughput and higher latency than wired connections. Test from a device close to your router, minimize interference (use 5 GHz or 6 GHz if available), and compare against wired results on the same device to isolate WiFi vs. ISP issues.

**Cloudflare and Ookla results differ significantly**

Different providers use different servers and measurement methods. Ookla's result is generally considered the "official" speed, as it's widely used by ISPs. Cloudflare results may vary depending on server distance and load. Always compare results from the same provider over time to detect trends.

**Iperf3 test fails with "iperf3 not found"**

You need to install iperf3. On macOS: `brew install iperf3`. On Linux: `apt install iperf3` (Debian/Ubuntu) or `yum install iperf3` (RedHat/CentOS). An iperf3 server must also be running at the target address: `iperf3 -s` starts a server on port 5201.

**Speedtest CLI not found**

The Ookla provider requires the `speedtest` CLI tool. Install it from https://www.speedtest.net/apps/cli, then accept the license agreement the first time you run it (`speedtest --accept-license --accept-gdpr`).

**Speed test hangs or times out**

Speed tests can take longer on slow connections. Increase the timeout by running a longer duration (`--duration 30`). If using iperf3, ensure the server is reachable and the port is not blocked by a firewall.

**VPN reduces my measured speed**

VPN encryption and routing overhead can reduce throughput. Disable the VPN temporarily to test your raw ISP speed, or test while connected to identify VPN performance.

**Speed varies by time of day**

Network congestion varies throughout the day. Peak hours (evenings, weekends) often show lower speeds. Test at consistent times to establish a reliable baseline.
