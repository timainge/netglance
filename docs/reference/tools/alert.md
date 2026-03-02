# Alert Rules

Manage threshold-based alerts for network metrics. Define rules that trigger when metrics exceed or fall below specified thresholds, with optional notifications.

## What it does

The `alert` tool lets you create and manage alert rules that automatically fire when network metrics cross a threshold. Each rule monitors a specific metric (like latency or packet loss), triggers when a condition is met (above or below a threshold), and can send notifications through configured channels.

Alert rules are stored in the database and evaluated continuously when metrics are recorded. You can list active rules, view fired alert history, acknowledge alerts, and enable/disable rules without deleting them.

## Quick start

Create an alert rule for high latency:

```bash
netglance alert add --metric ping.gateway.latency_ms --above 100 --message "Gateway latency high"
```

List all configured alert rules:

```bash
netglance alert list
```

View recent fired alerts:

```bash
netglance alert log --since 1h
```

Acknowledge a specific alert:

```bash
netglance alert ack 5
```

## Commands

### `netglance alert add`

Create a new alert rule. Requires a metric name and either `--above` or `--below`.

**Options:**

- `--metric, -m` (required) — Metric name to monitor (e.g., `ping.gateway.latency_ms`, `traffic.eth0.bytes_in`).
- `--above` — Trigger when metric exceeds this value (numeric).
- `--below` — Trigger when metric falls below this value (numeric).
- `--message` — Optional human-readable description for the alert. If not provided, a default message is generated.
- `--window, -w` — Evaluation window in seconds (default: 300). Rules evaluate over this time window.

Example:

```bash
netglance alert add --metric ping.gateway.latency_ms --above 150 --window 60 --message "High latency alert"
```

### `netglance alert list`

Show all configured alert rules in a table.

**Options:**

- `--json` — Output as JSON instead of table format.

Example:

```bash
netglance alert list --json
```

### `netglance alert delete`

Remove an alert rule by ID.

**Arguments:**

- `RULE_ID` — The numeric ID of the rule to delete.

Example:

```bash
netglance alert delete 2
```

### `netglance alert enable`

Re-enable a disabled alert rule (does not create a new rule).

**Arguments:**

- `RULE_ID` — The numeric ID of the rule to enable.

Example:

```bash
netglance alert enable 1
```

### `netglance alert disable`

Disable an alert rule without deleting it. Disabled rules are not evaluated.

**Arguments:**

- `RULE_ID` — The numeric ID of the rule to disable.

Example:

```bash
netglance alert disable 1
```

### `netglance alert log`

Show fired alert history. Displays a log of all alerts that have been triggered.

**Options:**

- `--since` — Show alerts from a period (e.g., `1h`, `24h`, `7d`).
- `--unacked` — Show only unacknowledged alerts.
- `--limit, -n` — Maximum number of entries to show (default: 50).
- `--json` — Output as JSON instead of table format.

Examples:

```bash
netglance alert log --since 24h --limit 20
netglance alert log --unacked
netglance alert log --json
```

### `netglance alert ack`

Mark a fired alert as acknowledged.

**Arguments:**

- `ALERT_ID` — The numeric ID of the alert log entry to acknowledge.

Example:

```bash
netglance alert ack 7
```

## Understanding the output

### Alert Rule Status

Rules have two states:

- **Enabled** — The rule is active and fires when the condition is met.
- **Disabled** — The rule exists but is not evaluated. Use `enable` to reactivate.

### Threshold Conditions

- **above** — Fires when metric value exceeds the threshold.
- **below** — Fires when metric value drops below the threshold.

For example, "ping.gateway.latency_ms above 100" fires whenever gateway latency exceeds 100ms.

### Alert Log Status

Each fired alert can be:

- **Unacknowledged** — Alert has fired but not yet marked as seen.
- **Acknowledged** — Alert has been acknowledged by a user.

Use `netglance alert ack <id>` to mark an alert as seen, then filter unacknowledged alerts with `--unacked` for new incidents.

## Related concepts

- **Metrics** — Alert rules monitor values produced by other netglance tools (ping, traffic, DNS). Run the corresponding tool to generate metrics.
- **Daemon** — The daemon continuously evaluates alert rules as metrics are recorded. Start with `netglance daemon start`.
- **Notifications** — Alerts can send notifications to configured channels (terminal, webhook). Configure in `~/.config/netglance/config.yaml`.

## Troubleshooting

### Alerts not firing

- **Daemon not running** — Rules are evaluated by the background daemon. Ensure it is running with `netglance daemon status`.
- **Metric name incorrect** — Double-check the exact metric name. Run the source tool first to generate metrics, then list rules to verify the name matches.
- **Rule disabled** — Check if the rule is enabled with `netglance alert list`. Re-enable with `netglance alert enable <id>` if needed.

### Too many alerts (noisy thresholds)

- Increase the threshold to reduce false positives.
- Increase the evaluation window (`--window`) to smooth out spikes.
- Disable low-priority rules and re-enable them only when needed.

### Notification delivery issues

- Verify notification channels are configured in `~/.config/netglance/config.yaml`.
- Check that the daemon is running and has access to notification service credentials.
- For webhooks, confirm the endpoint is reachable and accepting POST requests.

### Alert rule syntax errors

- `condition must be 'above' or 'below'` — Provide exactly one of `--above` or `--below`, not both.
- `Metric name` — Use standard netglance metric names like `ping.gateway.latency_ms`, not arbitrary strings.
