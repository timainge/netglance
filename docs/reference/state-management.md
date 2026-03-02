# State Management

Internal reference for how netglance stores, retrieves, and manages data across sessions.

## Architecture overview

netglance has two layers of state:

1. **Session state** — in-memory objects returned by module functions (e.g. a list of discovered devices, a ping result). These exist only for the duration of a command and are gone when the process exits.
2. **Persistent state** — SQLite database at `~/.config/netglance/netglance.db`. Data written here survives across sessions and powers baselines, metrics, alerts, and historical reports.

A third layer, **configuration**, lives in `~/.config/netglance/config.yaml` and controls daemon schedules, notification channels, and network defaults.

```
┌─────────────────────────────────────────────────────┐
│                   CLI Command                        │
├──────────┬──────────────────────────────┬────────────┤
│  Module  │   Session state (in-memory)  │   Output   │
│  func()  │   DeviceList, PingResult...  │   rich/    │
│          │                              │   stdout   │
├──────────┴──────────┬───────────────────┴────────────┤
│                     │ optional                        │
│                     ▼                                 │
│            store.save_result()                        │
│            store.save_baseline()                      │
│            store.save_metric()                        │
│                     │                                 │
│                     ▼                                 │
│   ┌─────────────────────────────────────┐            │
│   │  ~/.config/netglance/netglance.db     │            │
│   │  ┌───────────┐  ┌───────────────┐  │            │
│   │  │  results   │  │  baselines    │  │            │
│   │  ├───────────┤  ├───────────────┤  │            │
│   │  │  metrics   │  │  alert_rules  │  │            │
│   │  ├───────────┤  ├───────────────┤  │            │
│   │  │  alert_log │  │               │  │            │
│   │  └───────────┘  └───────────────┘  │            │
│   └─────────────────────────────────────┘            │
└──────────────────────────────────────────────────────┘
```

## Database tables

The Store (`netglance/store/db.py`) manages five SQLite tables. The connection uses WAL journal mode for concurrent reads and lazy-initializes on first use.

### `results` — module execution cache

Stores the JSON output of any module run. Modules opt in by calling `store.save_result()`.

| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Auto-increment |
| module | TEXT | Module name (e.g. "speed", "dns", "discover") |
| timestamp | TEXT | ISO 8601 |
| data | JSON | Serialized module result |

**Who writes:** daemon tasks (discover, dns_check, tls_verify, report). Any module _can_ write here but most don't during interactive use.

**Who reads:** `report` module reads latest results for speed, uptime, vpn, dhcp, ipv6 checks. Export reads from baselines, not results.

**Cleanup:** None automatic. Grows unbounded.

### `baselines` — network snapshots

A baseline captures a full picture of the network at a point in time: devices, ARP table, DNS state, open ports, gateway MAC.

| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Auto-increment |
| label | TEXT | User-provided or "daemon-auto" |
| timestamp | TEXT | ISO 8601 |
| data | JSON | Serialized NetworkBaseline |

**Who writes:** `netglance baseline capture` (manual), daemon baseline_diff task (automatic, labeled "daemon-auto").

**Who reads:** `netglance baseline diff` (compares current vs. last saved), `netglance baseline show`, `netglance export baseline`, `netglance export devices` (reads latest baseline for device list).

**Cleanup:** None automatic. Manual management via `baseline list`.

### `metrics` — time-series data points

Individual numeric samples tagged by metric name. Powers trending charts and sparklines.

| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Auto-increment |
| ts | TEXT | ISO 8601 |
| metric | TEXT | Dotted name (e.g. `ping.8.8.8.8.latency_ms`, `speed.download_mbps`) |
| value | REAL | Numeric measurement |
| tags | JSON | Optional metadata (e.g. `{"ssid": "MyNetwork"}`) |

**Metric names emitted by modules:**
- `ping.{host}.latency_ms`, `ping.{host}.packet_loss`
- `speed.download_mbps`, `speed.upload_mbps`, `speed.latency_ms`
- `traffic.{iface}.rx_bytes_per_sec`, `traffic.{iface}.tx_bytes_per_sec`
- `wifi.signal_dbm` (tagged with ssid)

**Cleanup:** `store.prune_metrics(older_than_days=365)` — daemon runs this daily at 3am by default. Retention configurable via `metrics.retention_days` in config.yaml.

### `alert_rules` — threshold definitions

Persistent alert rule configuration with CRUD operations.

| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Auto-increment |
| metric | TEXT | Metric name to watch |
| condition | TEXT | "above" or "below" |
| threshold | REAL | Trigger value |
| window_s | INTEGER | Evaluation window in seconds |
| enabled | INTEGER | 1/0 toggle |
| message | TEXT | Human-readable alert text |

### `alert_log` — fired alert history

Audit trail of every threshold violation.

| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Auto-increment |
| ts | TEXT | ISO 8601 |
| rule_id | INTEGER | FK to alert_rules |
| metric | TEXT | Metric that triggered |
| value | REAL | Observed value |
| threshold | REAL | Rule threshold |
| message | TEXT | Alert message |
| acknowledged | INTEGER | 1/0 ack flag |

