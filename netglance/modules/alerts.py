"""Alert rule management and threshold evaluation."""

from __future__ import annotations

from datetime import datetime, timezone

from netglance.notify import NotificationManager
from netglance.store.db import Store
from netglance.store.models import Alert


def create_alert_rule(
    store: Store,
    metric: str,
    condition: str,
    threshold: float,
    message: str | None = None,
    window_s: int = 300,
) -> int:
    """Create a new alert rule. Returns rule ID.

    Args:
        store: SQLite store instance.
        metric: Metric name to monitor (e.g. 'ping.gateway.latency_ms').
        condition: 'above' or 'below'.
        threshold: Numeric threshold value.
        message: Optional human-readable description.
        window_s: Evaluation window in seconds.

    Returns:
        The newly created rule's integer ID.

    Raises:
        ValueError: If condition is not 'above' or 'below'.
    """
    if condition not in ("above", "below"):
        raise ValueError(f"condition must be 'above' or 'below', got {condition!r}")

    cur = store.conn.execute(
        "INSERT INTO alert_rules (metric, condition, threshold, window_s, enabled, message) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (metric, condition, threshold, window_s, message),
    )
    store.conn.commit()
    return cur.lastrowid  # type: ignore[return-value]


def list_alert_rules(store: Store) -> list[dict]:
    """Return all alert rules as list of dicts.

    Returns:
        List of dicts with keys: id, metric, condition, threshold, window_s, enabled, message.
    """
    rows = store.conn.execute(
        "SELECT id, metric, condition, threshold, window_s, enabled, message "
        "FROM alert_rules ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


def get_alert_rule(store: Store, rule_id: int) -> dict | None:
    """Get a single alert rule by ID.

    Returns:
        Dict with rule data, or None if not found.
    """
    row = store.conn.execute(
        "SELECT id, metric, condition, threshold, window_s, enabled, message "
        "FROM alert_rules WHERE id = ?",
        (rule_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_alert_rule(store: Store, rule_id: int) -> bool:
    """Delete an alert rule by ID.

    Returns:
        True if deleted, False if not found.
    """
    cur = store.conn.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
    store.conn.commit()
    return cur.rowcount > 0


def toggle_alert_rule(store: Store, rule_id: int, enabled: bool) -> bool:
    """Enable or disable an alert rule.

    Returns:
        True if updated, False if not found.
    """
    cur = store.conn.execute(
        "UPDATE alert_rules SET enabled = ? WHERE id = ?",
        (1 if enabled else 0, rule_id),
    )
    store.conn.commit()
    return cur.rowcount > 0


def evaluate_metric_alerts(
    store: Store,
    metric: str,
    value: float,
    *,
    notify_manager: NotificationManager | None = None,
) -> list[str]:
    """Check if a metric value triggers any enabled alert rules.

    For each triggered rule:
    1. Inserts a row into alert_log.
    2. If notify_manager provided, sends an Alert notification.

    Returns:
        List of fired alert messages (one per triggered rule).
    """
    rows = store.conn.execute(
        "SELECT id, metric, condition, threshold, message FROM alert_rules "
        "WHERE metric = ? AND enabled = 1",
        (metric,),
    ).fetchall()

    fired: list[str] = []
    ts = datetime.now(timezone.utc).isoformat()

    for row in rows:
        rule_id = row["id"]
        condition = row["condition"]
        threshold = row["threshold"]
        rule_message = row["message"]

        triggered = (condition == "above" and value > threshold) or (
            condition == "below" and value < threshold
        )

        if not triggered:
            continue

        default_msg = (
            f"{metric} is {value} ({condition} threshold {threshold})"
        )
        alert_message = rule_message or default_msg

        store.conn.execute(
            "INSERT INTO alert_log (ts, rule_id, metric, value, threshold, message, acknowledged) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (ts, rule_id, metric, value, threshold, alert_message),
        )

        if notify_manager is not None:
            alert = Alert(
                severity="warning",
                category="metric_threshold",
                title=f"Alert: {metric}",
                message=alert_message,
                data={"metric": metric, "value": value, "threshold": threshold, "condition": condition},
            )
            notify_manager.notify(alert)

        fired.append(alert_message)

    store.conn.commit()
    return fired


def get_alert_log(
    store: Store,
    since: datetime | None = None,
    limit: int = 50,
    unacknowledged_only: bool = False,
) -> list[dict]:
    """Retrieve alert log entries.

    Returns:
        List of dicts with keys: id, ts, rule_id, metric, value, threshold, message, acknowledged.
    """
    query = (
        "SELECT id, ts, rule_id, metric, value, threshold, message, acknowledged "
        "FROM alert_log WHERE 1=1"
    )
    params: list = []

    if since is not None:
        query += " AND ts >= ?"
        params.append(since.isoformat())

    if unacknowledged_only:
        query += " AND acknowledged = 0"

    query += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    rows = store.conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def acknowledge_alert(store: Store, alert_id: int) -> bool:
    """Mark an alert as acknowledged.

    Returns:
        True if updated, False if not found.
    """
    cur = store.conn.execute(
        "UPDATE alert_log SET acknowledged = 1 WHERE id = ?",
        (alert_id,),
    )
    store.conn.commit()
    return cur.rowcount > 0


def fire_event_alert(
    notify_manager: NotificationManager,
    category: str,
    title: str,
    message: str,
    severity: str = "warning",
    data: dict | None = None,
) -> None:
    """Create and send an event-based alert (new device, ARP spoof, etc.).

    Args:
        notify_manager: NotificationManager to use for sending.
        category: Alert category (e.g. 'new_device', 'arp_spoof').
        title: Short alert title.
        message: Detailed alert message.
        severity: 'info', 'warning', or 'critical'.
        data: Optional extra structured data.
    """
    alert = Alert(
        severity=severity,
        category=category,
        title=title,
        message=message,
        data=data or {},
    )
    notify_manager.notify(alert)
