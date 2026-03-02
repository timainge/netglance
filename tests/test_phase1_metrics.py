"""Tests for metrics storage in store/db.py."""

from datetime import datetime, timedelta, timezone

from netglance.store.db import Store


def test_save_metric(tmp_db: Store):
    row_id = tmp_db.save_metric("ping.gateway.latency_ms", 5.2)
    assert row_id is not None
    assert row_id > 0


def test_save_metric_with_tags(tmp_db: Store):
    row_id = tmp_db.save_metric("ping.internet.latency_ms", 12.0, tags={"host": "1.1.1.1"})
    assert row_id > 0
    series = tmp_db.get_metric_series("ping.internet.latency_ms")
    assert len(series) == 1
    assert series[0]["tags"] == {"host": "1.1.1.1"}


def test_save_metric_no_tags(tmp_db: Store):
    tmp_db.save_metric("speed.download_mbps", 100.0)
    series = tmp_db.get_metric_series("speed.download_mbps")
    assert series[0]["tags"] is None


def test_save_metrics_batch(tmp_db: Store):
    samples = [
        ("ping.gw.latency_ms", 5.0, None),
        ("ping.gw.latency_ms", 6.0, None),
        ("ping.gw.latency_ms", 4.5, {"attempt": 3}),
    ]
    tmp_db.save_metrics_batch(samples)
    series = tmp_db.get_metric_series("ping.gw.latency_ms")
    assert len(series) == 3


def test_get_metric_series_ordering(tmp_db: Store):
    tmp_db.save_metric("test.metric", 1.0)
    tmp_db.save_metric("test.metric", 2.0)
    tmp_db.save_metric("test.metric", 3.0)
    series = tmp_db.get_metric_series("test.metric")
    values = [s["value"] for s in series]
    assert values == [1.0, 2.0, 3.0]


def test_get_metric_series_limit(tmp_db: Store):
    for i in range(10):
        tmp_db.save_metric("test.metric", float(i))
    series = tmp_db.get_metric_series("test.metric", limit=5)
    assert len(series) == 5


def test_get_metric_series_since(tmp_db: Store):
    tmp_db.save_metric("test.metric", 1.0)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    series = tmp_db.get_metric_series("test.metric", since=future)
    assert len(series) == 0


def test_get_metric_series_until(tmp_db: Store):
    tmp_db.save_metric("test.metric", 1.0)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    series = tmp_db.get_metric_series("test.metric", until=past)
    assert len(series) == 0


def test_get_metric_series_empty(tmp_db: Store):
    series = tmp_db.get_metric_series("nonexistent.metric")
    assert series == []


def test_get_metric_stats(tmp_db: Store):
    for v in [10.0, 20.0, 30.0]:
        tmp_db.save_metric("test.stat", v)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    stats = tmp_db.get_metric_stats("test.stat", since=since)
    assert stats["count"] == 3
    assert stats["avg"] == 20.0
    assert stats["min"] == 10.0
    assert stats["max"] == 30.0


def test_get_metric_stats_empty(tmp_db: Store):
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    stats = tmp_db.get_metric_stats("nonexistent", since=since)
    assert stats["count"] == 0
    assert stats["avg"] is None


def test_get_metric_stats_with_until(tmp_db: Store):
    tmp_db.save_metric("test.stat", 42.0)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    until = datetime.now(timezone.utc) + timedelta(hours=1)
    stats = tmp_db.get_metric_stats("test.stat", since=since, until=until)
    assert stats["count"] == 1
    assert stats["avg"] == 42.0


def test_prune_metrics_no_old_data(tmp_db: Store):
    tmp_db.save_metric("recent.metric", 1.0)
    deleted = tmp_db.prune_metrics(older_than_days=365)
    assert deleted == 0
    series = tmp_db.get_metric_series("recent.metric")
    assert len(series) == 1


def test_prune_metrics_old_data(tmp_db: Store):
    # Insert a metric with an old timestamp directly
    old_ts = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    tmp_db.conn.execute(
        "INSERT INTO metrics (ts, metric, value, tags) VALUES (?, ?, ?, ?)",
        (old_ts, "old.metric", 1.0, None),
    )
    tmp_db.conn.commit()

    # Also insert a recent one
    tmp_db.save_metric("old.metric", 2.0)

    deleted = tmp_db.prune_metrics(older_than_days=365)
    assert deleted == 1
    series = tmp_db.get_metric_series("old.metric")
    assert len(series) == 1
    assert series[0]["value"] == 2.0


def test_metrics_table_created(tmp_db: Store):
    """Metrics table exists after init_db."""
    row = tmp_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='metrics'"
    ).fetchone()
    assert row is not None


def test_metrics_isolation(tmp_db: Store):
    """Metrics for different names don't mix."""
    tmp_db.save_metric("a.metric", 1.0)
    tmp_db.save_metric("b.metric", 2.0)
    a_series = tmp_db.get_metric_series("a.metric")
    b_series = tmp_db.get_metric_series("b.metric")
    assert len(a_series) == 1
    assert len(b_series) == 1
    assert a_series[0]["value"] == 1.0
    assert b_series[0]["value"] == 2.0


def test_existing_tables_still_work(tmp_db: Store):
    """Existing results and baselines tables unaffected by metrics addition."""
    row_id = tmp_db.save_result("test_module", {"key": "value"})
    assert row_id is not None
    results = tmp_db.get_results("test_module")
    assert len(results) == 1

    bid = tmp_db.save_baseline({"devices": []}, label="test")
    assert bid is not None
    baseline = tmp_db.get_latest_baseline()
    assert baseline is not None
