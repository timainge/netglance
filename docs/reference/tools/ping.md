# Ping & Connectivity

> Test host reachability and measure round-trip latency using ICMP echo requests.

## What it does

The ping tool sends ICMP echo requests to hosts and measures how long each reply takes (round-trip time, or RTT). This is one of the quickest ways to verify that a host is reachable on your network and whether the connection quality is good or degraded.

netglance's ping subcommand group includes four modes:

- **`host`** — Ping a specific IP or hostname.
- **`gateway`** — Automatically detect and ping your default gateway (your router).
- **`internet`** — Check connectivity to the public internet by pinging Cloudflare, Google, and Quad9 DNS servers.
- **`sweep`** — Ping all hosts in a subnet and show which ones are alive (useful for a quick liveness check).

Each command can run once to get a snapshot, or continuously with `--watch` to see real-time changes.

## Quick start

```bash
# Ping your gateway (router) once
netglance ping gateway

# Ping a specific host continuously (useful for debugging Wi-Fi issues)
netglance ping host 192.168.1.100 --watch

# Check if you have internet (pings public DNS servers)
netglance ping internet

# Sweep your local subnet for responsive hosts
netglance ping sweep 192.168.1.0/24

# Ping with custom echo count (default is 4)
netglance ping host 8.8.8.8 --count 10
```

## Commands

### `ping host` — Ping a single host

```bash
netglance ping host <HOST> [OPTIONS]
```

**Arguments:**
- `HOST` — IP address or hostname to ping (required).

**Options:**
- `--count, -c <N>` — Number of ICMP echo requests to send. Default: `4`.
- `--timeout, -t <SECONDS>` — Timeout (seconds) to wait for each reply. Default: `2.0`.
- `--watch, -w` — Continuous ping with live updating display. Press Ctrl+C to stop.

### `ping gateway` — Ping the default gateway

```bash
netglance ping gateway [OPTIONS]
```

Automatically detects your default gateway (typically your router) and pings it.

**Options:**
- `--count, -c <N>` — Number of ICMP echo requests. Default: `4`.
- `--timeout, -t <SECONDS>` — Timeout (seconds) per request. Default: `2.0`.
- `--watch, -w` — Continuous ping with live display.

### `ping internet` — Check internet connectivity

```bash
netglance ping internet [OPTIONS]
```

Pings three well-known public DNS servers (Cloudflare, Google, Quad9) to verify you can reach the public internet. This is a quick sanity check for outbound connectivity.

**Options:**
- `--count, -c <N>` — Number of echo requests per host. Default: `4`.
- `--timeout, -t <SECONDS>` — Timeout (seconds) per request. Default: `2.0`.
- `--watch, -w` — Continuous check with live display.

### `ping sweep` — Sweep a subnet for responsive hosts

```bash
netglance ping sweep <SUBNET> [OPTIONS]
```

**Arguments:**
- `SUBNET` — CIDR subnet to scan (e.g., `192.168.1.0/24`). Required.

**Options:**
- `--timeout, -t <SECONDS>` — Timeout (seconds) per host. Default: `1.0`.

The output shows only the hosts that replied (are alive). This is faster than ARP discovery for a quick liveness check but may miss some devices (e.g., those behind firewalls that block ICMP).

## Understanding the output

Each command displays a table with these columns:

| Column | Meaning |
|--------|---------|
| **Host** | IP address or hostname that was pinged. |
| **Status** | `UP` (green) if reachable, `DOWN` (red) if no response. |
| **Avg** | Average round-trip time in milliseconds. `--` if host is unreachable. |
| **Min** | Fastest reply time. |
| **Max** | Slowest reply time. |
| **Loss** | Percentage of packets that did not receive a reply (0–100%). |

### Interpreting latency

The color of the latency values indicates quality:

- **Green (< 20 ms)** — Excellent latency. Typical for local network hosts or geographically close servers.
- **Yellow (20–100 ms)** — Good latency. Normal for distant servers or high-latency links.
- **Red (≥ 100 ms)** — Poor latency. May indicate network congestion, Wi-Fi interference, or a slow internet connection.

### Gateway latency guidelines

- **< 5 ms** — Excellent. You are wired and very close to the gateway.
- **5–20 ms** — Normal. Typical for Wi-Fi or a slightly longer local path.
- **> 50 ms** — Investigate. May indicate congestion, interference, or a broken route.

### Internet latency guidelines

- **< 50 ms** — Good. Responsive and snappy.
- **50–150 ms** — Acceptable. Noticeable but usable for most tasks.
- **> 200 ms** — Slow. May affect real-time applications (VoIP, gaming) or feel sluggish.

## Sweep mode

The `ping sweep` command pings every IP on a subnet and reports only the alive hosts. By default, timeout is shorter (1 second) to keep the sweep fast.

```bash
netglance ping sweep 192.168.1.0/24
```

This is useful for:
- Quick inventory of active devices on your network.
- Detecting when new devices join or go offline.
- Baseline before more invasive discovery (e.g., ARP or nmap).

**Note:** ICMP may be filtered by individual firewalls, so a host showing as `DOWN` does not always mean it is offline—it may simply be blocking ICMP. Use ARP discovery or device-specific checks for more reliable detection.

## Related concepts

- [How Networks Work](../../guide/concepts/how-networks-work.md) — Background on ICMP, gateways, and network hops.
- [Discovery](discover.md) — ARP and mDNS discovery for a more comprehensive device inventory.
- [Network Baseline](baseline.md) — Take snapshots of network state and compare over time.

## Troubleshooting

### Host shows as DOWN but I know it's online

**Cause:** The host is blocking ICMP echo requests via a local firewall or upstream firewall rules.

**Solutions:**
- Try pinging from a different network to rule out upstream filters.
- Use ARP discovery (`netglance discover arp`) instead; it doesn't rely on ICMP.
- Check if the host has a firewall rule blocking ICMP (e.g., Windows Defender, iptables).

### "Could not detect default gateway" error

**Cause:** The system could not automatically find the default gateway.

**Solutions:**
- Ensure you have an active network connection.
- On Linux, verify that `/proc/net/route` exists and is readable.
- On macOS/BSD, verify that the `route` command is available.
- Manually specify the gateway IP: `netglance ping host <GATEWAY_IP>`.

### High packet loss or inconsistent latency

**Causes:**
- Network congestion (saturated link).
- Wi-Fi interference (other networks on the same channel, microwave ovens, cordless phones).
- Routing instability or link flapping.
- Host under load, slow to respond.

**Solutions:**
- Use `--watch` to observe latency over time and spot trends.
- Check for Wi-Fi interference with the wifi module (`netglance wifi scan`).
- Look for traffic spikes with the traffic module.
- Move closer to the access point if on Wi-Fi.
- Restart the gateway or affected host.

### Elevated privileges required (Linux)

Some systems require `sudo` to send raw ICMP packets. netglance attempts to use unprivileged ping, but if you see permission errors:

```bash
sudo netglance ping gateway
```

On modern Linux systems with `CAP_NET_RAW`, unprivileged ping usually works out of the box.

### Timeout too short or too long

If most replies arrive with "timeout" or `--`, adjust the `--timeout` flag:

- **Increase** (`--timeout 5.0`) if the host is slow or the network is congested.
- **Decrease** (`--timeout 0.5`) if you want faster failures and the host is known to be fast.

Default is 2 seconds, which works for most local and internet hosts.
