# Reading Reports

A health report gives you a snapshot of your network's current status across multiple dimensions. Every module in netglance runs a check and returns a result with a status level. This guide explains how to interpret those results.

## The 5 Status Levels

Every check you run will return one of five possible statuses: `pass`, `warn`, `fail`, `error`, or `skip`. Each means something different about what was found.

### Pass

A `pass` means the check ran successfully and found no problems.

**Example:** "DNS resolvers consistent, fastest: 8.8.8.8" — all your DNS servers agree on answers, resolution is fast, no hijacking detected.

**What it means for your network:** This aspect is working correctly. No action needed.

### Warn

A `warn` means the check ran and found something worth paying attention to, but it's not a showstopper. Often this indicates degraded performance, inconsistency, or a configuration that's suboptimal.

**Example:** "Download speed below threshold: 18.5 Mbps" — your internet is slower than the 25 Mbps benchmark, but still usable.

**What it means for your network:** Something isn't ideal, but your network is still functional. Investigate if you want to improve it.

### Fail

A `fail` means the check detected a problem that significantly impacts network health or security. This requires investigation and usually action.

**Example:** "Potential DNS hijack detected - resolver answers diverge" — different DNS servers are giving different answers, suggesting someone may be intercepting or redirecting your queries.

**What it means for your network:** Address this soon. A failed check often indicates a real issue with connectivity, security, or reliability.

### Error

An `error` means the check couldn't run at all, usually due to a technical problem: missing permissions, network unreachable, misconfiguration, or an unexpected crash.

**Example:** "Permission denied (see sudo requirements)" — the check tried to scan network interfaces but lacked the necessary system privileges.

**What it means for your network:** The tool couldn't assess this aspect. Either fix the underlying problem (permissions, dependencies, network access) or try again later.

### Skip

A `skip` means the check was intentionally skipped, usually because it doesn't apply to your system.

**Example:** "WiFi check not available on this platform" — you're running netglance on a Linux server with no wireless hardware, so the WiFi module is skipped.

**What it means for your network:** No information gathered here, but that's expected. Only relevant if you expected the check to run.

## Overall Health Scoring

When you run a full health report, netglance aggregates all individual check results into an overall status. The logic is simple:

- **Worst status wins.** If any check returns `error` or `fail`, your overall status is `error` or `fail` respectively. If the worst is `warn`, overall is `warn`. Only if all checks `pass` (or are `skip`) is overall `pass`.
- **Skip is invisible.** Checks with status `skip` don't influence the overall score.

This means the overall status reflects the single most serious problem on your network.

### Interpreting Your Overall Score

- **Overall: PASS** — All enabled checks passed. Your network is operating normally.
- **Overall: WARN** — One or more checks returned `warn`. Review the module breakdown to decide if action is needed.
- **Overall: FAIL** — One or more checks returned `fail`. Investigate immediately.
- **Overall: ERROR** — One or more checks encountered an error and couldn't complete. Fix the underlying issue (permissions, dependencies, etc.) and rerun.

## Reading the Per-Module Breakdown

Each report lists every module that was checked. For each, you'll see:

- **Module name** — e.g., "ping", "dns", "tls"
- **Status** — one of the 5 levels (often shown with an icon: ✔ for pass, ⚠ for warn, ✘ for fail)
- **Summary** — a one-line explanation of the result
- **Details** — list items with specifics (optional)

Here's an example of what a typical report looks like:

```
Network Health Report
Generated: 2025-02-18T14:32:15

Overall Status: WARN

## discover [OK]
Summary: Found 12 device(s) on 192.168.1.0/24
- 192.168.1.1 (aa:bb:cc:dd:ee:01) - router
- 192.168.1.10 (aa:bb:cc:dd:ee:10) - laptop
- 192.168.1.42 (aa:bb:cc:dd:ee:42) - smart-speaker
...

## ping [OK]
Summary: Gateway and internet connectivity OK
- Gateway 192.168.1.1: UP (4.2 ms)
- Internet 8.8.8.8: UP (28.5 ms)
- Internet 1.1.1.1: UP (32.1 ms)

## dns [WARNING]
Summary: DNS resolvers returned inconsistent results
- Google (8.8.8.8): 93.184.216.34, 93.184.216.35 (12.4 ms)
- Cloudflare (1.1.1.1): 93.184.216.34 (8.9 ms)

## http [OK]
Summary: No HTTP proxy detected
- https://example.com: no proxy detected
- https://google.com: no proxy detected
```

**How to read this:**
1. Look at the overall status first. It tells you if there are any problems.
2. Scan the per-module statuses for anything that isn't `pass`.
3. For each non-passing check, read the summary to understand what was found.
4. Review the details to get context (e.g., which specific DNS servers disagree, which hosts are down).

## HTML vs Terminal Reports

netglance can output reports in two formats.

### Terminal Report (Rich Output)

```bash
netglance report
```

