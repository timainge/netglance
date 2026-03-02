# Metrics

The metrics subcommand group queries and visualizes stored time-series data from your network monitoring runs. All netglance tools write their results as metrics (latency, throughput, signal strength, etc.), and the `metrics` command reads that data to show trends, statistics, and charts.

## What it does

The metrics system is the central data store for netglance:

- **Collects data** — Every ping, speed test, bandwidth sample, and WiFi scan writes metrics to a SQLite database.
- **Queries time series** — Retrieve raw data points for any metric over custom time ranges.
- **Renders charts** — Visualize trends with terminal-based line charts and sparklines.
- **Aggregates statistics** — Calculate min, max, average, and sample counts for any metric.
- **Exports data** — Save metrics to CSV or JSON for analysis elsewhere.
- **Manages storage** — Prune old data and list available metrics.

Metrics use a hierarchical naming scheme:
- `ping.{host}.latency_ms` — Latency to a given hostname (dots in hostname → underscores)
- `ping.{host}.packet_loss` — Packet loss percentage
- `speed.download_mbps`, `speed.upload_mbps`, `speed.latency_ms` — Speed test results
- `traffic.{interface}.rx_bytes_per_sec`, `traffic.{interface}.tx_bytes_per_sec` — Bandwidth per interface
- `wifi.signal_dbm` — WiFi signal strength with `ssid` tag

## Quick start

List all available metrics:

```bash
netglance metrics list
```

Show a 24-hour chart of ping latency to 8.8.8.8:

```bash
netglance metrics show ping.8_8_8_8.latency_ms
```

View statistics for the last 7 days:

```bash
netglance metrics stats speed.download_mbps --period 7d
```

Export all metrics from the last day:

```bash
netglance metrics export --since 24h --output my_metrics.csv
```

## Commands

### `list`

List all metric names stored in the database.

**Usage:**

```bash
netglance metrics list [OPTIONS]
```

**Options:**

- `--json` — Output as JSON array of metric names instead of a formatted table.

**Example:**

```bash
netglance metrics list
netglance metrics list --json
```

### `show`

Display a time-series chart for a metric with a sparkline summary.

**Usage:**

```bash
netglance metrics show METRIC_NAME [OPTIONS]
```

**Arguments:**

- `METRIC_NAME` — The metric to chart (e.g., `ping.google_com.latency_ms`).

**Options:**

- `--period`, `-p` — Time period to display. Format: `Xh` or `Xd` (e.g., `1h`, `6h`, `24h`, `7d`, `30d`). Default: `24h`.
- `--width` — Chart width in characters. Default: `80`.
- `--height` — Chart height in characters. Default: `20`.
- `--json` — Output raw series as JSON instead of rendering a chart.

**Example:**

```bash
# 24-hour chart of WiFi signal strength
netglance metrics show wifi.signal_dbm --period 24h

# 7-day chart with custom dimensions
netglance metrics show speed.upload_mbps --period 7d --width 120 --height 25

# Export raw data as JSON for further processing
netglance metrics show ping.1_1_1_1.packet_loss --period 7d --json
```

### `stats`

Show aggregate statistics (count, min, max, average) for a metric over a time range.

**Usage:**

```bash
netglance metrics stats METRIC_NAME [OPTIONS]
```

**Arguments:**

- `METRIC_NAME` — The metric to analyze (e.g., `speed.download_mbps`).

**Options:**

- `--period`, `-p` — Time period to analyze. Format: `Xh` or `Xd`. Default: `7d`.
- `--json` — Output statistics as JSON instead of a formatted table.

**Example:**

```bash
# 30-day stats for download speed
netglance metrics stats speed.download_mbps --period 30d

# Get yesterday's latency stats as JSON
netglance metrics stats ping.8_8_8_8.latency_ms --period 1d --json
```

### `export`

Export metrics to a CSV or JSON file for use in external tools.

**Usage:**

```bash
netglance metrics export [OPTIONS]
```

**Options:**

- `--since`, `-s` — Time period to export. Format: `Xh` or `Xd`. Default: `7d`.
- `--output`, `-o` — Output file path. Default: `metrics_export.csv`.
- `--json` — Output as JSON instead of CSV.

**Example:**

```bash
# Export last 7 days to CSV
netglance metrics export

# Export last 30 days to a specific file
netglance metrics export --since 30d --output network_metrics_jan.csv

# Export as JSON for analysis
netglance metrics export --since 7d --json
```

The CSV output includes columns: `ts` (ISO timestamp), `metric` (metric name), `value`, and `tags` (JSON string or empty).

## Understanding the output

### Metric naming

Metrics follow a dot-separated hierarchy:

- **Category.subkey.measurement** — e.g., `ping.8_8_8_8.latency_ms`
- **Special characters** — Dots in hostnames are replaced with underscores (e.g., `8.8.8.8` → `8_8_8_8`)
- **Tagged metrics** — Some metrics (e.g., `wifi.signal_dbm`) include tags stored as JSON. Use `--json` flag to see tags.

### Time ranges

All time-based options accept periods in the format `Xh` (hours) or `Xd` (days):

| Format | Example | Meaning |
|--------|---------|---------|
| `Xh` | `1h`, `6h`, `24h` | Hours (relative to now) |
| `Xd` | `1d`, `7d`, `30d` | Days (relative to now) |

Invalid formats raise an error with the expected format.

### Charts and sparklines

- **Sparkline** — A compact inline chart using Unicode block characters (▁▂▃▄▅▆▇█). Shows the trend at a glance.
- **Full chart** — A plotext line chart showing values over time. Uses the `--width` and `--height` options. If plotext is not installed, the command falls back to showing a simple table.

### Statistics fields

The `stats` command shows:

- **Count** — Number of samples in the time period
- **Min** — Lowest value observed
- **Max** — Highest value observed
- **Avg** — Average of all samples (or `--` if no data)

## Related concepts

- **[Daemon](daemon.md)** — The background scheduler collects metrics automatically.
- **[Alerts](alert.md)** — Set thresholds on metrics and receive notifications.
- **[Baseline](baseline.md)** — Capture and compare network snapshots.
- **Export** — Use metrics export to integrate with external analytics platforms.

## Troubleshooting

### No metrics found

If `netglance metrics list` shows no data:

1. Run a module directly (e.g., `netglance ping 8.8.8.8`) to generate metrics.
2. Check that the daemon is running: `netglance daemon status`
3. Confirm the database file exists: `~/.config/netglance/netglance.db`

### Time range not recognized

Ensure periods use the format `Xh` or `Xd` (not `Xdays` or `X hours`):

```bash
# Correct
netglance metrics show ping.example_com.latency_ms --period 24h

# Incorrect (will fail)
netglance metrics show ping.example_com.latency_ms --period 1 day
```

### Chart not rendering

If you see "Could not render chart", the system falls back to a table. This happens when:

- The `plotext` library is not installed (optional dependency)
- There is no data for the metric in the requested period

Install plotext for chart support: `uv pip install plotext`

### Database size growing

Metrics accumulate over time. Prune old data to save space:

1. Use the daemon configuration to enable auto-pruning.
2. Or manually prune via Python: `from netglance.store.db import Store; Store().prune_metrics(older_than_days=90)`

The default retention is unlimited. Plan for disk usage if running the daemon continuously.
