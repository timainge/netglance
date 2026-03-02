"""Tests for Phase 3 db.py additions (alert tables, list_metrics)."""

import pytest
from datetime import datetime, timezone
from netglance.store.db import Store


@pytest.fixture()
def store(tmp_path):
    s = Store(db_path=tmp_path / "test.db")
    s.init_db()
    return s


class TestAlertTables:
    def test_alert_rules_table_exists(self, store):
        cur = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alert_rules'"
        )
        assert cur.fetchone() is not None

    def test_alert_log_table_exists(self, store):
        cur = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alert_log'"
        )
        assert cur.fetchone() is not None

    def test_insert_alert_rule(self, store):
        store.conn.execute(
            "INSERT INTO alert_rules (metric, condition, threshold, message) "
            "VALUES (?, ?, ?, ?)",
            ("ping.gateway.latency_ms", "above", 100.0, "High latency"),
        )
        store.conn.commit()
        row = store.conn.execute("SELECT * FROM alert_rules WHERE id = 1").fetchone()
        assert row["metric"] == "ping.gateway.latency_ms"
        assert row["condition"] == "above"
        assert row["threshold"] == 100.0
        assert row["enabled"] == 1
        assert row["window_s"] == 300

    def test_insert_alert_log(self, store):
        store.conn.execute(
            "INSERT INTO alert_rules (metric, condition, threshold) "
            "VALUES (?, ?, ?)",
            ("speed.download_mbps", "below", 50.0),
        )
        store.conn.execute(
            "INSERT INTO alert_log (ts, rule_id, metric, value, threshold, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00", 1, "speed.download_mbps", 42.3, 50.0, "Slow download"),
        )
        store.conn.commit()
        row = store.conn.execute("SELECT * FROM alert_log WHERE id = 1").fetchone()
        assert row["value"] == 42.3
        assert row["acknowledged"] == 0

    def test_alert_log_index_exists(self, store):
        cur = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_alert_log_ts'"
        )
        assert cur.fetchone() is not None

    def test_alert_rules_defaults(self, store):
        store.conn.execute(
            "INSERT INTO alert_rules (metric, condition, threshold) "
            "VALUES (?, ?, ?)",
            ("test.metric", "above", 1.0),
        )
        store.conn.commit()
        row = store.conn.execute("SELECT * FROM alert_rules WHERE id = 1").fetchone()
        assert row["enabled"] == 1
        assert row["window_s"] == 300
        assert row["message"] is None

    def test_multiple_rules(self, store):
        for i in range(5):
            store.conn.execute(
                "INSERT INTO alert_rules (metric, condition, threshold) VALUES (?, ?, ?)",
                (f"metric.{i}", "above", float(i * 10)),
            )
        store.conn.commit()
        count = store.conn.execute("SELECT COUNT(*) as cnt FROM alert_rules").fetchone()
        assert count["cnt"] == 5


class TestListMetrics:
    def test_empty_metrics(self, store):
        assert store.list_metrics() == []

    def test_list_metrics_returns_distinct(self, store):
        store.save_metric("ping.latency", 10.0)
        store.save_metric("ping.latency", 20.0)
        store.save_metric("speed.download", 100.0)
        result = store.list_metrics()
        assert result == ["ping.latency", "speed.download"]

    def test_list_metrics_sorted(self, store):
        store.save_metric("wifi.signal", -50.0)
        store.save_metric("arp.count", 5.0)
        store.save_metric("ping.latency", 10.0)
        result = store.list_metrics()
        assert result == ["arp.count", "ping.latency", "wifi.signal"]

    def test_list_metrics_many(self, store):
        for i in range(20):
            store.save_metric(f"metric.{i:02d}", float(i))
        result = store.list_metrics()
        assert len(result) == 20
        assert result[0] == "metric.00"
        assert result[-1] == "metric.19"
