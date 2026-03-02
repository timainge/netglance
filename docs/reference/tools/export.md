# Export Tool

Export your network inventory and baseline snapshots in JSON, CSV, or HTML formats for sharing, archiving, and analysis.

## What it does

The `export` command lets you save network discovery and scan data in multiple formats:

- **JSON** — Machine-readable format, preserves all metadata and timestamps, suitable for automation and scripting
- **CSV** — Spreadsheet-friendly format with columns for IP, MAC, hostname, vendor, discovery method, timestamps, and open ports
- **HTML** — Standalone web page with styled table, easy to share and view in any browser

Export supports two data sources:

1. **Device inventory** — Export devices discovered in your latest baseline (or any baseline by label)
2. **Full baseline** — Export the complete baseline snapshot including all device and port data as JSON

## Quick start

Export devices to JSON and print to stdout:
```bash
netglance export devices
```

Export devices to CSV file:
```bash
netglance export devices --format csv --output inventory.csv
```

Export as HTML report:
```bash
netglance export devices --format html --output devices.html
open devices.html  # macOS
```

Export a specific baseline by label:
```bash
netglance export baseline --label "before_update" --output baseline-backup.json
```

## Commands

### `netglance export devices`

Export device inventory from the latest baseline.

**Options:**

- `--format`, `-f` — Output format: `json`, `csv`, or `html` (default: `json`)
- `--output`, `-o` — Write to file; if not specified, prints to stdout

**Examples:**

```bash
# JSON to stdout
netglance export devices

# CSV file
netglance export devices --format csv --output /tmp/devices.csv

# HTML file
netglance export devices --format html -o report.html

# Short flags
netglance export devices -f json -o output.json
```

### `netglance export baseline`

Export the latest baseline (or a specific baseline by label) as JSON.

**Options:**

- `--label`, `-l` — Export baseline with this specific label (searches all stored baselines)
- `--output`, `-o` — Write to file; if not specified, prints to stdout

**Examples:**

```bash
# Latest baseline to stdout
netglance export baseline

# Save latest baseline
netglance export baseline --output latest.json

# Export baseline by label
netglance export baseline --label "pre-maintenance" --output backup.json
```

## Understanding the output

### JSON device export

Structure per device:

```json
{
  "ip": "192.168.1.10",
  "mac": "aa:bb:cc:dd:ee:ff",
  "hostname": "mydevice",
  "vendor": "Apple Inc.",
  "discovery_method": "arp",
  "first_seen": "2025-02-15T14:22:30.123456",
  "last_seen": "2025-02-18T09:15:45.654321",
  "open_ports": [
    {
      "port": 22,
      "state": "open",
      "service": "ssh",
      "version": "OpenSSH 7.4",
      "banner": null
    }
  ]
}
```

**Fields:**

- `ip` — Device IP address
- `mac` — MAC address
- `hostname` — Device hostname (or empty)
- `vendor` — OUI vendor lookup (or empty)
- `discovery_method` — How found: `arp`, `mdns`, `upnp`, etc.
- `first_seen` / `last_seen` — ISO 8601 timestamps
- `open_ports` — Array of ports discovered by scanning

### CSV device export

Columns: `ip`, `mac`, `hostname`, `vendor`, `discovery_method`, `first_seen`, `last_seen`, `open_ports`

The `open_ports` column is a comma-separated list of port numbers (e.g., `22,80,443`).

### HTML device export

Self-contained HTML page with:

- Dark theme (GitHub-style)
- Responsive table with IP, MAC, hostname, vendor, discovery method, timestamps, and open ports
- Metadata footer showing generation timestamp and device count
- No external dependencies — opens in any browser

### JSON baseline export

Complete baseline snapshot:

```json
{
  "id": "baseline-uuid",
  "timestamp": "2025-02-18T09:15:45",
  "label": "daily-scan",
  "devices": [ /* array of device objects */ ],
  "open_ports": {
    "192.168.1.10": [ /* array of port objects */ ]
  }
}
```

## Related concepts

- **[Baseline tool](../tools/baseline.md)** — Create and manage baseline snapshots
- **[Discover tool](../tools/discover.md)** — Discover devices on your network
- **[Scan tool](../tools/scan.md)** — Scan for open ports and services
- **[Report tool](../tools/report.md)** — Generate comprehensive health reports

## Troubleshooting

**No baseline found error**

If you see `No baseline found in store`, you must create a baseline first:

```bash
netglance baseline take
netglance export devices
```

**Large CSV files with Excel**

Excel may have issues with large CSV files or encoding. Open with a text editor or import into Google Sheets instead.

**JSON output with pipes**

Filter or transform JSON exports using `jq`:

```bash
netglance export devices | jq '.[] | {ip, hostname, vendor}'
netglance export devices | jq '.[] | select(.vendor | contains("Apple"))'
```

**Baseline label not found**

List available baselines to find the correct label:

```bash
netglance baseline list  # Shows all baselines with labels
```

**HTML report rendering**

If the HTML report doesn't render correctly, ensure you're opening it in a modern browser (Chrome, Safari, Firefox, Edge). Dark mode will use system preference if supported.
