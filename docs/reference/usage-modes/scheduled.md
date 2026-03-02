# Scheduled Checks

> Run checks on a timer. No persistent process, no daemon overhead.

Scheduled checks use cron or systemd timers to run netglance commands at fixed intervals. Each invocation is a standalone process — it runs, saves results, and exits. No daemon, no background service, no memory footprint between runs.

## When to use this mode

- You're on Linux and prefer cron or systemd over macOS launchd
- You want lighter-weight monitoring than the full daemon
- You're running on a server or VM where the daemon feels like overkill
- You want fine-grained control over exactly which checks run when
- You're already comfortable with cron and just want to plug netglance in

## What it looks like

```bash
# crontab -e

# Ping check every 5 minutes
*/5 * * * * /usr/local/bin/netglance ping check >> /var/log/netglance/ping.log 2>&1

# Full health report every hour
0 * * * * /usr/local/bin/netglance report --json >> /var/log/netglance/report.log 2>&1

# Device discovery every 6 hours (needs root — use root's crontab)
0 */6 * * * /usr/local/bin/netglance discover >> /var/log/netglance/discover.log 2>&1

# Daily baseline snapshot at 2 AM
0 2 * * * /usr/local/bin/netglance baseline snapshot >> /var/log/netglance/baseline.log 2>&1

# Weekly HTML report on Sunday
0 3 * * 0 /usr/local/bin/netglance report --format html -o /var/log/netglance/weekly.html 2>&1
```

## Setup

### 1. Install netglance

```bash
uv tool install netglance
```

### 2. Create the log directory

```bash
sudo mkdir -p /var/log/netglance
sudo chown $USER:$USER /var/log/netglance
```

### 3. Add entries to crontab

```bash
crontab -e
```

Add the checks you want from the examples above. Save and exit.

### 4. Verify scheduling

```bash
crontab -l                              # confirm entries
tail -f /var/log/netglance/report.log   # watch for output after the next trigger
```

## Storing results

By default, netglance writes results to its SQLite database at `~/.config/netglance/netglance.db`. Scheduled checks contribute to the same data store as manual CLI runs, so `netglance metrics` and `netglance baseline diff` work on accumulated data from both.

For JSON log files, use `--json` output and pipe to a file. This is useful for external log aggregation (Loki, Elasticsearch, etc.).

## Systemd timers

For more control than cron, use systemd timers. They support randomised delays, dependencies, and better logging.

Create a service unit (`/etc/systemd/system/netglance-report.service`):

```ini
[Unit]
Description=netglance health report

[Service]
Type=oneshot
ExecStart=/usr/local/bin/netglance report --json
User=netglance
```

Create a timer unit (`/etc/systemd/system/netglance-report.timer`):

```ini
[Unit]
Description=Run netglance report hourly

[Timer]
OnCalendar=hourly
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:

```bash
sudo systemctl enable --now netglance-report.timer
sudo systemctl list-timers | grep netglance
```

## Daemon vs. scheduled checks

| | Daemon | Scheduled checks |
|--|--------|-----------------|
| **Process model** | Persistent background service | Independent one-shot runs |
| **Memory usage** | Constant (~30 MB) | Zero between runs |
| **Platform** | macOS (launchd) | Any Unix (cron, systemd) |
| **Schedule config** | YAML config file | crontab or timer units |
| **Logs** | Single daemon log file | Per-check log files |
| **Best for** | macOS desktops | Linux servers, VMs, containers |

Both approaches write results to the same SQLite database, so `netglance metrics`, `netglance baseline`, and `netglance alert` work identically regardless of which mode collected the data.

## Full reference

For crontab recipes, PATH troubleshooting, log rotation setup, and wrapper scripts, see the **[Scheduling guide](../deployment/scheduling.md)**.
