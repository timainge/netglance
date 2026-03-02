# Set Up Alerts

> Your internet goes down at 2 AM and you don't find out until your morning video call fails. Your download speed has been tanking for a week but you only notice when a big file transfer crawls. netglance can watch your network metrics and tell you the moment something goes wrong — so you find out before it matters.

netglance supports two kinds of alerts. **Metric threshold alerts** are persistent rules stored in the database — "tell me when my download speed drops below 25 Mbps." **Event alerts** fire in real time when something happens, like a new device joining your network. This guide focuses on metric alerts, since they're the most useful for day-to-day home network monitoring.

## Prerequisites: getting metrics into the database

Alert rules watch *stored* metrics, so you need data in the database first. Any netglance command that measures something can save its result with the `--save` flag:

```bash
# Run a speed test and save the result
netglance speed --save

# Ping a host and save the result
netglance ping host 8.8.8.8 --save

# Monitor bandwidth on your main interface
netglance traffic --save
```

Each of these writes metric values into netglance's SQLite database. Here are the metric names that get created:

| Source | Metric names |
|--------|-------------|
| Speed tests | `speed.download_mbps`, `speed.upload_mbps`, `speed.latency_ms` |
| Ping | `ping.{host}.latency_ms`, `ping.{host}.packet_loss` |
| Traffic | `traffic.{iface}.rx_bytes_per_sec`, `traffic.{iface}.tx_bytes_per_sec` |
| WiFi | `wifi.signal_dbm` |

The `{host}` placeholder uses underscores instead of dots — so pinging `8.8.8.8` produces `ping.8_8_8_8.latency_ms`.

To see what metrics you actually have stored:

```bash
netglance metrics list
```

If you get "No metrics found," run a few commands with `--save` first, then come back.

## Your first alert: slow download speed

Let's create an alert that fires when your download speed drops below 25 Mbps. Here's the full workflow:

```bash
# Create the rule
netglance alert add --metric speed.download_mbps --below 25 \
  --message "Download speed dropped below 25 Mbps"
```

You'll see confirmation:

```
Created alert rule #1: speed.download_mbps below 25.0
```

Verify it was saved:

```bash
netglance alert list
```

```
         Alert Rules
┌────┬───────────────────────┬───────────┬───────────┬────────┬─────────┬──────────────────────────────────────┐
│ ID │ Metric                │ Condition │ Threshold │ Window │ Enabled │ Message                              │
├────┼───────────────────────┼───────────┼───────────┼────────┼─────────┼──────────────────────────────────────┤
│  1 │ speed.download_mbps   │   below   │      25.0 │  300s  │   Yes   │ Download speed dropped below 25 Mbps │
└────┴───────────────────────┴───────────┴───────────┴────────┴─────────┴──────────────────────────────────────┘
```

Now run a speed test to generate a data point:

```bash
netglance speed --save
```

If your download speed is below 25 Mbps, the alert fires. Check the alert log:

```bash
netglance alert log
```

**What happened behind the scenes:** when you ran `netglance speed --save`, the speed module measured your connection and saved `speed.download_mbps` to the database. That save triggered alert evaluation — netglance checked all enabled rules matching that metric name, compared the value against each rule's threshold, and logged any that triggered.

## Latency monitoring

High latency makes video calls choppy and games unplayable, even when your bandwidth is fine. Set up a latency alert:

```bash
netglance alert add --metric ping.8_8_8_8.latency_ms --above 100 \
  --message "Latency to Google DNS exceeds 100ms"
```

Then generate a data point:

```bash
netglance ping host 8.8.8.8 --save
```

### The evaluation window

Each alert rule has a `--window` flag (default: 300 seconds / 5 minutes). This controls the time window netglance considers when evaluating the rule. You can adjust it when creating the rule:

```bash
# Only alert if latency has been high for the past 10 minutes
netglance alert add --metric ping.8_8_8_8.latency_ms --above 100 \
  --window 600 \
  --message "Sustained high latency (10 min)"
```

A shorter window catches brief spikes. A longer window filters out momentary blips and only fires on sustained problems.

## Managing alerts

Once you have rules, here's how to manage them:

```bash
# View all rules
netglance alert list

# Disable a rule temporarily (keeps it but stops evaluation)
netglance alert disable 1

# Re-enable it
netglance alert enable 1

# Delete a rule permanently
netglance alert delete 1
```

### Working with the alert log

Every time a rule fires, it's recorded in the alert log:

