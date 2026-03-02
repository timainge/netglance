# Scheduling Checks

Run netglance checks automatically on a schedule without the overhead of the full daemon. Use cron, systemd timers, or a lightweight wrapper script to fit your infrastructure.

## Why Schedule Instead of Using Daemon Mode

The daemon mode (`netglance daemon install`) is convenient on macOS, but scheduling checks directly offers several advantages:

- **Lightweight**: No persistent process consuming memory or system resources
- **Flexible**: Run different checks at different intervals — a ping every 5 minutes, a full report every hour, device discovery weekly
- **Portable**: Works on any Unix system with cron or systemd, not just macOS
- **Observable**: Each run is independent; logs are straightforward to inspect and debug
- **Composable**: Combine multiple checks in a shell script with custom error handling

## Crontab Scheduling

Edit your crontab with `crontab -e`. The format is `minute hour day month weekday command`. All times are in your local timezone.

### Quick Reference

```bash
# Every 5 minutes: quick ping check
*/5 * * * * /usr/local/bin/netglance ping check >> /var/log/netglance-ping.log 2>&1

# Every hour: full health report
0 * * * * /usr/local/bin/netglance report >> /var/log/netglance-report.log 2>&1

# Every 6 hours: device discovery + baseline diff
0 */6 * * * /usr/local/bin/netglance discover scan && /usr/local/bin/netglance baseline diff >> /var/log/netglance-discover.log 2>&1

# Daily at 2:00 AM: comprehensive scan + HTML report
0 2 * * * /usr/local/bin/netglance report --format html -o /tmp/netglance-daily-$(date +\%Y\%m\%d).html >> /var/log/netglance-daily.log 2>&1

# Weekly on Sunday at 3:00 AM: full baseline snapshot
0 3 * * 0 /usr/local/bin/netglance baseline snapshot >> /var/log/netglance-baseline.log 2>&1
```

### PATH and Binary Location

Cron runs with a minimal PATH and no shell initialization. Either:

1. Use the full path to netglance (if installed system-wide):
   ```bash
   0 * * * * /usr/local/bin/netglance report
   ```

2. Or add PATH to the top of your crontab:
   ```bash
   PATH=/usr/local/bin:/usr/bin:/bin
   0 * * * * netglance report
   ```

3. If using `uv run` for development:
   ```bash
   0 * * * * cd /path/to/netglance && /usr/bin/uv run netglance report
   ```

### Log Rotation

Redirect output to a log file with `>> /var/log/netglance.log 2>&1`. On macOS, use `/var/log/` (requires sudo to edit crontab) or `~/Library/Logs/`. On Linux, logrotate handles rotation automatically. For manual rotation:

```bash
# On macOS or Linux
0 0 * * 0 gzip /var/log/netglance.log && mv /var/log/netglance.log.gz /var/log/netglance.log.$(date +\%Y\%m\%d).gz
0 0 * * * /usr/local/bin/netglance report > /var/log/netglance.log 2>&1
```

## Systemd Timer Alternative (Linux)

Systemd timers offer better integration with Linux services, automatic logging via journald, and dependency management.

### Service File

Create `/etc/systemd/system/netglance-healthcheck.service`:

```ini
[Unit]
Description=netglance health check
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/netglance report
StandardOutput=journal
StandardError=journal
User=root
```

### Timer File

Create `/etc/systemd/system/netglance-healthcheck.timer`:

```ini
[Unit]
Description=Run netglance health check hourly
Requires=netglance-healthcheck.service

[Timer]
OnBootSec=2min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
```

### Enable and Verify

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now netglance-healthcheck.timer
sudo systemctl list-timers netglance-healthcheck.timer
sudo journalctl -u netglance-healthcheck.service -f  # Watch logs
```

## Preventing Overlapping Runs

If a check takes longer than your schedule interval, prevent concurrent runs with `flock`:

```bash
# In crontab or systemd service
0 * * * * /usr/bin/flock -n /tmp/netglance.lock /usr/local/bin/netglance report >> /var/log/netglance.log 2>&1
```

The `-n` flag makes flock non-blocking — if another instance is running, the new one exits silently instead of waiting.

## Timeout Protection

Protect against hung or runaway checks:

```bash
# Kill the check if it runs longer than 5 minutes (300 seconds)
0 * * * * timeout 300 /usr/local/bin/netglance report >> /var/log/netglance.log 2>&1
```

## Wrapper Script for Multiple Checks

For more complex scheduling, create a wrapper script at `/usr/local/bin/netglance-scheduled.sh`:

```bash
#!/bin/bash
set -e

LOG="/var/log/netglance-scheduled.log"
ERROR_LOG="/var/log/netglance-errors.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

on_error() {
    log "ERROR: Check failed with exit code $?"
    echo "netglance check failed at $(date)" >> "$ERROR_LOG"
    exit 1
}

trap on_error ERR

log "Starting scheduled checks"

# Quick connectivity check
timeout 60 /usr/local/bin/netglance ping check >> "$LOG" 2>&1
log "Ping check completed"

# DNS health check
timeout 60 /usr/local/bin/netglance dns check >> "$LOG" 2>&1
log "DNS check completed"

# Device discovery
timeout 120 /usr/local/bin/netglance discover scan >> "$LOG" 2>&1
log "Discovery completed"

# Generate HTML report
REPORT="/tmp/netglance-report-$(date +%Y%m%d-%H%M%S).html"
timeout 300 /usr/local/bin/netglance report --format html -o "$REPORT" >> "$LOG" 2>&1
log "Report saved to $REPORT"

log "All checks completed successfully"
```

Make it executable:

```bash
chmod +x /usr/local/bin/netglance-scheduled.sh
```

Then schedule it in crontab:

```bash
0 * * * * /usr/local/bin/netglance-scheduled.sh
```

## Email Notifications on Failure

Install `cronic` (simple bash wrapper) to email only on failure:

```bash
# On macOS
brew install cronic

# On Linux (Debian/Ubuntu)
sudo apt install cronic

# In crontab
0 * * * * cronic /usr/local/bin/netglance report
# Emails output only if non-zero exit code
```

Or use a simple bash wrapper:

```bash
RESULT=$(/usr/local/bin/netglance report 2>&1)
STATUS=$?
if [ $STATUS -ne 0 ]; then
    echo "$RESULT" | mail -s "netglance check failed" admin@example.com
fi
exit $STATUS
```

## Comparison: Cron vs Daemon vs Systemd Timer

| Approach | Overhead | Portability | Logging | Error Handling | Best For |
|----------|----------|-------------|---------|----------------|----------|
| **Cron** | Very low | Universal (any Unix) | Manual file rotation | Simple shell traps | Lightweight, simple intervals |
| **Daemon mode** | Medium (persistent process) | macOS only | Built-in launchd logs | Native macOS integration | Always-on macOS monitoring |
| **Systemd timer** | Low | Linux only | journald (integrated) | Service dependencies | Modern Linux systems |

Choose **cron** for portability and simplicity. Choose **systemd timers** on Linux for better integration and logging. Use **daemon mode** on macOS if you want a persistent process with native system integration.
