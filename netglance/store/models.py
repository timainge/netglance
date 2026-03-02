"""Shared data models for netglance."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Device:
    ip: str
    mac: str
    hostname: str | None = None
    vendor: str | None = None
    discovery_method: str = "arp"
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)


@dataclass
class PingResult:
    host: str
    is_alive: bool
    avg_latency_ms: float | None = None
    min_latency_ms: float | None = None
    max_latency_ms: float | None = None
    packet_loss: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DnsResolverResult:
    resolver: str
    resolver_name: str
    query: str
    answers: list[str] = field(default_factory=list)
    response_time_ms: float = 0.0
    dnssec_valid: bool | None = None
    error: str | None = None


@dataclass
class PortResult:
    port: int
    state: str  # "open", "closed", "filtered"
    service: str | None = None
    version: str | None = None
    banner: str | None = None


@dataclass
class HostScanResult:
    host: str
    ports: list[PortResult] = field(default_factory=list)
    scan_time: datetime = field(default_factory=datetime.now)
    scan_duration_s: float = 0.0


@dataclass
class ArpEntry:
    ip: str
    mac: str
    interface: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ArpAlert:
    alert_type: str  # "mac_changed", "duplicate_ip", "duplicate_mac", "gateway_spoof"
    severity: str  # "warning", "critical"
    description: str
    old_value: str | None = None
    new_value: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class CertInfo:
    host: str
    port: int = 443
    subject: str = ""
    issuer: str = ""
    root_ca: str = ""
    fingerprint_sha256: str = ""
    not_before: datetime = field(default_factory=datetime.now)
    not_after: datetime = field(default_factory=datetime.now)
    san: list[str] = field(default_factory=list)
    chain_length: int = 0


@dataclass
class WifiNetwork:
    ssid: str
    bssid: str
    channel: int = 0
    band: str = ""
    signal_dbm: int = 0
    noise_dbm: int | None = None
    security: str = ""


@dataclass
class InterfaceStats:
    """Snapshot of cumulative network I/O counters for one interface."""

    interface: str
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class BandwidthSample:
    """Computed bandwidth rates between two snapshots for one interface."""

    interface: str
    tx_bytes_per_sec: float
    rx_bytes_per_sec: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class HttpProbeResult:
    """Structured result of an HTTP probe against a single URL."""

    url: str
    status_code: int
    suspicious_headers: dict[str, str] = field(default_factory=dict)
    injected_content: bool = False
    proxy_detected: bool = False
    details: list[str] = field(default_factory=list)


@dataclass
class TlsCheckResult:
    """Result of a TLS certificate check for a single host."""

    host: str
    cert: CertInfo
    is_trusted: bool = True
    is_intercepted: bool = False
    matches_baseline: bool | None = None
    details: str = ""


@dataclass
class DnsHealthReport:
    """Aggregated DNS health assessment."""

    resolvers_checked: int = 0
    consistent: bool = True
    fastest_resolver: str | None = None
    dnssec_supported: bool = False
    potential_hijack: bool = False
    details: list[DnsResolverResult] = field(default_factory=list)


@dataclass
class Hop:
    """A single hop along a traceroute path."""

    ttl: int
    ip: str | None = None
    hostname: str | None = None
    rtt_ms: float | None = None
    asn: str | None = None
    as_name: str | None = None


@dataclass
class TraceResult:
    """Complete result of a traceroute to a destination."""

    destination: str
    hops: list[Hop] = field(default_factory=list)
    reached: bool = False
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class CheckStatus:
    """Result of a single module health check."""

    module: str  # "discover", "ping", "dns", etc.
    status: str  # "pass", "warn", "fail", "error", "skip"
    summary: str  # one-line summary
    details: list[str] = field(default_factory=list)  # detailed findings


@dataclass
class HealthReport:
    """Aggregated health report across all checked modules."""

    timestamp: datetime
    checks: list[CheckStatus] = field(default_factory=list)
    overall_status: str = "pass"  # worst status across all checks


@dataclass
class NetworkBaseline:
    """Complete network state snapshot."""

    timestamp: datetime
    devices: list[Device]
    arp_table: list[ArpEntry]
    dns_results: list[DnsResolverResult]
    open_ports: dict[str, list[PortResult]]  # host -> ports
    gateway_mac: str | None
    label: str | None = None


# --- Phase 2 shared types ---


@dataclass
class SpeedTestResult:
    """Result from a speed test (download/upload/latency)."""

    download_mbps: float
    upload_mbps: float
    latency_ms: float
    jitter_ms: float | None = None
    server: str = ""
    server_location: str = ""
    provider: str = "cloudflare"
    download_bytes: int = 0
    upload_bytes: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class UptimeRecord:
    """Single uptime check result for a host."""

    host: str
    check_time: datetime
    is_alive: bool
    latency_ms: float | None = None


@dataclass
class UptimeSummary:
    """Aggregated uptime statistics for a host over a period."""

    host: str
    period: str
    uptime_pct: float
    total_checks: int
    successful_checks: int
    avg_latency_ms: float | None = None
    outages: list[dict] = field(default_factory=list)
    current_status: str = "unknown"
    last_seen: datetime | None = None


@dataclass
class NetworkPerformanceResult:
    """Result from network performance assessment (jitter, MTU, bufferbloat)."""

    target: str
    avg_latency_ms: float
    jitter_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    packet_loss_pct: float
    path_mtu: int | None = None
    bufferbloat_rating: str | None = None
    idle_latency_ms: float | None = None
    loaded_latency_ms: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class WolResult:
    """Result from a Wake-on-LAN magic packet send."""

    mac: str
    broadcast: str = "255.255.255.255"
    port: int = 9
    sent: bool = False
    device_name: str | None = None


@dataclass
class DhcpEvent:
    """A captured DHCP transaction event."""

    event_type: str
    client_mac: str
    client_ip: str | None = None
    server_mac: str | None = None
    server_ip: str | None = None
    offered_ip: str | None = None
    gateway: str | None = None
    dns_servers: list[str] = field(default_factory=list)
    lease_time: int | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DhcpAlert:
    """Alert from DHCP monitoring (e.g. rogue server detected)."""

    alert_type: str
    severity: str
    description: str
    server_ip: str = ""
    server_mac: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class VpnLeakReport:
    """Result from VPN leak detection assessment."""

    vpn_detected: bool
    vpn_interface: str | None = None
    dns_leak: bool = False
    dns_leak_resolvers: list[str] = field(default_factory=list)
    ipv6_leak: bool = False
    ipv6_addresses: list[str] = field(default_factory=list)
    split_tunnel: bool = False
    local_ip_exposed: bool = False
    details: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class IPv6Neighbor:
    """An IPv6 neighbor discovered via NDP."""

    ipv6_address: str
    mac: str
    address_type: str = ""
    interface: str = ""


@dataclass
class IPv6AuditResult:
    """Result from IPv6 audit (NDP, privacy, dual-stack)."""

    neighbors: list[IPv6Neighbor] = field(default_factory=list)
    local_addresses: list[dict] = field(default_factory=list)
    privacy_extensions: bool = False
    eui64_exposed: bool = False
    dual_stack: bool = False
    ipv6_dns_leak: bool | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class FirewallTestResult:
    """Result from testing a single port direction/protocol."""

    direction: str
    protocol: str
    port: int
    status: str
    target: str = ""
    latency_ms: float | None = None


@dataclass
class FirewallAuditReport:
    """Aggregated firewall audit results."""

    egress_results: list[FirewallTestResult] = field(default_factory=list)
    ingress_results: list[FirewallTestResult] = field(default_factory=list)
    blocked_egress_ports: list[int] = field(default_factory=list)
    open_ingress_ports: list[int] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ExportResult:
    """Result from an inventory export operation."""

    format: str
    path: str
    record_count: int
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Alert:
    """A notification-worthy event."""

    severity: str  # "info", "warning", "critical"
    category: str  # "new_device", "arp_spoof", "metric_threshold", etc.
    title: str
    message: str
    data: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


# --- Phase 3 shared types ---


@dataclass
class DeviceFingerprint:
    """Raw fingerprint signals collected for a device."""

    mac: str
    mac_is_randomized: bool = False
    oui_vendor: str | None = None
    hostname: str | None = None
    mdns_services: list[str] = field(default_factory=list)
    mdns_txt_records: dict[str, dict[str, str]] = field(default_factory=dict)
    upnp_friendly_name: str | None = None
    upnp_manufacturer: str | None = None
    upnp_model_name: str | None = None
    upnp_model_number: str | None = None
    upnp_device_type: str | None = None
    open_ports: list[int] = field(default_factory=list)
    banners: dict[int, str] = field(default_factory=dict)


@dataclass
class DeviceProfile:
    """Classified device identity with confidence."""

    ip: str
    mac: str
    device_type: str | None = None
    device_category: str | None = None
    os: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    friendly_name: str | None = None
    confidence: float = 0.0
    classification_method: str = ""
    fingerprint: DeviceFingerprint | None = None
    user_label: str | None = None
    last_profiled: datetime | None = None


# --- Phase 4 shared types ---


@dataclass
class TopologyNode:
    """A node in the network topology graph."""

    id: str
    label: str
    node_type: str  # "gateway", "switch", "host", "internet", "unknown"
    ip: str | None = None
    mac: str | None = None
    vendor: str | None = None
    interfaces: list[str] = field(default_factory=list)


@dataclass
class TopologyEdge:
    """A connection between two topology nodes."""

    source: str
    target: str
    edge_type: str  # "direct", "routed", "wireless"
    latency_ms: float | None = None
    label: str = ""


@dataclass
class NetworkTopology:
    """Complete network topology graph."""

    nodes: list[TopologyNode] = field(default_factory=list)
    edges: list[TopologyEdge] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class IoTDevice:
    """An identified IoT device with security assessment."""

    ip: str
    mac: str
    device_type: str  # "camera", "speaker", "thermostat", "plug", "hub", "unknown"
    manufacturer: str | None = None
    model: str | None = None
    risky_ports: list[int] = field(default_factory=list)
    risk_score: int = 0
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class IoTAuditReport:
    """Aggregated IoT security audit results."""

    devices: list[IoTDevice] = field(default_factory=list)
    high_risk_count: int = 0
    total_issues: int = 0
    recommendations: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PluginInfo:
    """Metadata about a loaded plugin."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    module_path: str = ""
    enabled: bool = True
    commands: list[str] = field(default_factory=list)
