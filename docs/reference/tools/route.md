# Route — Traceroute & Path Analysis

## What it does

The `route` tool performs traceroute to visualize the network path between your device and a destination. Each hop shows:

- **Hop number** (TTL / time-to-live)
- **IP address** of the intermediate router
- **Reverse-DNS hostname** (if available)
- **Round-trip time (RTT)** — latency from you to that hop
- **ASN (Autonomous System Number)** — the network operator at that hop
- **AS Name** — the organization name of that network

You can also compare routes over time to detect changes in your network path — useful for spotting failovers, load balancer rotations, or ISP route changes.

## Quick start

### Basic traceroute
```bash
netglance route trace google.com
```

Shows the path to google.com with ASN information for each hop.

### Save and compare routes
```bash
netglance route trace google.com --save
# ... later ...
netglance route trace google.com --save --diff
```

Compare the current path against the last saved route. Detects hop changes, new ASNs, and path length differences.

### Adjust probe parameters
```bash
netglance route trace 8.8.8.8 --max-hops 20 --timeout 3.0
```

Reduce maximum hops to speed up the trace, or increase timeout if hops are slow to respond.

## Commands

### `netglance route trace`

Run a traceroute to a destination.

**Arguments:**
- `HOST` — Target hostname or IP address (required)

**Options:**
- `--max-hops, -m` — Maximum number of hops to probe (default: 30)
- `--timeout, -t` — Timeout per probe in seconds (default: 2.0)
- `--save` — Persist results to SQLite for future comparison
- `--diff` — Compare this route against the last saved route (only works if you've previously used `--save`)

**Examples:**
```bash
# Trace to a hostname
netglance route trace example.com

# Trace with 20 hops max and 3-second timeout
netglance route trace 1.1.1.1 --max-hops 20 --timeout 3.0

# Save for later comparison
netglance route trace aws.amazon.com --save

# Show changes from last saved route
netglance route trace aws.amazon.com --save --diff
```

## Understanding the output

### The trace table

Each row represents a hop (intermediate router) on the path:

| Column | Meaning |
|--------|---------|
| **Hop** | TTL (Time To Live) value, starting at 1 |
| **IP** | IP address of the router. `* * *` means it didn't respond |
| **Hostname** | Reverse-DNS name, if resolvable. Empty if not available |
| **RTT** | Round-trip time in milliseconds. Lower is faster. `* * *` if no response |
| **ASN** | Autonomous System Number (e.g., `AS15169` for Google) |
| **AS Name** | Human-readable organization name (e.g., `Google Inc.`) |

### Status line

Below the table:
- **Reached** (green) — You successfully reached the destination IP
- **Not reached** (red) — The destination was not found in the trace

### Route changes (with `--diff`)

When comparing against a saved route, you'll see:

1. **Route Changes table** — Shows hop numbers and IP changes
   - `Previous IP` (red) — Old IP at that hop
   - `Current IP` (green) — New IP at that hop
   - If no table appears, the route hasn't changed

2. **New ASNs observed** — ASNs seen in the current route but not in the previous one

3. **Path length delta** — Whether the path is longer or shorter than before

## Related concepts

- **[Ping](./ping.md)** — Measure latency to a single host. Use this when you just need RTT, not the full path.
- **[DNS](./dns.md)** — Resolve hostnames and check for DNS leaks. The route tool uses reverse-DNS on each hop.
- **Autonomous Systems (ASN)** — Every router belongs to an AS, identified by its ASN. Traceroute maps which organizations carry traffic to your destination.

## Troubleshooting

### Seeing `* * *` for many hops

Some routers are configured not to respond to traceroute probes (firewall rules or ICMP rate limiting). This shows as `* * *` in the RTT column.

**Solution:** This is normal. The trace continues to subsequent hops. If the destination is eventually reached, the path is intact.

### Route keeps changing on every run

Load balancers, multipath routing, or traffic engineering can cause slight path variations between runs.

**Solution:** Use `--save --diff` on multiple consecutive runs. A *genuine* route change shows distinct hop IP changes. Natural variation affects only a hop or two.

### Trace stops before reaching the destination

The destination may be:
- Blocking ICMP (some firewalls)
- Configured to not respond to traceroute at all
- Unreachable from your network

**Solution:** Check with `netglance ping <host>` to verify the host is actually reachable. If it responds to ping but not traceroute, the destination blocks traceroute probes.

### Asymmetric routing

Outbound path (you → destination) differs from return path (destination → you). You see the outbound hops in traceroute, not the return path.

**Solution:** This is normal on the internet. AS owners often optimize egress and ingress paths separately. If you need to see the return path, use a tool on the destination end.

### Needs elevated privileges

On some systems, raw socket traceroute requires root or administrator access.

**Solution:** Run with `sudo`:
```bash
sudo uv run netglance route trace example.com
```
