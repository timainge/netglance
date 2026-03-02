"""Wireless network environment analysis.

Provides WiFi scanning, current connection info, rogue AP detection,
and channel utilization analysis using macOS system utilities.

Primary method uses the ``airport`` CLI utility.  On modern macOS (14+)
the airport binary may be missing or return empty output, so we fall
back to ``networksetup`` commands which are available on all macOS
versions.
"""

from __future__ import annotations

import platform
import subprocess

from netglance.store.models import WifiNetwork

AIRPORT_BIN = (
    "/System/Library/PrivateFrameworks/Apple80211.framework"
    "/Versions/Current/Resources/airport"
)


def _run_airport(
    args: list[str],
    *,
    _run_fn: object | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the airport CLI with the given arguments.

    Args:
        args: Command-line arguments to pass to airport.
        _run_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        CompletedProcess with stdout/stderr.

    Raises:
        RuntimeError: If not running on macOS or the command fails.
    """
    run_fn = _run_fn or subprocess.run
    if _run_fn is None and platform.system() != "Darwin":
        raise RuntimeError(
            "WiFi scanning via airport is only supported on macOS. "
            f"Current platform: {platform.system()}"
        )
    result = run_fn(
        [AIRPORT_BIN] + args,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result  # type: ignore[return-value]


def _parse_scan_output(raw: str) -> list[WifiNetwork]:
    """Parse the tabular output of ``airport -s`` into WifiNetwork objects.

    The airport -s output has a header line with column names, followed by
    data lines. The header positions indicate where each column starts.
    Example header::

                                SSID BSSID             RSSI CHANNEL HT CC SECURITY ...

    The SSID field is right-justified up to the SSID header end position.
    """
    lines = raw.rstrip().splitlines()
    if not lines:
        return []
    # Drop any leading blank lines (preserve indentation of non-blank lines)
    while lines and not lines[0].strip():
        lines.pop(0)

    # Find the header line (contains "SSID" and "BSSID")
    header_idx = -1
    for i, line in enumerate(lines):
        if "SSID" in line and "BSSID" in line and "RSSI" in line:
            header_idx = i
            break

    if header_idx == -1:
        return []

    header = lines[header_idx]

    # Determine column start positions from the header.
    # Column names in order: SSID, BSSID, RSSI, CHANNEL, HT, CC, SECURITY
    col_starts: dict[str, int] = {}
    for col_name in ["BSSID", "RSSI", "CHANNEL", "HT", "CC", "SECURITY"]:
        idx = header.find(col_name)
        if idx != -1:
            col_starts[col_name] = idx

    # SSID ends where BSSID starts (SSID is right-justified before BSSID)
    ssid_end = col_starts.get("BSSID", 33)

    networks: list[WifiNetwork] = []
    for line in lines[header_idx + 1 :]:
        if not line.strip():
            continue

        # SSID is everything up to the BSSID column start, stripped
        ssid = line[:ssid_end].strip()

        # Extract fields by column positions
        bssid_start = col_starts.get("BSSID", 33)
        rssi_start = col_starts.get("RSSI", 51)
        channel_start = col_starts.get("CHANNEL", 56)
        ht_start = col_starts.get("HT", 64)
        security_start = col_starts.get("SECURITY", 70)

        bssid = line[bssid_start:rssi_start].strip()
        rssi_str = line[rssi_start:channel_start].strip()
        channel_str = line[channel_start:ht_start].strip()
        security = line[security_start:].strip() if security_start < len(line) else ""

        # Parse RSSI
        try:
            signal_dbm = int(rssi_str)
        except (ValueError, IndexError):
            signal_dbm = 0

        # Parse channel - may contain comma for dual-band like "36,1"
        channel = 0
        band = ""
        if channel_str:
            # Take the primary channel number (before any comma)
            primary = channel_str.split(",")[0].strip()
            try:
                channel = int(primary)
            except ValueError:
                channel = 0
            # Determine band from channel number
            if channel <= 14:
                band = "2.4 GHz"
            elif channel <= 196:
                band = "5 GHz"
            else:
                band = "6 GHz"

        if bssid:  # Only add if we got a valid BSSID
            networks.append(
                WifiNetwork(
                    ssid=ssid,
                    bssid=bssid,
                    channel=channel,
                    band=band,
                    signal_dbm=signal_dbm,
                    security=security,
                )
            )

    return networks


def _parse_info_output(raw: str) -> WifiNetwork | None:
    """Parse the output of ``airport -I`` into a WifiNetwork.

    The output is a series of key: value lines like::

             agrCtlRSSI: -55
             agrCtlNoise: -88
                   SSID: MyNetwork
                  BSSID: aa:bb:cc:dd:ee:ff
              ...
    """
    if not raw.strip():
        return None

    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()

    ssid = fields.get("SSID", "")
    bssid = fields.get("BSSID", "")

    if not ssid and not bssid:
        return None

    # Parse channel
    channel = 0
    band = ""
    channel_str = fields.get("channel", "")
    if channel_str:
        primary = channel_str.split(",")[0].strip()
        try:
            channel = int(primary)
        except ValueError:
            channel = 0
        if channel <= 14:
            band = "2.4 GHz"
        elif channel <= 196:
            band = "5 GHz"
        else:
            band = "6 GHz"

    # Parse signal and noise
    signal_dbm = 0
    noise_dbm: int | None = None
    try:
        signal_dbm = int(fields.get("agrCtlRSSI", "0"))
    except ValueError:
        pass
    try:
        noise_val = fields.get("agrCtlNoise", "")
        if noise_val:
            noise_dbm = int(noise_val)
    except ValueError:
        pass

    security = fields.get("link auth", "")

    return WifiNetwork(
        ssid=ssid,
        bssid=bssid,
        channel=channel,
        band=band,
        signal_dbm=signal_dbm,
        noise_dbm=noise_dbm,
        security=security,
    )


def _detect_wifi_interface() -> str:
    """Return the name of the primary WiFi network interface.

    On most Macs this is ``en0``, but we check ``networksetup`` to be
    safe.  Falls back to ``en0`` if detection fails.
    """
    try:
        result = subprocess.run(
            ["networksetup", "-listallhardwareports"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Parse output looking for "Hardware Port: Wi-Fi" followed by "Device: enX"
        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i + 1, min(i + 4, len(lines))):
                    if lines[j].strip().startswith("Device:"):
                        return lines[j].split(":", 1)[1].strip()
    except Exception:
        pass
    return "en0"


def _run_networksetup(
    args: list[str],
    *,
    _run_fn: object | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a ``networksetup`` command.

    Args:
        args: Arguments to pass to networksetup.
        _run_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        CompletedProcess with stdout/stderr.
    """
    run_fn = _run_fn or subprocess.run
    if _run_fn is None and platform.system() != "Darwin":
        raise RuntimeError(
            "WiFi detection via networksetup is only supported on macOS. "
            f"Current platform: {platform.system()}"
        )
    result = run_fn(
        ["networksetup"] + args,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return result  # type: ignore[return-value]


def _parse_networksetup_output(raw: str) -> str | None:
    """Parse the output of ``networksetup -getairportnetwork <iface>``.

    Expected output when connected::

        Current Wi-Fi Network: MyNetwork

    Expected output when disconnected::

        You are not associated with an AirPort network.

    Returns the SSID string, or None if not connected.
    """
    if not raw or not raw.strip():
        return None

    line = raw.strip().splitlines()[0]

    # Connected: "Current Wi-Fi Network: <SSID>"
    if ":" in line and ("Wi-Fi Network" in line or "AirPort Network" in line):
        _, _, ssid = line.partition(":")
        ssid = ssid.strip()
        if ssid:
            return ssid

    return None


def _current_connection_via_networksetup(
    *,
    _run_fn: object | None = None,
) -> WifiNetwork | None:
    """Detect current WiFi connection using ``networksetup`` as a fallback.

    This is used when the ``airport`` binary is missing or returns empty
    output on modern macOS.

    Args:
        _run_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        WifiNetwork with at least the SSID populated, or None if not
        connected.
    """
    # Determine the WiFi interface name
    iface = "en0"
    if _run_fn is None:
        iface = _detect_wifi_interface()

    # Get SSID from networksetup
    result = _run_networksetup(
        ["-getairportnetwork", iface],
        _run_fn=_run_fn,
    )
    ssid = _parse_networksetup_output(result.stdout)
    if not ssid:
        return None

    # We have a connection -- return what we know.
    # networksetup only gives us the SSID reliably, but that is enough
    # to confirm WiFi is connected.
    return WifiNetwork(
        ssid=ssid,
        bssid="",
        channel=0,
        band="",
        signal_dbm=0,
        security="",
    )


def scan_wifi(*, _run_fn: object | None = None) -> list[WifiNetwork]:
    """Scan for nearby WiFi networks.

    Uses the macOS ``airport -s`` command to discover wireless networks
    in range.

    Args:
        _run_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        List of WifiNetwork dataclass instances, one per discovered network.

    Raises:
        RuntimeError: If not running on macOS.
    """
    result = _run_airport(["-s"], _run_fn=_run_fn)
    return _parse_scan_output(result.stdout)


def current_connection(
    *,
    _run_fn: object | None = None,
    _networksetup_run_fn: object | None = None,
) -> WifiNetwork | None:
    """Get information about the current WiFi connection.

    Tries the macOS ``airport -I`` command first.  If the airport binary
    is missing or returns empty/unparseable output, falls back to
    ``networksetup -getairportnetwork`` which is available on all macOS
    versions.

    Args:
        _run_fn: Injectable replacement for subprocess.run (for testing)
            used for the airport command.
        _networksetup_run_fn: Injectable replacement for subprocess.run
            (for testing) used for the networksetup fallback.  If not
            provided, ``_run_fn`` is used for the fallback as well.

    Returns:
        WifiNetwork for the current connection, or None if not connected.

    Raises:
        RuntimeError: If not running on macOS.
    """
    # --- Primary method: airport -I ---
    try:
        result = _run_airport(["-I"], _run_fn=_run_fn)
        conn = _parse_info_output(result.stdout)
        if conn is not None:
            return conn
    except (FileNotFoundError, OSError):
        # airport binary not found -- fall through to networksetup
        pass

    # --- Fallback: networksetup ---
    fallback_run_fn = _networksetup_run_fn if _networksetup_run_fn is not None else _run_fn
    return _current_connection_via_networksetup(_run_fn=fallback_run_fn)


def detect_rogue_aps(
    known_ssids: dict[str, list[str]],
    networks: list[WifiNetwork] | None = None,
    *,
    _run_fn: object | None = None,
) -> list[WifiNetwork]:
    """Detect potential rogue access points.

    A rogue AP is a network broadcasting a known SSID but from an
    unrecognized BSSID (MAC address). This could indicate an evil-twin
    attack.

    Args:
        known_ssids: Mapping of SSID -> list of known/trusted BSSIDs for
            that SSID.
        networks: Pre-scanned network list. If None, performs a fresh scan.
        _run_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        List of WifiNetwork objects that match known SSIDs but have
        unknown BSSIDs.
    """
    if networks is None:
        networks = scan_wifi(_run_fn=_run_fn)

    rogues: list[WifiNetwork] = []
    for net in networks:
        if net.ssid in known_ssids:
            trusted_bssids = [b.lower() for b in known_ssids[net.ssid]]
            if net.bssid.lower() not in trusted_bssids:
                rogues.append(net)

    return rogues


def channel_utilization(
    networks: list[WifiNetwork] | None = None,
    *,
    _run_fn: object | None = None,
) -> dict[int, int]:
    """Count how many networks occupy each WiFi channel.

    Args:
        networks: Pre-scanned network list. If None, performs a fresh scan.
        _run_fn: Injectable replacement for subprocess.run (for testing).

    Returns:
        Dict mapping channel number to count of networks on that channel.
    """
    if networks is None:
        networks = scan_wifi(_run_fn=_run_fn)

    counts: dict[int, int] = {}
    for net in networks:
        if net.channel > 0:
            counts[net.channel] = counts.get(net.channel, 0) + 1

    return dict(sorted(counts.items()))


def signal_bar(dbm: int) -> str:
    """Convert a signal strength in dBm to a visual bar.

    Signal quality mapping:
        >= -50 dBm : Excellent (5 bars)
        >= -60 dBm : Good      (4 bars)
        >= -70 dBm : Fair      (3 bars)
        >= -80 dBm : Weak      (2 bars)
        >= -90 dBm : Very weak (1 bar)
        <  -90 dBm : No signal (0 bars)

    Args:
        dbm: Signal strength in dBm (negative number, e.g. -55).

    Returns:
        A string of filled and empty bar characters, e.g. "████░".
    """
    filled = "\u2588"  # Full block
    empty = "\u2591"   # Light shade block
    total_bars = 5

    if dbm >= -50:
        bars = 5
    elif dbm >= -60:
        bars = 4
    elif dbm >= -70:
        bars = 3
    elif dbm >= -80:
        bars = 2
    elif dbm >= -90:
        bars = 1
    else:
        bars = 0

    return filled * bars + empty * (total_bars - bars)
