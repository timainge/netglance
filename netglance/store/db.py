"""SQLite storage for netglance results and baselines."""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".config" / "netglance" / "netglance.db"

VALID_TABLES = frozenset({"results", "baselines", "metrics", "alert_rules", "alert_log"})


class Store:
    """SQLite-backed storage for netglance data."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
        return self._conn

    def init_db(self) -> None:
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                module TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS baselines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT,
                timestamp TEXT NOT NULL,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id     INTEGER PRIMARY KEY,
                ts     TEXT    NOT NULL,
                metric TEXT    NOT NULL,
                value  REAL    NOT NULL,
                tags   TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_rules (
                id         INTEGER PRIMARY KEY,
                metric     TEXT    NOT NULL,
                condition  TEXT    NOT NULL,
                threshold  REAL    NOT NULL,
                window_s   INTEGER NOT NULL DEFAULT 300,
                enabled    INTEGER NOT NULL DEFAULT 1,
                message    TEXT
            );

            CREATE TABLE IF NOT EXISTS alert_log (
                id           INTEGER PRIMARY KEY,
                ts           TEXT    NOT NULL,
                rule_id      INTEGER NOT NULL,
                metric       TEXT    NOT NULL,
                value        REAL    NOT NULL,
                threshold    REAL    NOT NULL,
                message      TEXT,
                acknowledged INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_results_module ON results(module);
            CREATE INDEX IF NOT EXISTS idx_results_timestamp ON results(timestamp);
            CREATE INDEX IF NOT EXISTS idx_metrics_metric_ts ON metrics(metric, ts);
            CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);
            CREATE INDEX IF NOT EXISTS idx_alert_log_ts ON alert_log(ts);
        """)

    def save_result(self, module: str, data: dict) -> int:
        """Save a module result. Returns the row ID."""
        cur = self.conn.execute(
            "INSERT INTO results (module, timestamp, data) VALUES (?, ?, ?)",
            (module, datetime.now().isoformat(), json.dumps(data)),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_results(
        self, module: str, limit: int = 10, since: datetime | None = None
    ) -> list[dict]:
        """Get recent results for a module."""
        if since:
            rows = self.conn.execute(
                "SELECT data FROM results WHERE module = ? AND timestamp >= ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (module, since.isoformat(), limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM results WHERE module = ? ORDER BY timestamp DESC LIMIT ?",
                (module, limit),
            ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def save_baseline(self, data: dict, label: str | None = None) -> int:
        """Save a network baseline. Returns the baseline ID."""
        cur = self.conn.execute(
            "INSERT INTO baselines (label, timestamp, data) VALUES (?, ?, ?)",
            (label, datetime.now().isoformat(), json.dumps(data)),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_latest_baseline(self) -> dict | None:
        """Get the most recent baseline."""
        row = self.conn.execute(
            "SELECT data FROM baselines ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def get_baseline(self, baseline_id: int) -> dict | None:
        """Get a specific baseline by ID."""
        row = self.conn.execute(
            "SELECT data FROM baselines WHERE id = ?", (baseline_id,)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def list_baselines(self, limit: int = 20) -> list[dict]:
        """List saved baselines (id, label, timestamp). Returns metadata only."""
        rows = self.conn.execute(
            "SELECT id, label, timestamp FROM baselines ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"id": row["id"], "label": row["label"], "timestamp": row["timestamp"]} for row in rows]

    def save_metric(self, metric: str, value: float, tags: dict | None = None) -> int:
        """Insert a single metric sample. Returns row ID."""
        cur = self.conn.execute(
            "INSERT INTO metrics (ts, metric, value, tags) VALUES (?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                metric,
                value,
                json.dumps(tags) if tags else None,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def save_metrics_batch(self, samples: list[tuple[str, float, dict | None]]) -> None:
        """Insert multiple samples in one transaction. Each tuple: (metric, value, tags)."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.executemany(
            "INSERT INTO metrics (ts, metric, value, tags) VALUES (?, ?, ?, ?)",
            [
                (now, metric, value, json.dumps(tags) if tags else None)
                for metric, value, tags in samples
            ],
        )
        self.conn.commit()

    def get_metric_series(
        self,
        metric: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        """Retrieve time series for a metric. Returns [{"ts", "value", "tags"}, ...]."""
        query = "SELECT ts, value, tags FROM metrics WHERE metric = ?"
        params: list = [metric]

        if since:
            query += " AND ts >= ?"
            params.append(since.isoformat())
        if until:
            query += " AND ts <= ?"
            params.append(until.isoformat())

        query += " ORDER BY ts ASC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "ts": row["ts"],
                "value": row["value"],
                "tags": json.loads(row["tags"]) if row["tags"] else None,
            }
            for row in rows
        ]

    def get_metric_stats(
        self,
        metric: str,
        since: datetime,
        until: datetime | None = None,
    ) -> dict:
        """Aggregate stats: {"count", "avg", "min", "max"}."""
        query = "SELECT COUNT(*) as cnt, AVG(value) as avg, MIN(value) as min, MAX(value) as max FROM metrics WHERE metric = ? AND ts >= ?"
        params: list = [metric, since.isoformat()]

        if until:
            query += " AND ts <= ?"
            params.append(until.isoformat())

        row = self.conn.execute(query, params).fetchone()
        return {
            "count": row["cnt"],
            "avg": row["avg"],
            "min": row["min"],
            "max": row["max"],
        }

    def list_metrics(self) -> list[str]:
        """Return all distinct metric names in the metrics table."""
        rows = self.conn.execute(
            "SELECT DISTINCT metric FROM metrics ORDER BY metric"
        ).fetchall()
        return [row["metric"] for row in rows]

    def prune_metrics(self, older_than_days: int = 365) -> int:
        """Delete raw samples older than N days. Returns rows deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        cur = self.conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount

    def count_rows(self, table: str) -> int:
        """Return row count for a table. Validates table name against VALID_TABLES to prevent injection."""
        if table not in VALID_TABLES:
            raise ValueError(f"Unknown table: {table!r}")
        row = self.conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
        return row["cnt"]

    def prune_results(self, older_than_days: int = 365) -> int:
        """Delete results older than N days. Returns rows deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        cur = self.conn.execute("DELETE FROM results WHERE timestamp < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount

    def delete_baseline(self, baseline_id: int) -> bool:
        """Delete a baseline by ID. Returns True if deleted."""
        cur = self.conn.execute("DELETE FROM baselines WHERE id = ?", (baseline_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def reset_all(self) -> dict[str, int]:
        """Delete all data from all tables. Returns {table: rows_deleted}."""
        counts = {}
        for table in VALID_TABLES:
            count = self.count_rows(table)
            self.conn.execute(f"DELETE FROM {table}")
            counts[table] = count
        self.conn.commit()
        return counts

    def export_all(self) -> dict:
        """Export all tables as JSON-serializable dict."""
        data = {}
        for table in VALID_TABLES:
            rows = self.conn.execute(f"SELECT * FROM {table}").fetchall()
            data[table] = [dict(row) for row in rows]
        return data

    def import_all(self, data: dict, mode: str = "merge") -> dict[str, int]:
        """Import data. mode='merge' appends, mode='replace' wipes first. Returns {table: rows_imported}."""
        if mode == "replace":
            self.reset_all()
        counts = {}
        for table in VALID_TABLES:
            rows = data.get(table, [])
            if not rows:
                counts[table] = 0
                continue
            cols = [k for k in rows[0].keys() if k != "id"]
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            for row in rows:
                vals = [row[c] for c in cols]
                self.conn.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", vals)
            counts[table] = len(rows)
        self.conn.commit()
        return counts

    def check_db_size(self, warn_threshold_mb: int = 100) -> dict | None:
        """Check if DB exceeds threshold.

        Returns None if under threshold, or a dict with size_mb,
        threshold_mb, largest_table, and largest_count.
        """
        size_bytes = os.path.getsize(self.db_path)
        size_mb = size_bytes / (1024 * 1024)
        if size_mb < warn_threshold_mb:
            return None
        largest_table = ""
        largest_count = -1
        for table in VALID_TABLES:
            count = self.count_rows(table)
            if count > largest_count:
                largest_count = count
                largest_table = table
        return {
            "size_mb": size_mb,
            "threshold_mb": warn_threshold_mb,
            "largest_table": largest_table,
            "largest_count": largest_count,
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
