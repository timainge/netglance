# Health Report

> Run all network checks at once and get a unified health score with per-module breakdown.

## What it does

`netglance report` is the "run everything" command. It executes all available checks (device discovery, connectivity, DNS, ARP, TLS certificates, HTTP proxy detection, WiFi status, and any test data from the database like speed tests and uptime) and aggregates the results into a single report with an overall health score and per-module status.

This is the best starting point for understanding your network's health at a glance. Instead of running individual commands, you get a complete picture: what's working, what needs attention, and what failed to run.

## Quick start

Basic report to the terminal:
```bash
netglance report
```

Save as markdown file:
```bash
netglance report --output report.md
```

Generate an HTML report for sharing or archiving:
```bash
netglance report --html --html-output report.html
```

Check only specific modules:
```bash
netglance report --modules discover,dns,ping
```

JSON output for scripting or parsing:
```bash
netglance report --json
```

## Commands

### `netglance report`

Run all health checks and display results.

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--modules` | `-m` | string | None | Comma-separated list of modules to check (e.g., `discover,dns,tls`). If omitted, all modules run. |
| `--output` | `-o` | path | None | Save report as markdown to this file path. |
| `--json` | — | flag | false | Output report as JSON instead of formatted text. |
| `--subnet` | `-s` | string | 192.168.1.0/24 | Network subnet for device discovery. |
| `--html` | — | flag | false | Generate HTML report. |
| `--html-output` | — | path | None | Save HTML report to this file path. If omitted with `--html`, prints HTML to stdout. |
| `--include-trending` | — | flag | false | Include metric sparkline charts (24-hour trends) in HTML report. Requires database access. |
| `--include-alerts` | — | flag | false | Include recent alert history table in HTML report. Requires database access. |

#### Available modules

The following modules can be checked:

- `discover` — Find devices on your network (ARP, mDNS, uPnP).
- `ping` — Test gateway and internet connectivity.
- `dns` — Check DNS consistency and detect hijacking.
- `arp` — Monitor ARP table for anomalies.
- `tls` — Verify TLS certificates on default sites.
- `http` — Detect HTTP proxies.
- `wifi` — Report current WiFi connection info.
- `speed` — Last speed test result (from database).
- `uptime` — Uptime monitoring status (from database).
- `vpn` — VPN leak detection results (from database).
- `dhcp` — DHCP rogue server detection (from database).
- `ipv6` — IPv6 privacy and leak analysis (from database).

## Understanding the output

### Terminal output

The report displays an overall health status banner followed by a colored panel for each module:

```
Network Health Report
Overall: PASS

✔ discover - PASS
Found 12 device(s) on 192.168.1.0/24
  192.168.1.100 (aa:bb:cc:dd:ee:ff) - router
  192.168.1.101 (11:22:33:44:55:66) - laptop

✔ ping - PASS
Gateway and internet connectivity OK
  Gateway 192.168.1.1: UP (5.2 ms)
  Internet 8.8.8.8: UP (23.4 ms)

⚠ dns - WARN
DNS resolvers returned inconsistent results
  ...
