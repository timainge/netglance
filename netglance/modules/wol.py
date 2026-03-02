"""Wake-on-LAN magic packet construction and sending."""

from __future__ import annotations

import re
import socket

from netglance.store.models import WolResult

# Regex patterns for MAC address formats
_MAC_COLON = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_MAC_DASH = re.compile(r"^([0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}$")
_MAC_PLAIN = re.compile(r"^[0-9a-fA-F]{12}$")

# Regex to loosely detect if a string looks like a MAC address (any format)
_MAC_LIKE = re.compile(
    r"^([0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}$|^[0-9a-fA-F]{12}$"
)


def _normalize_mac(mac: str) -> str:
    """Return 12 uppercase hex chars from a MAC string, raising ValueError if invalid."""
    mac = mac.strip()
    if _MAC_COLON.match(mac):
        return mac.replace(":", "").upper()
    if _MAC_DASH.match(mac):
        return mac.replace("-", "").upper()
    if _MAC_PLAIN.match(mac):
        return mac.upper()
    raise ValueError(
        f"Invalid MAC address: {mac!r}. "
        "Expected format: AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, or AABBCCDDEEFF."
    )


def build_magic_packet(mac: str) -> bytes:
    """Construct a WoL magic packet: 6x 0xFF followed by 16 repetitions of the MAC bytes.

    Args:
        mac: MAC address in AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, or AABBCCDDEEFF format.

    Returns:
        102-byte magic packet as bytes.

    Raises:
        ValueError: If the MAC address format is invalid.
    """
    mac_hex = _normalize_mac(mac)
    mac_bytes = bytes.fromhex(mac_hex)
    return b"\xff" * 6 + mac_bytes * 16


def _default_socket_fn(packet: bytes, broadcast: str, port: int) -> None:
    """Send a WoL packet using a UDP broadcast socket."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))


def send_wol(
    mac: str,
    broadcast: str = "255.255.255.255",
    port: int = 9,
    *,
    _socket_fn=None,
) -> WolResult:
    """Send a WoL magic packet via UDP broadcast.

    Args:
        mac: Target device MAC address.
        broadcast: Broadcast address to send the packet to.
        port: UDP port (default 9, also common: 7).
        _socket_fn: Injectable callable(packet_bytes, broadcast, port) for testing.
                    Defaults to a real UDP socket with SO_BROADCAST.

    Returns:
        WolResult with sent=True on success, sent=False on socket error.
    """
    socket_fn = _socket_fn or _default_socket_fn
    try:
        packet = build_magic_packet(mac)
        socket_fn(packet, broadcast, port)
        return WolResult(mac=mac, broadcast=broadcast, port=port, sent=True)
    except OSError:
        return WolResult(mac=mac, broadcast=broadcast, port=port, sent=False)


def _is_mac_address(value: str) -> bool:
    """Return True if value looks like a MAC address."""
    return bool(_MAC_LIKE.match(value.strip()))


def _default_store_fn() -> list[dict]:
    """Return inventory devices from the netglance database."""
    try:
        from netglance.store.db import Store

        store = Store()
        devices = store.get_devices()
        return [
            {
                "mac": d.mac,
                "hostname": d.hostname,
                "ip": d.ip,
            }
            for d in devices
        ]
    except Exception:
        return []


def wake_device(
    name_or_mac: str,
    broadcast: str = "255.255.255.255",
    port: int = 9,
    *,
    _store_fn=None,
    _socket_fn=None,
) -> WolResult:
    """Look up a device by name or MAC in the inventory and send a WoL packet.

    If name_or_mac looks like a MAC address, it is used directly without an
    inventory lookup. Otherwise the inventory is searched by hostname.

    Args:
        name_or_mac: A MAC address or device hostname to look up.
        broadcast: Broadcast address for the magic packet.
        port: UDP port for the magic packet.
        _store_fn: Injectable callable returning list of dicts with 'mac',
                   'hostname', and 'ip' keys (for testing).
        _socket_fn: Injectable callable(packet_bytes, broadcast, port).

    Returns:
        WolResult indicating whether the packet was sent.

    Raises:
        ValueError: If name_or_mac is not a MAC address and is not found
                    in the inventory.
    """
    if _is_mac_address(name_or_mac):
        return send_wol(name_or_mac, broadcast=broadcast, port=port, _socket_fn=_socket_fn)

    store_fn = _store_fn or _default_store_fn
    devices = store_fn()

    target_lower = name_or_mac.strip().lower()
    for device in devices:
        hostname = device.get("hostname") or ""
        if hostname.lower() == target_lower:
            result = send_wol(
                device["mac"], broadcast=broadcast, port=port, _socket_fn=_socket_fn
            )
            result.device_name = name_or_mac
            return result

    raise ValueError(
        f"Device {name_or_mac!r} not found in inventory. "
        "Try using the MAC address directly or run 'netglance discover' first."
    )
