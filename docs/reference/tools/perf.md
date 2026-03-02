# Perf: Network Performance Assessment

## What it does

The `perf` tool measures advanced network performance metrics beyond simple speed tests. It diagnostics network quality through four complementary measurements:

- **Jitter** — Variation in latency between consecutive packets. High jitter indicates unstable connections, problematic for VoIP and real-time gaming.
- **Packet loss** — Percentage of packets that don't reach the destination. Even small amounts degrade interactive applications.
- **Path MTU** — Maximum Transmission Unit (largest packet size) supported on the route to the target. Undersized MTU causes fragmentation and reduced throughput.
- **Bufferbloat** — Latency increase under heavy load. Indicates undersized network buffers causing queuing delays, especially common on consumer routers and ISP uplinks.

Combined, these metrics reveal whether your network can reliably handle demanding applications like video conferencing, online gaming, or VoIP.

## Quick start

### Full performance check
```bash
netglance perf run
```

Tests all four metrics to `1.1.1.1` (Cloudflare DNS). Takes ~30–60 seconds.

### Jitter only
```bash
netglance perf run --jitter-only
```

Measures jitter with 50 pings. Useful when quick diagnosis is needed.

### Bufferbloat test
```bash
netglance perf run --bufferbloat
```

Detects bufferbloat by comparing latency at rest vs under load. Simulates a 10-second download.

### MTU discovery
```bash
netglance perf run --mtu
```

Binary-searches to find the largest packet size the route supports. Useful when troubleshooting fragmentation or MTU mismatches.

### Custom target
```bash
netglance perf run 8.8.8.8
netglance perf run --jitter-only 192.168.1.1
```

Test any reachable host instead of the default `1.1.1.1`.

### JSON output
```bash
netglance perf run --json
netglance perf run --mtu --json
```

Output results as JSON for parsing by scripts or dashboards.

## Commands

### `netglance perf run [HOST]`

**Subcommands:** None (all options are flags)

**Arguments:**
- `HOST` — Target host to test. Optional; defaults to `1.1.1.1`.

**Flags:**

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--jitter-only` | | False | Run jitter measurement only (50 pings). |
| `--mtu` | | False | Run path MTU discovery only. |
| `--bufferbloat` | | False | Run bufferbloat detection only. |
| `--count` | `-c` | 50 | Number of pings for jitter measurement. |
| `--json` | | False | Output results as JSON instead of formatted table. |

**Behavior:**
- If no sub-test flag is provided, runs the full test suite (jitter + MTU + bufferbloat).
- If one of `--jitter-only`, `--mtu`, or `--bufferbloat` is set, runs only that test.
- Full test takes ~30–60 seconds. Individual tests take 5–15 seconds.

## Understanding the output

### Jitter
**What it is:** Mean absolute difference between consecutive RTTs (round-trip times). Measured in milliseconds.

**Quality thresholds:**
- **< 5 ms** — Excellent. Suitable for any application (VoIP, gaming, video).
- **5–20 ms** — Good. Most users won't notice; some games may see microstutter.
- **20–50 ms** — Fair. VoIP becomes noticeably choppy; gaming has visible lag spikes.
- **> 50 ms** — Poor. Nearly unusable for real-time applications.

**Causes of high jitter:**
- WiFi interference or distance from AP.
- Congested ISP or home network.
- Bufferbloat on the router (see below).
- Packet prioritization by ISP (traffic shaping).

### P95 and P99 Latency
**What they are:** 95th and 99th percentiles of latency. Represent typical worst-case delays.

- **P95** — 95% of packets arrive faster than this.
- **P99** — 99% of packets arrive faster than this.

High percentile latencies indicate occasional lag spikes. A P99 value much higher than average latency suggests intermittent congestion.

### Packet Loss
**What it is:** Percentage of sent packets that never arrive. Measured as 0–100%.

**Thresholds:**
- **0%** — No loss; excellent.
- **< 1%** — Normal. Imperceptible for most applications.
- **1–5%** — Noticeable. VoIP becomes choppy; streaming may rebuffer.
- **> 5%** — Severe. Internet is practically unusable.

Packet loss is often caused by:
- WiFi dropout or weak signal.
- Router memory/CPU overload.
- ISP line quality or congestion.

### Path MTU
**What it is:** The largest packet size (in bytes) that can traverse the route without fragmentation.

**Standard values:**
- **1500 bytes** — Ethernet standard. Ideal for most home networks.
- **1492 bytes** — PPPoE (common on some ISPs).
- **1472 bytes** — GRE or other encapsulation.
- **< 1280 bytes** — Indicates a problematic link or misconfiguration.

**Why it matters:**
- Undersized MTU causes packets to be split (fragmented), increasing overhead and reducing throughput.
- Some firewalls or ISPs block ICMP, causing MTU discovery to fail (may report minimum 68 bytes).

### Bufferbloat Rating
**What it is:** Comparison of latency when idle vs. under heavy load.

**Ratings:**
- **NONE** (green) — Latency increases < 2x under load. Buffers are right-sized. Excellent.
- **MILD** (yellow) — Latency increases 2–4x. Some queueing occurs; interactive applications may lag during uploads/downloads.
- **SEVERE** (red) — Latency increases > 4x. Buffers are severely undersized; the connection becomes unresponsive during heavy use.

**What causes bufferbloat:**
- Consumer router with undersized buffers.
- ISP uplink/downlink congestion.
- Operating system TCP stack defaults (tuning can help).

A severe rating means your router or ISP is adding 200+ ms of extra delay during heavy transfers. This destroys VoIP, video calls, and gaming.

## Related concepts

- [**Speed**](./speed.md) — Bandwidth testing (download/upload throughput). Complements perf for a complete picture of link quality.
- [**Ping**](./ping.md) — Basic latency and connectivity checks. Perf extends ping with jitter, percentiles, and load testing.
- [**Route**](./route.md) — Traceroute and path analysis. Use to identify which hop is causing MTU issues or high latency.

## Troubleshooting

### MTU discovery reports 68 bytes or fails
**Cause:** Firewall (yours or ISP's) blocking ICMP packets needed for MTU probe.

**Solutions:**
- Check if `ping` works to the target. If not, ICMP is blocked.
- Test against different hosts (e.g., `8.8.8.8`, `8.8.4.4`).
- Ask your ISP about ICMP filtering.
- On your router, check if ICMP is allowed in the firewall rules.

### Bufferbloat test shows "NONE" but download/upload feels laggy
**Cause:** Bufferbloat test uses Cloudflare's CDN, which is fast and nearby. Your actual ISP connection may have different characteristics.

**Solutions:**
- Run the test against your ISP gateway (default gateway; find with `netglance route`).
- Monitor real-world usage: run video call during a large download and see if audio/video freezes.
- Test with a direct file transfer to a server you control.

### Jitter is high only on WiFi, not wired
**Cause:** WiFi is inherently less stable than ethernet, especially over distance or with interference.

**Solutions:**
- Test from a wired connection to establish a baseline.
- Move closer to the AP or reduce interference (change WiFi channel).
- Check for neighboring networks on the same channel (use `netglance wifi scan` if available).
- Consider upgrading to WiFi 6 (802.11ax) or using a mesh system.

### All metrics are poor during peak hours
**Cause:** ISP or your network is congested.

**Solutions:**
- Test at off-peak times to confirm if ISP or home network is the bottleneck.
- Check active connections: run `netglance discover` to see all devices on your network.
- Upgrade your internet plan or switch providers.
- Consider QoS (Quality of Service) rules on your router to prioritize VoIP/gaming traffic.