This shows a nicely formatted table in your terminal with color-coded statuses and emoji icons. It's designed for human readability at the command line.

**Best for:**
- Quick checks while working in the terminal
- Seeing the full context of all modules at a glance
- Scripting (since `rich` renders to text, not HTML)

### HTML Report

```bash
netglance report --format html > report.html
```

This generates a standalone HTML file that you can open in a web browser. It includes:

- Color-coded status badges (green for pass, yellow for warn, red for fail)
- A summary table with all modules
- Expandable details sections (if supported)
- Responsive design that looks good on desktop and mobile

**Best for:**
- Sharing reports with others via email or file
- Archiving reports for later review
- Viewing on systems without a terminal (phone, tablet)
- Printing

Both formats show the same underlying data; HTML just makes it more shareable and visually polished.

## What Each Module's Check Means

### discover
Scans your network for connected devices using ARP, mDNS, and uPnP. Returns the count and details of each device found. A `pass` means at least one device was discovered; it's informational, not a health indicator. An `error` means the scan failed.

### ping
Tests connectivity to your gateway (router) and a few major internet hosts (Google, Cloudflare, Quad9). A `pass` means all reachable. A `warn` means partial connectivity (some hosts down). A `fail` means gateway or all internet hosts are unreachable.

### dns
Queries multiple DNS resolvers (Google, Cloudflare, Quad9) to resolve example.com and checks for consistency. A `pass` means all resolvers agree. A `warn` means slight differences. A `fail` means potential DNS hijacking (resolvers strongly diverge). Tests for DNS leak and DNSSEC as well.

### arp
Reads your local ARP table and reports the number of entries. Purely informational for now; a `pass` means the ARP table is readable. An `error` means insufficient permissions (may require `sudo`).

### tls
Fetches TLS certificates from a list of common hosts (google.com, cloudflare.com, etc.) and checks if they're trusted by your system. A `pass` means all are valid. A `warn` means some are untrusted (may be internal or self-signed). A `fail` means TLS interception detected (certificate signed by unknown CA, likely a proxy or firewall).

### http
Makes HTTP requests to test URLs and checks response headers for proxy signatures (X-Forwarded-For, etc.). A `pass` means no proxy detected. A `warn` means HTTP proxy indicators found (may be corporate, ISP, or malicious). Useful for identifying transparent proxies.

### wifi
Reports your current WiFi connection (SSID, channel, signal strength, security type). A `pass` means connected. A `warn` means not connected to WiFi (Ethernet instead). An `error` means WiFi check unavailable on your OS.

### traffic
Measures network interface activity (bytes/packets sent/received). Informational. A `pass` means data was sampled successfully. An `error` means interfaces unavailable.

### route
Performs traceroute to a destination and analyzes the path hops (IP, latency, ASN). Informational. A `pass` means destination was reached. A `fail` means path was blocked or unreachable.

### speed
Checks the database for recent speed test results (download/upload/latency). A `pass` means download ≥ 25 Mbps. A `warn` means 10–25 Mbps (slower than desired). A `fail` means < 10 Mbps (critically slow). A `skip` means no speed test data in the database yet (run `netglance speed` to collect).

### uptime
Checks the database for uptime monitoring records. A `pass` means ≥ 99% uptime. A `warn` means 95–99%. A `fail` means < 95% (frequent outages). A `skip` means no uptime data collected yet.

### baseline
Compares the current network state (devices, ARP table, open ports) to a saved baseline snapshot. A `pass` means no significant drift. A `warn` means minor differences (e.g., one new device). A `fail` means substantial changes (e.g., many devices added/removed or different open ports, suggesting security issue). A `skip` means no baseline has been saved yet (run `netglance baseline save` first).

### vpn
Checks for VPN leaks (DNS, IPv6, local IP exposure). A `pass` means no leaks detected. A `fail` means DNS or IPv6 leak found (your real IP may be exposed). A `skip` means no VPN leak test data in the database.

### dhcp
Monitors for rogue DHCP servers. A `pass` means no alerts. A `warn` means rogue server suspected. A `skip` means no DHCP monitoring data.

### ipv6
Audits IPv6 configuration (privacy extensions, EUI-64 exposure). A `pass` means privacy extensions enabled. A `warn` means EUI-64 MAC address visible in IPv6 address (fingerprinting risk). A `skip` means no IPv6 data.

## Tips for Troubleshooting

- **Start with overall status.** If it's `PASS`, no action needed. If `WARN` or `FAIL`, look at which modules are red/yellow.
- **Rerun on error.** An `error` status sometimes means transient issues (network flaky, system busy). Rerun to confirm.
- **Check dependencies.** Some checks need root or internet connectivity. Make sure your environment is set up correctly.
- **Use details.** The summary line tells you *what* happened; the details tell you *why*. Always read both.
- **Compare over time.** Run reports periodically and save them. Trends are more informative than a single snapshot.
