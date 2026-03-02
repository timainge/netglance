# Background Daemon

> Set it up once. Let it watch your network around the clock.

The background daemon runs netglance as a persistent service on your primary machine. It executes scheduled checks — device discovery, DNS verification, TLS certificate checks, health reports — and stores every result in SQLite. When something changes or breaks a threshold, it triggers alerts.

## When to use this mode

- You want continuous monitoring without manual effort
- You care about trends over time — is my network getting slower? Are new devices appearing?
- You want alerts when something goes wrong (new device, DNS hijack, certificate expiry)
- Your machine is on most of the time (desktop Mac, always-on laptop)
- You don't want to set up dedicated hardware

## What it looks like

```console
$ netglance daemon install
✓ Installed launchd plist at ~/Library/LaunchAgents/com.netglance.daemon.plist
✓ Daemon loaded and running

$ netglance daemon status
Daemon: running (pid 4821)

┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Task          ┃ Schedule        ┃ Last Run            ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ discover      │ */15 * * * *    │ 2 min ago ✓         │
│ dns_check     │ 0 * * * *      │ 18 min ago ✓        │
│ tls_verify    │ 0 */6 * * *    │ 3 hours ago ✓       │
│ baseline_diff │ 0 2 * * *      │ 14 hours ago ✓      │
│ report        │ 0 7 * * *      │ 9 hours ago ✓       │
└───────────────┴─────────────────┴─────────────────────┘
```

Once installed, the daemon starts on login and runs silently. You interact with it through `netglance daemon status`, `netglance metrics`, and `netglance alert`.

## Setup

### Install the daemon (macOS)

```bash
netglance daemon install
```

This creates a launchd plist and loads it. The daemon starts immediately and restarts on every login.

### Verify it's running

```bash
netglance daemon status
```

### Customize the schedule

Edit `~/.config/netglance/config.yaml`:

```yaml
daemon:
  schedules:
    discover: "*/15 * * * *"    # every 15 minutes
    dns_check: "0 * * * *"      # every hour
    tls_verify: "0 */6 * * *"   # every 6 hours
    baseline_diff: "0 2 * * *"  # daily at 2 AM
    report: "0 7 * * *"         # daily at 7 AM
```

Restart after changing:

```bash
netglance daemon uninstall && netglance daemon install
```

### Add alerts

Pair the daemon with alert rules so you're notified when checks fail:

```bash
netglance alert list           # see configured rules
netglance alert log            # see recent alerts
```

See [Alert](../tools/alert.md) for configuring thresholds and notification channels.

## What the daemon monitors

| Task | What it does | Default frequency |
|------|-------------|:-----------------:|
| **discover** | ARP scan for new/missing devices | Every 15 min |
| **dns_check** | Verify DNS consistency, detect hijacking | Hourly |
| **tls_verify** | Check TLS certificates for expiry/interception | Every 6 hours |
| **baseline_diff** | Compare current network state to saved baseline | Daily (2 AM) |
| **report** | Full health report across all modules | Daily (7 AM) |

Results are stored in `~/.config/netglance/netglance.db` and available through `netglance metrics` for charting and trend analysis.

## Querying daemon data

The daemon's value comes from the data it accumulates:

```bash
# View stored metrics with sparkline charts
netglance metrics show --period 7d

# Check for devices that appeared or disappeared
netglance baseline diff

# Review alert history
netglance alert log --last 50
```

## Pairing with other modes

- **Daemon + CLI**: The daemon collects; you use CLI commands to dig deeper when something looks off.
- **Daemon + MCP**: Ask your AI assistant to analyze daemon-collected data — "show me the DNS trend for the past week" or "any new devices since yesterday?"

## Full reference

For all commands, flags, launchd details, log locations, and troubleshooting, see the **[Daemon command reference](../tools/daemon.md)**.
