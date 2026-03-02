"""Inventory export module — JSON, CSV, and HTML export of device/scan data."""

from __future__ import annotations

import csv
import html
import io
import json
from datetime import datetime
from pathlib import Path

from netglance.store.models import Device, ExportResult, HostScanResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _datetime_serializer(obj):
    """JSON default serializer for datetime objects."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _open_ports_str(ip: str, scans: dict[str, HostScanResult] | None) -> str:
    """Return comma-separated open port numbers for a device, or empty string."""
    if not scans or ip not in scans:
        return ""
    open_ports = [str(p.port) for p in scans[ip].ports if p.state == "open"]
    return ",".join(open_ports)


def _device_to_dict(device: Device, scans: dict[str, HostScanResult] | None) -> dict:
    """Convert a Device (with optional scan data) to a JSON-friendly dict."""
    d: dict = {
        "ip": device.ip,
        "mac": device.mac,
        "hostname": device.hostname,
        "vendor": device.vendor,
        "discovery_method": device.discovery_method,
        "first_seen": device.first_seen.isoformat(),
        "last_seen": device.last_seen.isoformat(),
    }
    if scans and device.ip in scans:
        scan = scans[device.ip]
        d["open_ports"] = [
            {
                "port": p.port,
                "state": p.state,
                "service": p.service,
                "version": p.version,
                "banner": p.banner,
            }
            for p in scan.ports
            if p.state == "open"
        ]
        d["scan_time"] = scan.scan_time.isoformat()
        d["scan_duration_s"] = scan.scan_duration_s
    else:
        d["open_ports"] = []
    return d


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def export_devices_json(
    devices: list[Device],
    scans: dict[str, HostScanResult] | None = None,
    output: Path | None = None,
) -> str:
    """Export device inventory as JSON string.

    If output path given, also write to file.
    Includes scan results merged with devices if provided.

    Returns:
        The JSON string.
    """
    records = [_device_to_dict(d, scans) for d in devices]
    content = json.dumps(records, indent=2, default=_datetime_serializer)
    if output is not None:
        _write_file(output, content)
    return content


def export_devices_csv(
    devices: list[Device],
    scans: dict[str, HostScanResult] | None = None,
    output: Path | None = None,
) -> str:
    """Export device inventory as CSV string.

    Columns: ip, mac, hostname, vendor, discovery_method, first_seen, last_seen, open_ports.
    open_ports = comma-separated port numbers from scan results.

    If output path given, also write to file.

    Returns:
        The CSV string.
    """
    buf = io.StringIO()
    fieldnames = [
        "ip", "mac", "hostname", "vendor", "discovery_method",
        "first_seen", "last_seen", "open_ports",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for device in devices:
        writer.writerow({
            "ip": device.ip,
            "mac": device.mac,
            "hostname": device.hostname or "",
            "vendor": device.vendor or "",
            "discovery_method": device.discovery_method,
            "first_seen": device.first_seen.isoformat(),
            "last_seen": device.last_seen.isoformat(),
            "open_ports": _open_ports_str(device.ip, scans),
        })
    content = buf.getvalue()
    if output is not None:
        _write_file(output, content)
    return content


def export_devices_html(
    devices: list[Device],
    scans: dict[str, HostScanResult] | None = None,
    output: Path | None = None,
) -> str:
    """Export as standalone HTML table.

    Generates a self-contained HTML page with a styled table.
    Columns: ip, mac, hostname, vendor, discovery_method, first_seen, last_seen, open_ports.

    If output path given, also write to file.

    Returns:
        The HTML string.
    """
    rows_html = []
    for device in devices:
        open_ports = _open_ports_str(device.ip, scans)
        cells = [
            html.escape(device.ip),
            html.escape(device.mac),
            html.escape(device.hostname or ""),
            html.escape(device.vendor or ""),
            html.escape(device.discovery_method),
            html.escape(device.first_seen.isoformat()),
            html.escape(device.last_seen.isoformat()),
            html.escape(open_ports),
        ]
        row = "    <tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        rows_html.append(row)

    rows_block = "\n".join(rows_html) if rows_html else "    <tr><td colspan='8'>No devices found.</td></tr>"
    generated = datetime.now().isoformat(timespec="seconds")

    content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>netglance Device Inventory</title>
  <style>
    body {{ font-family: monospace; margin: 2em; background: #0d1117; color: #c9d1d9; }}
    h1 {{ color: #58a6ff; }}
    p.meta {{ color: #8b949e; font-size: 0.9em; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th {{ background: #161b22; color: #58a6ff; padding: 8px 12px; text-align: left; border: 1px solid #30363d; }}
    td {{ padding: 6px 12px; border: 1px solid #21262d; }}
    tr:nth-child(even) {{ background: #161b22; }}
    tr:hover {{ background: #1f2937; }}
  </style>
</head>
<body>
  <h1>netglance Device Inventory</h1>
  <p class="meta">Generated: {html.escape(generated)} &mdash; {len(devices)} device(s)</p>
  <table>
    <thead>
      <tr>
        <th>IP</th><th>MAC</th><th>Hostname</th><th>Vendor</th>
        <th>Discovery</th><th>First Seen</th><th>Last Seen</th><th>Open Ports</th>
      </tr>
    </thead>
    <tbody>
{rows_block}
    </tbody>
  </table>
</body>
</html>
"""
    if output is not None:
        _write_file(output, content)
    return content


def export_baseline_json(
    baseline: dict,
    output: Path | None = None,
) -> str:
    """Export full baseline as formatted JSON.

    If output path given, also write to file.

    Returns:
        The JSON string.
    """
    content = json.dumps(baseline, indent=2, default=_datetime_serializer)
    if output is not None:
        _write_file(output, content)
    return content