```

### Overall status meanings

The overall status is the worst status from any module:

- **PASS** (green) — All checks passed, no issues detected.
- **WARN** (yellow) — Minor concerns detected (e.g., slow DNS, partial connectivity). Network is functional but may need investigation.
- **FAIL** (red) — Problems detected (e.g., all DNS resolvers hijacked, TLS interception). Network has real issues.
- **ERROR** (red bold) — One or more checks failed to run entirely (e.g., permission denied, network unreachable).

### Per-module status

Each module gets a status label:

| Status | Meaning |
|--------|---------|
| **PASS** | No issues detected; everything works as expected. |
| **WARN** | Minor concerns or degradation; functionality is maintained but should be monitored. |
| **FAIL** | Problems detected; functionality is impaired or blocked. |
| **ERROR** | Check could not run (permission denied, missing tools, network errors). |
| **SKIP** | Module disabled, not applicable on this platform, or no data available. |

### Module-specific indicators

- **discover** — Pass if devices found; error if no network interface detected.
- **ping** — Pass if both gateway and internet up; warn if one is down; fail if all down.
- **dns** — Pass if resolvers agree; warn if inconsistent; fail if potential hijack detected.
- **arp** — Pass if table readable (informational); error if requires root.
- **tls** — Pass if all certs trusted; warn if some untrusted; fail if interception detected.
- **http** — Pass if no proxy detected; warn if proxy headers found.
- **wifi** — Pass if connected; warn if not connected or on this platform.
- **speed** — Pass if download ≥ 25 Mbps; warn if 10–24 Mbps; fail if < 10 Mbps; skip if no test run yet.
- **uptime** — Pass if ≥ 99%; warn if 95–99%; fail if < 95%; skip if not monitored.
- **vpn** — Pass if no leaks; fail if DNS or IPv6 leaks detected; skip if never checked.
- **dhcp** — Pass if no rogue servers; warn if rogue servers detected; skip if never monitored.
- **ipv6** — Pass if privacy extensions enabled; warn if EUI-64 exposed; skip if no IPv6 data.

## HTML reports

The `--html` flag generates a standalone HTML report with inline CSS and no external dependencies. This is useful for sharing, archiving, or viewing in a browser.

```bash
netglance report --html --html-output ~/Downloads/report.html
```

The HTML report includes:

- Overall health status banner with color coding.
- Module summary table with status icons, labels, and details.
- Optional metric sparklines (24-hour trends) with `--include-trending`.
- Optional alert history table with `--include-alerts`.

To view in your default browser:
```bash
netglance report --html --html-output report.html && open report.html
```

## Trending and history

Reports can be compared over time to spot network degradation or improvement. The database stores results from previous checks, and the `--include-trending` flag pulls the last 24 hours of metric data to render as sparkline charts in the HTML report.

Example with trending and alerts:
```bash
netglance report --html --html-output report.html --include-trending --include-alerts
```

This adds two sections to the HTML:
1. **Metric Trends** — Charts showing how metrics (download speed, latency, uptime %) changed over 24 hours.
2. **Recent Alerts** — A table of the last 20 alerts, with timestamps, thresholds, and acknowledgment status.

## Targeting specific modules

If a full report is slow or you only care about certain modules, use `--modules`:

```bash
# Only connectivity and DNS
netglance report --modules ping,dns

# Only security checks
netglance report --modules tls,http,vpn
```

This runs faster and produces a shorter report.

## Output formats

### Terminal (default)

Colored, richly formatted output with panels and icons:
```bash
netglance report
```

### Markdown

Plain markdown, suitable for email, docs, or version control:
```bash
netglance report --output report.md
```

### JSON

Machine-readable format for scripting or integration:
```bash
netglance report --json | jq '.checks[] | select(.status == "fail")'
```

### HTML

Standalone HTML with inline styles for sharing:
```bash
netglance report --html --html-output report.html
```

## Troubleshooting

### Some modules show ERROR or SKIP

**Why:** Some checks require elevated privileges (root or sudo) or are not applicable on your platform.

- **arp** — Requires `sudo` to read the ARP table. Run with `sudo netglance report` if needed.
- **wifi** — Skipped on non-macOS platforms; only macOS is supported.
- **speed, uptime, vpn, dhcp, ipv6** — Skipped if no data exists in the database (e.g., no speed tests run yet).

**Fix:** Run the individual module to collect data first, then run the report again.

### Report is slow

**Why:** Some checks are inherently slow:

- **discover** — Scans the network for devices (typically 1–2 seconds per /24 subnet).
- **tls** — Connects to multiple hosts and checks certificates (2–5 seconds).
- **http** — Makes HTTP requests to check for proxy headers.

**Fix:** Skip slow modules with `--modules`:
```bash
netglance report --modules ping,dns
```

### Empty or partial report

**Why:** Network interface not detected, no WiFi connection, or no database initialized.

**Fix:**
1. Check network connectivity: `netglance ping`
2. Verify database: `netglance speed --help` (initialize the DB if needed).
3. Use `--subnet` to specify the correct subnet for discovery.

## Related concepts

- [Reading Reports](../../guide/interpreting-results/reading-reports.md) — Deeper guidance on interpreting results and deciding what to fix.
