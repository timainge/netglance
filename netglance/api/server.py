"""FastAPI-based REST API server for netglance.

Exposes all netglance modules as a JSON HTTP API under /api/v1/.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader

from netglance.validation import validate_host, validate_port_range, validate_subnet

# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses and datetimes to JSON-serialisable dicts."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _make_auth_dep(api_key: str | None):
    """Return a FastAPI dependency that enforces API key auth when key is set."""

    async def _check_key(key: str | None = Security(_API_KEY_HEADER)) -> None:
        if api_key and key != api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return _check_key


# ---------------------------------------------------------------------------
# Period parsing helper
# ---------------------------------------------------------------------------

def _parse_period(period: str) -> timedelta:
    """Convert period string like '24h', '7d' to timedelta."""
    suffix_map = {"h": "hours", "d": "days", "m": "minutes"}
    if period and period[-1] in suffix_map and period[:-1].isdigit():
        value = int(period[:-1])
        return timedelta(**{suffix_map[period[-1]]: value})
    raise ValueError(f"Unknown period format: {period!r}")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_DEFAULT_CORS_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
]


def create_app(
    api_key: str | None = None,
    db_path: str | None = None,
    cors_origins: list[str] | None = None,
    *,
    # Dependency-injection overrides for testability
    _discover_fn: Callable | None = None,
    _ping_fn: Callable | None = None,
    _gateway_fn: Callable | None = None,
    _dns_fn: Callable | None = None,
    _scan_fn: Callable | None = None,
    _arp_fn: Callable | None = None,
    _tls_fn: Callable | None = None,
    _wifi_fn: Callable | None = None,
    _report_fn: Callable | None = None,
    _speed_fn: Callable | None = None,
    _vpn_fn: Callable | None = None,
    _uptime_fn: Callable | None = None,
    _perf_fn: Callable | None = None,
    _baseline_fn: Callable | None = None,
    _store_fn: Callable | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        api_key: API key for authentication. If None, auth is disabled.
        db_path: Path to the SQLite database. Uses default if None.
        cors_origins: Allowed CORS origins. Defaults to localhost only.
        _*_fn: Injectable module functions for testing.

    Returns:
        Configured FastAPI instance.
    """
    # Resolve effective API key (env var wins if set)
    effective_key = os.environ.get("NETGLANCE_API_KEY") or api_key

    app = FastAPI(
        title="netglance API",
        description="netglance REST API — home network health checks.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — localhost only by default; user can widen via cors_origins
    effective_origins = cors_origins if cors_origins is not None else _DEFAULT_CORS_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=effective_origins,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["X-API-Key"],
    )

    auth_dep = _make_auth_dep(effective_key)

    # ------------------------------------------------------------------
    # Helper: get a store instance
    # ------------------------------------------------------------------

    def _get_store():
        if _store_fn is not None:
            return _store_fn()
        from netglance.store.db import Store
        path_kwargs = {"db_path": db_path} if db_path else {}
        store = Store(**path_kwargs)
        store.init_db()
        return store

    # ------------------------------------------------------------------
    # /api/v1/health — API health check (no auth required)
    # ------------------------------------------------------------------

    @app.get("/api/v1/health")
    async def health_check() -> dict:
        """Simple health check for monitoring the API itself."""
        return {"status": "ok", "timestamp": datetime.now().isoformat()}

    # ------------------------------------------------------------------
    # /api/v1/discover
    # ------------------------------------------------------------------

    @app.get("/api/v1/discover", dependencies=[Depends(auth_dep)])
    async def discover(subnet: str = "192.168.1.0/24") -> list:
        """Discover devices on the network via ARP/mDNS."""
        try:
            subnet = validate_subnet(subnet)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            if _discover_fn is not None:
                devices = _discover_fn(subnet)
            else:
                from netglance.modules.discover import discover_all
                devices = discover_all(subnet)
            return [_to_dict(d) for d in devices]
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/ping/{host}
    # ------------------------------------------------------------------

    @app.get("/api/v1/ping/gateway", dependencies=[Depends(auth_dep)])
    async def ping_gateway() -> dict:
        """Ping the default gateway."""
        try:
            if _gateway_fn is not None:
                result = _gateway_fn()
            else:
                from netglance.modules.ping import check_gateway
                result = check_gateway()
            return _to_dict(result)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/v1/ping/{host}", dependencies=[Depends(auth_dep)])
    async def ping_host(host: str, count: int = 4) -> dict:
        """Ping a specific host."""
        try:
            host = validate_host(host)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            if _ping_fn is not None:
                result = _ping_fn(host, count=count)
            else:
                from netglance.modules.ping import ping_host as _ph
                result = _ph(host, count=count)
            return _to_dict(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/dns/health
    # ------------------------------------------------------------------

    @app.get("/api/v1/dns/health", dependencies=[Depends(auth_dep)])
    async def dns_health() -> dict:
        """Check DNS health and consistency."""
        try:
            if _dns_fn is not None:
                report = _dns_fn()
            else:
                from netglance.modules.dns import check_consistency
                report = check_consistency("example.com")
            return _to_dict(report)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/scan/{host}
    # ------------------------------------------------------------------

    @app.get("/api/v1/scan/{host}", dependencies=[Depends(auth_dep)])
    async def scan_host(host: str, ports: str = "1-1024") -> dict:
        """Scan ports on a host."""
        try:
            host = validate_host(host)
            ports = validate_port_range(ports)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            if _scan_fn is not None:
                result = _scan_fn(host, ports=ports)
            else:
                from netglance.modules.scan import scan_host as _sh
                result = _sh(host, ports=ports)
            return _to_dict(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/arp
    # ------------------------------------------------------------------

    @app.get("/api/v1/arp", dependencies=[Depends(auth_dep)])
    async def arp_table() -> dict:
        """Get ARP table and check for anomalies."""
        try:
            if _arp_fn is not None:
                entries, alerts = _arp_fn()
            else:
                from netglance.modules.arp import check_arp_anomalies, get_arp_table
                entries = get_arp_table()
                alerts = check_arp_anomalies(entries)
            return {
                "entries": [_to_dict(e) for e in entries],
                "alerts": [_to_dict(a) for a in alerts],
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/tls/{host}
    # ------------------------------------------------------------------

    @app.get("/api/v1/tls/{host}", dependencies=[Depends(auth_dep)])
    async def tls_check(host: str, port: int = 443) -> dict:
        """Check TLS certificate for a host."""
        try:
            host = validate_host(host)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            if _tls_fn is not None:
                result = _tls_fn(host, port=port)
            else:
                from netglance.modules.tls import check_certificate
                result = check_certificate(host, port=port)
            return _to_dict(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/wifi
    # ------------------------------------------------------------------

    @app.get("/api/v1/wifi", dependencies=[Depends(auth_dep)])
    async def wifi_scan() -> dict:
        """Scan WiFi environment."""
        try:
            if _wifi_fn is not None:
                result = _wifi_fn()
            else:
                from netglance.modules.wifi import current_connection, scan_wifi
                conn = current_connection()
                networks = scan_wifi()
                return {
                    "current": _to_dict(conn) if conn else None,
                    "networks": [_to_dict(n) for n in networks],
                }
            # If _wifi_fn is injected it returns the full dict
            return _to_dict(result) if not isinstance(result, dict) else result
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/report
    # ------------------------------------------------------------------

    @app.get("/api/v1/report", dependencies=[Depends(auth_dep)])
    async def full_report(subnet: str = "192.168.1.0/24") -> dict:
        """Generate a full network health report."""
        try:
            subnet = validate_subnet(subnet)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            if _report_fn is not None:
                report = _report_fn(subnet=subnet)
            else:
                from netglance.modules.report import generate_report
                store = _get_store()
                report = generate_report(subnet=subnet, _store=store)
            return _to_dict(report)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/speed
    # ------------------------------------------------------------------

    @app.get("/api/v1/speed", dependencies=[Depends(auth_dep)])
    async def speed_test(provider: str = "cloudflare") -> dict:
        """Run an internet speed test."""
        try:
            if _speed_fn is not None:
                result = _speed_fn(provider=provider)
            else:
                from netglance.modules.speed import run_speedtest
                result = run_speedtest(provider=provider)
            return _to_dict(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/vpn
    # ------------------------------------------------------------------

    @app.get("/api/v1/vpn", dependencies=[Depends(auth_dep)])
    async def vpn_check() -> dict:
        """Check for VPN leaks."""
        try:
            if _vpn_fn is not None:
                result = _vpn_fn()
            else:
                from netglance.modules.vpn import run_vpn_leak_check
                result = run_vpn_leak_check()
            return _to_dict(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/uptime/{host}
    # ------------------------------------------------------------------

    @app.get("/api/v1/uptime/{host}", dependencies=[Depends(auth_dep)])
    async def uptime_summary(host: str, period: str = "24h") -> dict:
        """Get uptime summary for a host."""
        try:
            host = validate_host(host)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            if _uptime_fn is not None:
                result = _uptime_fn(host, period=period)
            else:
                from netglance.modules.uptime import get_uptime_summary
                result = get_uptime_summary(host, period=period)
            return _to_dict(result)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/perf/{host}
    # ------------------------------------------------------------------

    @app.get("/api/v1/perf/{host}", dependencies=[Depends(auth_dep)])
    async def perf_check(host: str) -> dict:
        """Run network performance assessment for a host."""
        try:
            host = validate_host(host)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            if _perf_fn is not None:
                result = _perf_fn(host)
            else:
                from netglance.modules.perf import run_performance_test
                result = run_performance_test(host)
            return _to_dict(result)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/baseline  (current baseline)
    # ------------------------------------------------------------------

    @app.get("/api/v1/baseline", dependencies=[Depends(auth_dep)])
    async def get_baseline() -> dict:
        """Get the current (most recent) network baseline."""
        try:
            if _baseline_fn is not None:
                result = _baseline_fn()
            else:
                store = _get_store()
                result = store.get_latest_baseline()
            if result is None:
                raise HTTPException(status_code=404, detail="No baseline found")
            return result if isinstance(result, dict) else _to_dict(result)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/baselines  (list all)
    # ------------------------------------------------------------------

    @app.get("/api/v1/baselines", dependencies=[Depends(auth_dep)])
    async def list_baselines() -> list:
        """List all saved network baselines."""
        try:
            store = _get_store()
            return store.list_baselines()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/devices  (inventory from last discovery)
    # ------------------------------------------------------------------

    @app.get("/api/v1/devices", dependencies=[Depends(auth_dep)])
    async def device_inventory() -> list:
        """Get device inventory from the last discovery stored in the baseline."""
        try:
            store = _get_store()
            baseline = store.get_latest_baseline()
            if baseline is None:
                return []
            return baseline.get("devices", [])
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/metrics
    # ------------------------------------------------------------------

    @app.get("/api/v1/metrics", dependencies=[Depends(auth_dep)])
    async def get_metrics(
        metric: str = "ping.gateway.latency",
        period: str = "24h",
    ) -> dict:
        """Get time-series data for a metric."""
        try:
            delta = _parse_period(period)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            store = _get_store()
            since = datetime.now() - delta
            series = store.get_metric_series(metric, since=since)
            return {"metric": metric, "period": period, "series": series}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.get("/api/v1/metrics/list", dependencies=[Depends(auth_dep)])
    async def list_metrics() -> list:
        """List all available metric names."""
        try:
            store = _get_store()
            return store.list_metrics()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # /api/v1/alerts
    # ------------------------------------------------------------------

    @app.get("/api/v1/alerts", dependencies=[Depends(auth_dep)])
    async def get_alerts(limit: int = 50) -> list:
        """Get the alert log."""
        try:
            store = _get_store()
            rows = store.conn.execute(
                "SELECT id, ts, metric, value, threshold, message, acknowledged "
                "FROM alert_log ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "ts": row["ts"],
                    "metric": row["metric"],
                    "value": row["value"],
                    "threshold": row["threshold"],
                    "message": row["message"],
                    "acknowledged": bool(row["acknowledged"]),
                }
                for row in rows
            ]
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ------------------------------------------------------------------
    # Generic error handler
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def _generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )

    return app
