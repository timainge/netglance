"""DHCP monitoring and rogue server detection."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from netglance.store.models import DhcpAlert, DhcpEvent

# DHCP message type names (option 53 values)
_DHCP_MESSAGE_TYPES: dict[int, str] = {
    1: "discover",
    2: "offer",
    3: "request",
    4: "decline",
    5: "ack",
    6: "nak",
    7: "release",
    8: "inform",
}


def _default_sniff_fn(filter: str, timeout: float, iface: str | None) -> list:
    """Default packet capture using scapy."""
    try:
        from scapy.all import sniff as scapy_sniff  # type: ignore[import]

        kwargs: dict = {"filter": filter, "timeout": timeout, "store": True}
        if iface:
            kwargs["iface"] = iface
        return list(scapy_sniff(**kwargs))
    except Exception:
        return []


def parse_dhcp_packet(packet) -> DhcpEvent | None:
    """Extract DhcpEvent from a scapy DHCP packet.

    Looks for DHCP message type option (option 53):
      1=Discover, 2=Offer, 3=Request, 5=ACK, 6=NAK

    Extracts: client MAC (chaddr), client IP, server IP, offered IP,
    gateway (option 3), DNS servers (option 6), lease time (option 51).

    Returns None if packet is not a valid DHCP packet.
    """
    try:
        # Check for required layers
        if not (hasattr(packet, "haslayer") and packet.haslayer("DHCP")):
            return None

        bootp = packet.getlayer("BOOTP")
        dhcp = packet.getlayer("DHCP")

        if bootp is None or dhcp is None:
            return None

        # Parse DHCP options into a dict
        options: dict[str | int, object] = {}
        for opt in dhcp.options:
            if isinstance(opt, tuple) and len(opt) >= 2:
                options[opt[0]] = opt[1]
            elif opt == "end":
                break

        # DHCP message type is required
        msg_type_num = options.get("message-type")
        if msg_type_num is None:
            return None

        event_type = _DHCP_MESSAGE_TYPES.get(int(msg_type_num), f"type_{msg_type_num}")

        # Extract client MAC from chaddr field
        client_mac = ""
        if hasattr(bootp, "chaddr"):
            raw_mac = bootp.chaddr
            if isinstance(raw_mac, bytes):
                # Take first 6 bytes
                client_mac = ":".join(f"{b:02x}" for b in raw_mac[:6])
            else:
                client_mac = str(raw_mac)

        # Extract IPs — bootp fields
        client_ip: str | None = None
        offered_ip: str | None = None
        server_ip: str | None = None
        server_mac: str | None = None

        if hasattr(bootp, "ciaddr"):
            ip = str(bootp.ciaddr)
            if ip and ip != "0.0.0.0":
                client_ip = ip

        if hasattr(bootp, "yiaddr"):
            ip = str(bootp.yiaddr)
            if ip and ip != "0.0.0.0":
                offered_ip = ip

        if hasattr(bootp, "siaddr"):
            ip = str(bootp.siaddr)
            if ip and ip != "0.0.0.0":
                server_ip = ip

        # Try getting server IP from Ethernet/IP layer if not in bootp
        if server_ip is None and packet.haslayer("IP"):
            ip_layer = packet.getlayer("IP")
            src = str(ip_layer.src)
            # Server sends Offers and ACKs from its IP
            if event_type in ("offer", "ack", "nak") and src != "0.0.0.0":
                server_ip = src

        # Get server MAC from Ethernet layer
        if packet.haslayer("Ether"):
            eth = packet.getlayer("Ether")
            if event_type in ("offer", "ack", "nak"):
                server_mac = str(eth.src)

        # DHCP options
        gateway: str | None = None
        dns_servers: list[str] = []
        lease_time: int | None = None

        # Option 3: router/gateway
        router = options.get("router")
        if router:
            if isinstance(router, (list, tuple)):
                gateway = str(router[0]) if router else None
            else:
                gateway = str(router)

        # Option 6: DNS servers
        dns = options.get("name_server")
        if dns:
            if isinstance(dns, (list, tuple)):
                dns_servers = [str(d) for d in dns]
            else:
                dns_servers = [str(dns)]

        # Option 51: lease time
        lt = options.get("lease_time")
        if lt is not None:
            try:
                lease_time = int(lt)
            except (ValueError, TypeError):
                pass

        return DhcpEvent(
            event_type=event_type,
            client_mac=client_mac,
            client_ip=client_ip,
            server_mac=server_mac,
            server_ip=server_ip,
            offered_ip=offered_ip,
            gateway=gateway,
            dns_servers=dns_servers,
            lease_time=lease_time,
            timestamp=datetime.now(),
        )

    except Exception:
        return None


def get_dhcp_fingerprint(packet) -> str | None:
    """Extract DHCP Option 55 (Parameter Request List) as a fingerprint string.

    Returns comma-separated option numbers, e.g. "1,3,6,15,28,51,58,59"
    Returns None if option 55 not present.
    """
    try:
        if not (hasattr(packet, "haslayer") and packet.haslayer("DHCP")):
            return None

        dhcp = packet.getlayer("DHCP")
        if dhcp is None:
            return None

        for opt in dhcp.options:
            if isinstance(opt, tuple) and len(opt) >= 2 and opt[0] == "param_req_list":
                param_list = opt[1]
                if isinstance(param_list, (bytes, bytearray)):
                    return ",".join(str(b) for b in param_list)
                elif isinstance(param_list, (list, tuple)):
                    return ",".join(str(v) for v in param_list)
                else:
                    return str(param_list)

        return None

    except Exception:
        return None


def sniff_dhcp(
    timeout: float = 30.0,
    interface: str | None = None,
    *,
    _sniff_fn=None,
) -> list[DhcpEvent]:
    """Capture DHCP packets on the network.

    Requires root/sudo privileges for raw packet capture.

    Args:
        timeout: How long to listen for packets (seconds).
        interface: Network interface to listen on. Uses default if None.
        _sniff_fn: Injectable function(filter, timeout, iface) returning packets.

    Returns:
        List of DhcpEvent parsed from captured packets.
    """
    sniff_fn = _sniff_fn or _default_sniff_fn
    packets = sniff_fn(
        filter="udp and (port 67 or port 68)",
        timeout=timeout,
        iface=interface,
    )
    events: list[DhcpEvent] = []
    for pkt in packets:
        event = parse_dhcp_packet(pkt)
        if event is not None:
            events.append(event)
    return events


def detect_rogue_servers(
    events: list[DhcpEvent],
    expected_servers: list[str] | None = None,
) -> list[DhcpAlert]:
    """Check for unauthorized DHCP servers.

    Examines Offer and ACK events. If server_ip is not in expected_servers,
    generates a DhcpAlert with alert_type="rogue_server", severity="critical".

    If expected_servers is None, auto-detects: the most common server is
    "expected", any others are flagged as rogue.

    Args:
        events: List of DhcpEvent from sniff_dhcp.
        expected_servers: List of authorized DHCP server IPs. Auto-detects if None.

    Returns:
        List of DhcpAlert for each rogue server detected.
    """
    if not events:
        return []

    # Only look at server-originated events
    server_events = [
        e for e in events
        if e.event_type in ("offer", "ack") and e.server_ip
    ]

    if not server_events:
        return []

    if expected_servers is None:
        # Auto-detect: count server IPs, most frequent is "expected"
        counts: Counter[str] = Counter(
            e.server_ip for e in server_events if e.server_ip
        )
        if not counts:
            return []
        most_common_ip, _ = counts.most_common(1)[0]
        expected_set = {most_common_ip}
    else:
        expected_set = set(expected_servers)

    alerts: list[DhcpAlert] = []
    seen_rogue: set[str] = set()

    for event in server_events:
        if event.server_ip and event.server_ip not in expected_set:
            if event.server_ip not in seen_rogue:
                seen_rogue.add(event.server_ip)
                alerts.append(
                    DhcpAlert(
                        alert_type="rogue_server",
                        severity="critical",
                        description=(
                            f"Unauthorized DHCP server detected at {event.server_ip} "
                            f"(MAC: {event.server_mac or 'unknown'})"
                        ),
                        server_ip=event.server_ip,
                        server_mac=event.server_mac or "",
                        timestamp=event.timestamp,
                    )
                )

    return alerts


def monitor_dhcp(
    duration: float = 60.0,
    interface: str | None = None,
    expected_servers: list[str] | None = None,
    *,
    _sniff_fn=None,
) -> tuple[list[DhcpEvent], list[DhcpAlert]]:
    """Monitor DHCP traffic and detect anomalies.

    Main entry point. Captures DHCP packets then checks for rogue servers.

    Requires root/sudo privileges for raw packet capture.

    Args:
        duration: How long to monitor in seconds.
        interface: Network interface to listen on. Uses default if None.
        expected_servers: Authorized DHCP server IPs. Auto-detects if None.
        _sniff_fn: Injectable function for testing (bypasses scapy).

    Returns:
        Tuple of (events, alerts).
    """
    events = sniff_dhcp(timeout=duration, interface=interface, _sniff_fn=_sniff_fn)
    alerts = detect_rogue_servers(events, expected_servers=expected_servers)
    return events, alerts