```bash
# View recent alerts
netglance alert log

# View alerts from the last hour
netglance alert log --since 1h

# View alerts from the last 7 days
netglance alert log --since 7d

# Show only alerts you haven't acknowledged yet
netglance alert log --unacked

# Acknowledge an alert (mark it as "seen")
netglance alert ack 1
```

Acknowledging alerts doesn't silence the rule — it just marks that specific log entry as handled. The rule keeps evaluating and will fire again if the condition is met.

## Getting notified

By default, alerts print to the terminal. That's fine when you're watching, but you probably want notifications sent to your phone or a chat channel. Configure notification channels in `~/.config/netglance/config.yaml`.

### Terminal (default)

Alerts print as rich panels in your terminal. This is always on unless you disable it:

```yaml
notifications:
  stdout: true
```

### ntfy (recommended for mobile)

[ntfy](https://ntfy.sh) is a free, open-source push notification service. Install the ntfy app on your phone, pick a topic name, and you'll get alerts as push notifications.

```yaml
notifications:
  ntfy:
    server: https://ntfy.sh
    topic: my-network-alerts
```

That's it. No account needed. Alerts show up on your phone within seconds. You can also self-host ntfy if you prefer — just change the `server` URL.

### Webhook

Send alerts as JSON POST requests to any URL — works with Slack, Discord, Teams, or your own service:

```yaml
notifications:
  webhook:
    url: https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXX
```

The payload includes `severity`, `category`, `title`, `message`, `data`, and `timestamp` fields.

### Email

Send alerts via SMTP:

```yaml
notifications:
  email:
    smtp_host: smtp.gmail.com
    smtp_port: 587
    from: alerts@example.com
    to: you@example.com
    username: alerts@example.com
    password: app-password-here
```

!!! tip "Gmail users"
    Use an [App Password](https://support.google.com/accounts/answer/185833) instead of your regular password. You'll need 2-factor authentication enabled on your Google account first.

You can enable multiple channels at once. For example, keep `stdout: true` and add ntfy — you'll get both terminal output and phone notifications.

## Common alert recipes

Here are useful rules for a typical home network:

| What to watch | Command |
|---|---|
| Slow downloads | `netglance alert add --metric speed.download_mbps --below 25 --message "Slow download"` |
| Slow uploads | `netglance alert add --metric speed.upload_mbps --below 5 --message "Slow upload"` |
| High latency | `netglance alert add --metric ping.8_8_8_8.latency_ms --above 100 --message "High latency"` |
| Packet loss | `netglance alert add --metric ping.8_8_8_8.packet_loss --above 0.05 --message "Packet loss >5%"` |
| Weak WiFi | `netglance alert add --metric wifi.signal_dbm --below -70 --message "Weak WiFi signal"` |
| High latency to router | `netglance alert add --metric ping.192_168_1_1.latency_ms --above 10 --message "High LAN latency"` |

Adjust the thresholds to match your connection. If you're paying for 100 Mbps, set the download alert at maybe 50 Mbps. If your connection is normally 20 Mbps, 25 Mbps would trigger constantly.

## Continuous monitoring with the daemon

Running commands with `--save` manually works, but you'd have to remember to do it. The netglance daemon runs in the background and collects metrics on a schedule — and evaluates your alert rules automatically every time it does.

```bash
# Start the daemon in the foreground (good for testing)
netglance daemon start

# Or install it as a background service (macOS)
netglance daemon install
```

The daemon runs discovery, DNS checks, TLS verification, baseline diffs, and health reports on configurable cron schedules. Each time it collects data, any matching alert rules are evaluated.

To check whether the daemon is installed:

```bash
netglance daemon status
```

With the daemon running and a few alert rules configured, you have a hands-off monitoring system. Your network gets checked regularly, and you only hear about it when something needs attention.

## Quick reference

| What you want to do | Command |
|---------------------|---------|
| Create a threshold alert | `netglance alert add --metric <name> --above/--below <value>` |
| List all rules | `netglance alert list` |
| View alert history | `netglance alert log` |
| View recent alerts | `netglance alert log --since 24h` |
| Acknowledge an alert | `netglance alert ack <id>` |
| Disable a rule | `netglance alert disable <id>` |
| Enable a rule | `netglance alert enable <id>` |
| Delete a rule | `netglance alert delete <id>` |
| See stored metrics | `netglance metrics list` |
| Start the daemon | `netglance daemon start` |

## Next steps

- [Keep My Network Healthy](keep-my-network-healthy.md) — set up continuous monitoring with the daemon and scheduled health reports
- [What's on My Network?](whats-on-my-network.md) — discover all devices and set baselines to catch new ones
- [Is My Internet Slow?](is-my-internet-slow.md) — diagnose bandwidth and latency problems
