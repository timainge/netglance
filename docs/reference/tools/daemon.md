# Daemon

## What it does

The `netglance daemon` manages a background monitoring service that runs scheduled network checks on a cron-like schedule. It automatically discovers devices, monitors DNS integrity, verifies TLS certificates, captures network baselines, and generates periodic health reports. Results are stored in SQLite for later analysis and alerting.

On macOS, the daemon integrates with **launchd** for automatic start-on-login and persistent operation.

## Quick start

**Start the daemon in the foreground** (for testing or manual use):

```bash
netglance daemon start
```

**Install as a macOS launchd service** (runs automatically on login):

```bash
netglance daemon install
netglance daemon status
```

**Check daemon and schedule status**:

```bash
netglance daemon status
```

## Commands

### `netglance daemon start`

Start the scheduler in the foreground. Useful for testing or initial setup.

**Flags:**

- `--config PATH`, `-c PATH` — Path to a YAML config file (optional). If not provided, uses system defaults.

**Example:**

```bash
netglance daemon start --config ~/.config/netglance/config.yaml
```

The daemon will display a table of scheduled tasks and run them according to their cron expressions. Press **Ctrl+C** to stop.

### `netglance daemon install`

Generate and install the launchd plist file at `~/Library/LaunchAgents/com.netglance.daemon.plist`. This enables auto-start on login.

**Flags:**

- `--netglance-path PATH` — Override the path to the netglance executable. Auto-detected if not specified.
- `--config PATH`, `-c PATH` — Path to a YAML config file for the daemon (optional).

**Example:**

```bash
netglance daemon install --config ~/.config/netglance/config.yaml
```

After installation, the plist is loaded automatically. You can manually load or unload it with:

```bash
launchctl load ~/Library/LaunchAgents/com.netglance.daemon.plist
launchctl unload ~/Library/LaunchAgents/com.netglance.daemon.plist
```

### `netglance daemon uninstall`

Remove the launchd plist file. The daemon will no longer start automatically.

**Example:**

```bash
netglance daemon uninstall
```

### `netglance daemon status`

Display the current daemon installation and configuration status, including all scheduled tasks and their cron expressions.

**Example:**

```bash
netglance daemon status
```

## Understanding the output

### Scheduled tasks table

When you start the daemon, you'll see a table showing all active scheduled tasks:

```
netglance daemon starting

┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Task          ┃ Schedule        ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ discover      │ */15 * * * *    │
│ dns_check     │ 0 * * * *      │
│ tls_verify    │ 0 */6 * * *    │
│ baseline_diff │ 0 2 * * *      │
│ report        │ 0 7 * * *      │
└───────────────┴─────────────────┘
```

Each task runs according to its **cron expression**:

- **discover** — Device discovery every 15 minutes
- **dns_check** — DNS consistency check hourly
- **tls_verify** — TLS certificate verification every 6 hours
- **baseline_diff** — Network baseline capture daily at 2 AM
- **report** — Health report generation daily at 7 AM

### Cron expression format

Daemon schedules use standard 5-field cron syntax: `minute hour day-of-month month day-of-week`

Common patterns:

- `*/15 * * * *` — Every 15 minutes
- `0 * * * *` — Every hour at minute 0
- `0 2 * * *` — Daily at 2 AM
- `0 */6 * * *` — Every 6 hours

### Daemon logs

On macOS, daemon output is written to:

```
~/.config/netglance/daemon.log
```

Check the log if tasks are failing silently:

```bash
tail -f ~/.config/netglance/daemon.log
```

### Results storage

All check results are stored in SQLite:

```
~/.config/netglance/netglance.db
```

Each task saves its result under a key: `discover`, `dns_check`, `tls_verify`, `baseline_diff`, `report`.

## Related concepts

- **[Baseline](./baseline.md)** — Capture and compare network snapshots to detect changes
- **[Alert](./alert.md)** — Evaluate rules against daemon results and trigger notifications
- **[Metrics](./metrics.md)** — Query and analyze stored results over time

## Troubleshooting

### Daemon fails to start

**Check for permission issues:**

```bash
ls -la ~/Library/LaunchAgents/
```

The plist file should be readable. If permissions are wrong:

```bash
chmod 644 ~/Library/LaunchAgents/com.netglance.daemon.plist
```

**Check if the netglance binary is found:**

```bash
which netglance
netglance --version
```

If not found, reinstall with:

```bash
netglance daemon install --netglance-path /absolute/path/to/netglance
```

### launchd plist not loading

Verify the plist is valid:

```bash
plutil ~/Library/LaunchAgents/com.netglance.daemon.plist
```

If invalid, reinstall:

```bash
netglance daemon uninstall
netglance daemon install
```

Load it manually:

```bash
launchctl load ~/Library/LaunchAgents/com.netglance.daemon.plist
```

### High CPU or memory usage

The scheduler checks tasks once per minute. If a single task is taking too long (e.g., scanning a large subnet), reduce the frequency in your config:

```yaml
daemon:
  schedules:
    discover: "0 */4 * * *"  # Every 4 hours instead of every 15 minutes
```

### Checks failing silently

Check daemon logs:

```bash
tail -50 ~/.config/netglance/daemon.log
```

Common issues:

- Network interface not specified or invalid
- Subnet unreachable from current network
- Insufficient permissions for ARP or raw socket operations

### Database locked errors

If you run `netglance` CLI commands while the daemon is running, you may see "database locked" warnings. This is normal and usually brief. To avoid contention:

1. Stop the daemon before running intensive CLI operations
2. Increase metric retention or prune frequency if the database grows large
3. Run CLI commands during off-peak times (not during daemon check windows)
