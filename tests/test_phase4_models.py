"""Tests for Phase 4 shared types in store/models.py."""

from datetime import datetime

from netglance.store.models import (
    IoTAuditReport,
    IoTDevice,
    NetworkTopology,
    PluginInfo,
    TopologyEdge,
    TopologyNode,
)


class TestTopologyNode:
    def test_basic_creation(self):
        node = TopologyNode(id="192.168.1.1", label="Gateway", node_type="gateway")
        assert node.id == "192.168.1.1"
        assert node.label == "Gateway"
        assert node.node_type == "gateway"
        assert node.ip is None
        assert node.mac is None
        assert node.vendor is None
        assert node.interfaces == []

    def test_full_creation(self):
        node = TopologyNode(
            id="192.168.1.42",
            label="NAS",
            node_type="host",
            ip="192.168.1.42",
            mac="aa:bb:cc:dd:ee:ff",
            vendor="Synology",
            interfaces=["en0"],
        )
        assert node.ip == "192.168.1.42"
        assert node.vendor == "Synology"
        assert node.interfaces == ["en0"]

    def test_node_types(self):
        for ntype in ("gateway", "switch", "host", "internet", "unknown"):
            node = TopologyNode(id="n1", label="test", node_type=ntype)
            assert node.node_type == ntype


class TestTopologyEdge:
    def test_basic_creation(self):
        edge = TopologyEdge(source="n1", target="n2", edge_type="direct")
        assert edge.source == "n1"
        assert edge.target == "n2"
        assert edge.edge_type == "direct"
        assert edge.latency_ms is None
        assert edge.label == ""

    def test_full_creation(self):
        edge = TopologyEdge(
            source="gw", target="host1", edge_type="wireless", latency_ms=2.5, label="WiFi"
        )
        assert edge.latency_ms == 2.5
        assert edge.label == "WiFi"


class TestNetworkTopology:
    def test_empty_topology(self):
        topo = NetworkTopology()
        assert topo.nodes == []
        assert topo.edges == []
        assert isinstance(topo.timestamp, datetime)

    def test_topology_with_nodes_and_edges(self):
        nodes = [
            TopologyNode(id="gw", label="Gateway", node_type="gateway"),
            TopologyNode(id="h1", label="Host 1", node_type="host"),
        ]
        edges = [TopologyEdge(source="gw", target="h1", edge_type="direct")]
        topo = NetworkTopology(nodes=nodes, edges=edges)
        assert len(topo.nodes) == 2
        assert len(topo.edges) == 1


class TestIoTDevice:
    def test_basic_creation(self):
        dev = IoTDevice(ip="192.168.1.50", mac="aa:bb:cc:dd:ee:ff", device_type="camera")
        assert dev.ip == "192.168.1.50"
        assert dev.device_type == "camera"
        assert dev.risk_score == 0
        assert dev.risky_ports == []
        assert dev.issues == []
        assert dev.recommendations == []

    def test_full_creation(self):
        dev = IoTDevice(
            ip="192.168.1.50",
            mac="aa:bb:cc:dd:ee:ff",
            device_type="camera",
            manufacturer="Ring",
            model="Doorbell Pro",
            risky_ports=[23, 80],
            risk_score=75,
            issues=["Telnet open", "HTTP without TLS"],
            recommendations=["Disable telnet", "Enable HTTPS"],
        )
        assert dev.manufacturer == "Ring"
        assert dev.risk_score == 75
        assert len(dev.issues) == 2

    def test_device_types(self):
        for dtype in ("camera", "speaker", "thermostat", "plug", "hub", "unknown"):
            dev = IoTDevice(ip="10.0.0.1", mac="ff:ff:ff:ff:ff:ff", device_type=dtype)
            assert dev.device_type == dtype


class TestIoTAuditReport:
    def test_empty_report(self):
        report = IoTAuditReport()
        assert report.devices == []
        assert report.high_risk_count == 0
        assert report.total_issues == 0
        assert isinstance(report.timestamp, datetime)

    def test_report_with_devices(self):
        devices = [
            IoTDevice(
                ip="192.168.1.50", mac="aa:bb:cc:00:00:01", device_type="camera", risk_score=80
            ),
            IoTDevice(
                ip="192.168.1.51", mac="aa:bb:cc:00:00:02", device_type="plug", risk_score=20
            ),
        ]
        report = IoTAuditReport(
            devices=devices,
            high_risk_count=1,
            total_issues=3,
            recommendations=["Segment IoT devices on a separate VLAN"],
        )
        assert len(report.devices) == 2
        assert report.high_risk_count == 1


class TestPluginInfo:
    def test_basic_creation(self):
        info = PluginInfo(name="my-plugin")
        assert info.name == "my-plugin"
        assert info.version == "0.0.0"
        assert info.description == ""
        assert info.enabled is True
        assert info.commands == []

    def test_full_creation(self):
        info = PluginInfo(
            name="router-check",
            version="1.2.0",
            description="Check router-specific health",
            author="user",
            module_path="/home/user/.config/netglance/plugins/router_check.py",
            enabled=True,
            commands=["router-status", "router-reboot"],
        )
        assert info.version == "1.2.0"
        assert len(info.commands) == 2

    def test_disabled_plugin(self):
        info = PluginInfo(name="disabled-plugin", enabled=False)
        assert info.enabled is False
