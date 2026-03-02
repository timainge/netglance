# Uptime Monitoring

The `netglance uptime` tool tracks host availability over time. It records whether targets are reachable, detects outage windows, and calculates uptime percentages to help you understand reliability patterns and service quality.

## What it does

Uptime monitoring performs periodic reachability checks (using ping) against hosts and records the results. The tool:

- **Checks current status** — performs a live ping to see if a host is up right now
- **Queries history** — retrieves stored records from the database over a time period
- **Calculates uptime %** — shows what percentage of checks succeeded (e.g., 99.5% = 3.6 hours downtime per month)
- **Identifies outages** — detects consecutive down periods, records their start/end times and duration
- **Tracks latency** — records round-trip times for each check to spot degradation
- **Shows status** — reports last successful check time and current up/down status

## Quick start

Check if a host is currently up and see its 24-hour uptime:

```bash
netglance uptime check 8.8.8.8
```

View uptime over the last 7 days:

```bash
netglance uptime check example.com --period 7d
```

Query stored history without a live check (useful if the host is known to be down):

```bash
netglance uptime summary 192.168.1.1 --period 24h
```

Get JSON output for scripting:

```bash
netglance uptime check 8.8.8.8 --json
```

## Commands

### `netglance uptime check`

Perform a live ping and display the current status plus stored uptime summary.

**Arguments:**
- `HOST` (required) — IP address or hostname to check (e.g., `8.8.8.8` or `example.com`)

**Options:**
- `--period, -p` — Time window for historical summary (default: `24h`). Accepts `1h`, `6h`, `12h`, `24h`, `2d`, `7d`, `30d`, or custom formats like `48h`, `3d`.
- `--timeout, -t` — Seconds to wait for each ping reply (default: `2.0`)
- `--json` — Output as machine-readable JSON instead of formatted tables

**Example:**
```bash
netglance uptime check 1.1.1.1 --period 7d --timeout 3.0
netglance uptime check example.com --json
```

### `netglance uptime summary`

Show stored uptime history without performing a live check. Useful when a host is down and you want historical context only.

**Arguments:**
- `HOST` (required) — IP address or hostname

**Options:**
- `--period, -p` — Historical window (default: `24h`)
- `--json` — Output as JSON

**Example:**
```bash
netglance uptime summary 192.168.1.1 --period 24h
netglance uptime summary gateway.local --json
```

### `netglance uptime list`

List all monitored hosts in the database.

**Options:**
- `--json` — Output as JSON

**Status:** This command is a placeholder. Store integration is pending. Run `uptime check` to perform live checks.

## Understanding the output

### Uptime percentage

Uptime is calculated as `(successful checks / total checks) × 100%`. For example:

- **99.9%** = ~8.7 hours downtime per year (~7.2 minutes per day)
- **99.5%** = ~43.8 hours downtime per year (~3.6 minutes per day)
- **99.0%** = ~87.6 hours downtime per year (~7.2 minutes per day)
- **95.0%** = ~438 hours downtime per year (~36 minutes per day)

Higher percentages indicate more reliable services. Most SLAs target 99.0%–99.99% ("three-nines" to "four-nines").

### Status indicators

- **[UP]** (green) — Host responded to the most recent check
- **[DOWN]** (red) — Host did not respond to the most recent check
- **[unknown]** (dim) — No checks recorded yet

### Outage duration format

Outages are reported in the most readable unit:

- `45s` — 45 seconds
- `3.2m` — 3.2 minutes
- `1.5h` — 1.5 hours

### Latency

Average round-trip time in milliseconds. Higher latency may indicate network congestion or distant targets. `--` means no successful checks were recorded.

### Checks count

Shows `successful_checks / total_checks`. For example, `48 / 50` means 48 successful pings out of 50 total attempts (96% uptime).

## Related concepts

- **[Ping tool](./ping.md)** — On-demand connectivity checks and latency measurement
- **[Daemon](./daemon.md)** — Continuous background monitoring (required for uptime history)
- **[Alert](./alert.md)** — Notifications when hosts go down or come back up
- **[Baseline](./baseline.md)** — Snapshot network state to track changes over time

## Troubleshooting

**"No data found" or empty outage list**

The database has no historical records for this host. Either:
- The daemon has not been running (needed for continuous monitoring)
- The host was not previously checked
- The time period is too old and records have been purged

Start the daemon to begin collecting baseline data:
```bash
netglance daemon start
```

**Outages look suspicious or too short**

Short outages might be missed if the check interval is too long. By default, the daemon checks every 60 seconds. If an outage lasts only 10 seconds, only 1–2 checks may catch it. Reduce the check interval in your daemon config for finer granularity.

**Latency is very high or missing**

High latency may indicate network issues. Missing latency (`--`) means no successful checks recorded, so latency could not be measured. Check that the host is reachable via `ping` manually first:
```bash
ping example.com
```

**Uptime looks wrong for a host I know is reliable**

Verify your local network and ISP connectivity first. The tool measures reachability *from your network to the target*. Temporary local network glitches appear as target downtime. Check your router and DNS:
```bash
netglance dns check 8.8.8.8
netglance route trace example.com
```

**Timestamps are in the wrong timezone**

Timestamps are stored in UTC and displayed in your system timezone via `strftime()`. Check that your system clock and timezone are correct:
```bash
date
timedatectl  # on Linux; use `systemsetup -gettimezone` on macOS
```
