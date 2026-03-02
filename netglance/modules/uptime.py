"""Host uptime monitoring — periodic reachability checks and summary computation."""

from __future__ import annotations

from datetime import datetime, timedelta

from netglance.modules.ping import ping_host
from netglance.store.db import Store
from netglance.store.models import PingResult, UptimeRecord, UptimeSummary

# Maps period strings like "24h", "7d", "1h" to timedelta
_PERIOD_MAP: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "24h": timedelta(hours=24),
    "2d": timedelta(days=2),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def _parse_period(period: str) -> timedelta:
    """Parse a period string into a timedelta.

    Supports strings like "24h", "7d". Raises ValueError for unknown formats.
    """
    if period in _PERIOD_MAP:
        return _PERIOD_MAP[period]
    # Try parsing manually: e.g. "48h", "3d"
    suffix_map = {"h": "hours", "d": "days", "m": "minutes"}
    if period and period[-1] in suffix_map and period[:-1].isdigit():
        value = int(period[:-1])
        return timedelta(**{suffix_map[period[-1]]: value})
    raise ValueError(f"Unknown period format: {period!r}. Use e.g. '24h', '7d'.")


def check_host(
    host: str,
    timeout: float = 2.0,
    *,
    _ping_fn=None,
) -> UptimeRecord:
    """Perform a single uptime check for a host.

    Wraps ping_host with count=1 and converts the PingResult to an UptimeRecord.

    Args:
        host: IP address or hostname to check.
        timeout: Seconds to wait for ICMP reply.
        _ping_fn: Injectable replacement for icmplib.ping (for testing).

    Returns:
        UptimeRecord capturing whether the host is alive and round-trip latency.
    """
    result: PingResult = ping_host(host, count=1, timeout=timeout, _ping_fn=_ping_fn)
    return UptimeRecord(
        host=host,
        check_time=result.timestamp,
        is_alive=result.is_alive,
        latency_ms=result.avg_latency_ms,
    )


def save_uptime_record(record: UptimeRecord, store: Store) -> int:
    """Persist an uptime check record to the store."""
    return store.save_result("uptime", {
        "host": record.host,
        "check_time": record.check_time.isoformat(),
        "is_alive": record.is_alive,
        "latency_ms": record.latency_ms,
    })


def _default_store_fn(host: str, period: str) -> list[UptimeRecord]:
    """Query the DB for uptime records matching host and period."""
    try:
        store = Store()
        store.init_db()
        since = datetime.now() - _parse_period(period)
        rows = store.get_results("uptime", limit=10000, since=since)
        store.close()
    except Exception:
        return []
    records = []
    for row in rows:
        if row.get("host") == host:
            records.append(UptimeRecord(
                host=row["host"],
                check_time=datetime.fromisoformat(row["check_time"]),
                is_alive=row["is_alive"],
                latency_ms=row.get("latency_ms"),
            ))
    return records


def compute_uptime(
    records: list[UptimeRecord],
    period: str = "24h",
) -> UptimeSummary:
    """Compute uptime percentage and detect outage windows from a list of records.

    Pure computation — no I/O. Records need not be pre-sorted; this function
    sorts them chronologically internally.

    An outage is a consecutive run of is_alive=False records. Each outage dict
    has keys: ``start`` (datetime), ``end`` (datetime), ``duration_s`` (float).

    Args:
        records: List of UptimeRecord objects (any order).
        period: Human-readable label stored in the returned UptimeSummary.

    Returns:
        UptimeSummary with uptime percentage, outage windows, and current status.
    """
    if not records:
        return UptimeSummary(
            host="",
            period=period,
            uptime_pct=0.0,
            total_checks=0,
            successful_checks=0,
            avg_latency_ms=None,
            outages=[],
            current_status="unknown",
            last_seen=None,
        )

    sorted_records = sorted(records, key=lambda r: r.check_time)
    host = sorted_records[0].host

    total = len(sorted_records)
    alive_records = [r for r in sorted_records if r.is_alive]
    successful = len(alive_records)
    uptime_pct = (successful / total) * 100.0

    # Average latency over alive records only
    latencies = [r.latency_ms for r in alive_records if r.latency_ms is not None]
    avg_latency_ms = sum(latencies) / len(latencies) if latencies else None

    # Detect outage windows: consecutive is_alive=False runs
    outages: list[dict] = []
    outage_start: datetime | None = None
    outage_last: datetime | None = None

    for rec in sorted_records:
        if not rec.is_alive:
            if outage_start is None:
                outage_start = rec.check_time
            outage_last = rec.check_time
        else:
            if outage_start is not None:
                duration_s = (outage_last - outage_start).total_seconds()  # type: ignore[operator]
                outages.append(
                    {
                        "start": outage_start,
                        "end": outage_last,
                        "duration_s": duration_s,
                    }
                )
                outage_start = None
                outage_last = None

    # Close any open outage at end of records
    if outage_start is not None:
        duration_s = (outage_last - outage_start).total_seconds()  # type: ignore[operator]
        outages.append(
            {
                "start": outage_start,
                "end": outage_last,
                "duration_s": duration_s,
            }
        )

    last_record = sorted_records[-1]
    current_status = "up" if last_record.is_alive else "down"
    last_seen = last_record.check_time if last_record.is_alive else None
    # If host was up at some earlier point, record that as last_seen
    if last_seen is None and alive_records:
        last_seen = alive_records[-1].check_time

    return UptimeSummary(
        host=host,
        period=period,
        uptime_pct=uptime_pct,
        total_checks=total,
        successful_checks=successful,
        avg_latency_ms=avg_latency_ms,
        outages=outages,
        current_status=current_status,
        last_seen=last_seen,
    )


def get_uptime_summary(
    host: str,
    period: str = "24h",
    *,
    _store_fn=None,
) -> UptimeSummary:
    """Query stored records and compute an uptime summary.

    Args:
        host: IP address or hostname whose records to query.
        period: Time window string (e.g. "24h", "7d").
        _store_fn: Injectable callable ``(host, period) -> list[UptimeRecord]``
                   (for testing). If None, returns an empty summary (store
                   integration is wired up by the daemon layer).

    Returns:
        UptimeSummary computed from stored records.
    """
    if _store_fn is not None:
        records = _store_fn(host, period)
    else:
        records = _default_store_fn(host, period)

    summary = compute_uptime(records, period=period)
    # Ensure host is set even when records list is empty
    if not summary.host:
        summary = UptimeSummary(
            host=host,
            period=summary.period,
            uptime_pct=summary.uptime_pct,
            total_checks=summary.total_checks,
            successful_checks=summary.successful_checks,
            avg_latency_ms=summary.avg_latency_ms,
            outages=summary.outages,
            current_status=summary.current_status,
            last_seen=summary.last_seen,
        )
    return summary
