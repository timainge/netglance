# Documentation

Install netglance, learn the commands, and deploy it on your network.

---

## Install

=== "uv (recommended)"

    ```bash
    uv tool install netglance
    ```

=== "pip"

    ```bash
    pip install netglance
    ```

---

## Get started

**[Getting Started](getting-started.md)** — Install, discover your devices, and run your first health report in under 5 minutes.

---

## Usage modes

**[Usage Modes](usage-modes/index.md)** — Interactive CLI, AI agent (MCP), background daemon, dedicated hardware, or scheduled checks. Pick how you want to run netglance.

---

## Commands

**Find your devices, know your network:**

- **[discover](tools/discover.md)** — Find every device on your network
- **[scan](tools/scan.md)** — See open ports and running services
- **[identify](tools/identify.md)** — Figure out what a device actually is
- **[export](tools/export.md)** — Save your inventory as JSON, CSV, or HTML
- **[baseline](tools/baseline.md)** — Snapshot your network and detect changes

**Test your connection:**

- **[ping](tools/ping.md)** — Connectivity and latency checks
- **[speed](tools/speed.md)** — Download/upload speed tests
- **[perf](tools/perf.md)** — Jitter, path MTU, bufferbloat detection
- **[route](tools/route.md)** — Trace traffic paths and find slowdowns
- **[uptime](tools/uptime.md)** — Track which hosts are up and when they go down
- **[traffic](tools/traffic.md)** — Real-time bandwidth usage per interface

**Check your security:**

- **[dns](tools/dns.md)** — DNS resolver trust, DNSSEC, hijacking detection
- **[arp](tools/arp.md)** — ARP spoofing and man-in-the-middle detection
- **[tls](tools/tls.md)** — Certificate verification and interception detection
- **[http](tools/http.md)** — Proxy injection and suspicious headers
- **[vpn](tools/vpn.md)** — DNS and IPv6 leak detection
- **[dhcp](tools/dhcp.md)** — Rogue DHCP server detection
- **[firewall](tools/firewall.md)** — Test what your firewall actually blocks
- **[ipv6](tools/ipv6.md)** — IPv6 neighbors, privacy extensions, dual-stack
- **[wifi](tools/wifi.md)** — Wireless security, channels, rogue access points

**Monitor and get alerted:**

- **[report](tools/report.md)** — Unified health assessment across all checks
- **[metrics](tools/metrics.md)** — Historical data, charts, and sparklines
- **[alert](tools/alert.md)** — Threshold-based notifications
- **[daemon](tools/daemon.md)** — Background scheduled checks

**Utilities:**

- **[wol](tools/wol.md)** — Wake-on-LAN magic packets

**AI Integration:**

- **[mcp](tools/mcp.md)** — MCP server for Claude, Cursor, VS Code, and other AI clients

---

## Deploy

Run netglance 24/7 on your network:

- **[Raspberry Pi](deployment/raspberry-pi.md)** — Dedicated always-on monitor
- **[macOS Daemon](deployment/mac-mini-daemon.md)** — Set-and-forget with launchd
- **[Docker](deployment/docker.md)** — Containerized deployment
- **[Cron & Timers](deployment/scheduling.md)** — Lightweight scheduling