**Cleanup:** None automatic. Grows unbounded.

## What each module persists

| Module | Session output | Writes to DB? | What gets stored |
|--------|---------------|---------------|-----------------|
| discover | Device list | Only via baseline or daemon | Devices as baseline snapshot |
| ping | PingResult | Metrics only | latency_ms, packet_loss |
| dns | DnsResult | Via daemon | Consistency check results |
| scan | ScanResult | No | — |
| arp | ArpResult | No | — |
| tls | TlsResult | Via daemon | Certificate check results |
| http | HttpResult | No | — |
| traffic | TrafficSample | Metrics only | rx/tx bytes per sec |
| route | RouteResult | No | — |
| wifi | WifiResult | Metrics only | signal_dbm |
| speed | SpeedResult | Metrics + results | download/upload/latency |
| baseline | NetworkBaseline | Yes (explicit) | Full network snapshot |
| report | HealthReport | Via daemon | Aggregate check results |
| uptime | UptimeRecord | Not yet wired | Planned but incomplete |
| alerts | — | Yes (rules + log) | Alert rules and fire history |
| trending | — | Reads only | Queries metrics table |
| export | — | Reads only | Reads baselines for export |

## CLI commands for state management

### Baselines

```bash
netglance baseline capture              # snapshot current network → DB
netglance baseline capture --label prod # snapshot with custom label
netglance baseline list                 # show all saved baselines (id, label, timestamp)
netglance baseline show <id>            # display full baseline details
netglance baseline diff                 # compare live network vs. last saved baseline
```

### Metrics

```bash
netglance metrics list                  # show all metric names in DB
netglance metrics show <name>           # chart metric over time (default 24h)
netglance metrics show <name> --period 7d  # custom time window
netglance metrics stats <name>          # min/max/avg over period
netglance metrics export                # dump to CSV or JSON
```

### Alerts

```bash
netglance alert add                     # create threshold rule (persisted)
netglance alert list                    # show all rules
netglance alert delete <id>             # remove rule
netglance alert enable <id>             # toggle on
netglance alert disable <id>            # toggle off
netglance alert log                     # show fired alert history
netglance alert ack <id>                # acknowledge a fired alert
```

### Export

```bash
netglance export devices                # export latest baseline devices as JSON/CSV/HTML
netglance export baseline               # export specific baseline by ID/label as JSON
```

### Report (reads from DB)

```bash
netglance report                        # run all checks, display results
netglance report --include-trending     # add metric sparklines from DB
netglance report --include-alerts       # add recent alert log from DB
netglance report --html-output report.html  # standalone HTML report
```

### Daemon (populates DB automatically)

```bash
netglance daemon start                  # run scheduler in foreground
netglance daemon install                # install macOS launchd plist
netglance daemon uninstall              # remove plist
netglance daemon status                 # show schedule config
```

## What's missing

### No `db` management commands

There is no CLI for directly inspecting or managing the database:
- No `netglance db status` (show DB path, size, table row counts)
- No `netglance db prune` (manually trigger retention cleanup)
- No `netglance db reset` (wipe all data)
- No `netglance db export` / `netglance db import` (full DB backup)

Metrics pruning runs only via daemon schedule. If you don't run the daemon, metrics accumulate forever.

### No result cleanup

The `results` table has no retention policy and no CLI for purging old entries.

### No baseline delete

You can list and show baselines but cannot delete individual ones.

### Uptime not wired

`UptimeRecord` and `UptimeSummary` dataclasses exist. The module computes summaries from record lists. But nothing writes uptime records to the store yet — the store integration returns empty summaries.

### No session state capture

When you run `netglance discover` or `netglance scan` interactively, the results display on screen and vanish. There's no `--save` flag or automatic result caching for interactive commands. To persist discovery results, you must run `netglance baseline capture` separately.

## Data flow examples

### "What's on my network?" (session only)

```
netglance discover → DeviceList (in-memory) → rich table → gone
```

Nothing persisted. Run `baseline capture` to save.

### "Save a snapshot and compare later"

```
netglance baseline capture → NetworkBaseline → store.save_baseline() → DB
  ... time passes ...
netglance baseline diff → capture live → diff vs. DB → show changes
```

### "Track speed over time"

```
netglance speed → SpeedResult → emit_speed_metrics(result, store) → metrics table
  ... repeat daily ...
netglance metrics show speed.download_mbps --period 30d → chart from DB
```

### "Alert me if latency spikes"

```
netglance alert add --metric ping.8.8.8.8.latency_ms --condition above --threshold 100
  → alert_rules table
  ... daemon runs ping checks ...
  → evaluate_metric_alerts() → alert_log table + notification
netglance alert log → show history
```

### "Daemon runs everything automatically"

```
netglance daemon start
  → every 15min: discover → results table
  → every hour: dns check → results table
  → daily 2am: baseline capture → baselines table (label="daemon-auto")
  → daily 3am: prune metrics older than 365 days
  → daily 7am: report → results table
```
