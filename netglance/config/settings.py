"""Configuration loader for netglance."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "netglance" / "config.yaml"

DEFAULTS = {
    "network": {
        "subnet": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "interface": None,
    },
    "daemon": {
        "schedules": {
            "discover": "*/15 * * * *",
            "dns_check": "0 * * * *",
            "tls_verify": "0 */6 * * *",
            "baseline_diff": "0 2 * * *",
            "report": "0 7 * * *",
            "uptime_check": "*/5 * * * *",
        },
        "uptime_hosts": ["8.8.8.8", "1.1.1.1"],
    },
    "alerts": {
        "new_device": True,
        "missing_device": True,
        "arp_spoof": True,
        "tls_mismatch": True,
        "dns_hijack": True,
        "open_port_change": True,
    },
    "notifications": {
        "stdout": True,
    },
}


@dataclass
class NetworkConfig:
    subnet: str = "192.168.1.0/24"
    gateway: str = "192.168.1.1"
    interface: str | None = None


@dataclass
class NotificationConfig:
    stdout: bool = True
    webhook_url: str | None = None
    email_smtp_host: str | None = None
    email_smtp_port: int = 587
    email_from: str | None = None
    email_to: str | None = None
    email_username: str | None = None
    email_password: str | None = None
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str | None = None


@dataclass
class MetricsConfig:
    retention_days: int = 365
    prune_schedule: str = "0 3 * * *"


@dataclass
class DbConfig:
    warn_threshold_mb: int = 100


@dataclass
class Settings:
    network: NetworkConfig = field(default_factory=NetworkConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    db: DbConfig = field(default_factory=DbConfig)
    config_path: Path = DEFAULT_CONFIG_PATH

    @classmethod
    def load(cls, config_path: Path | str | None = None) -> "Settings":
        """Load settings from YAML config file, falling back to defaults."""
        path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        data = {}
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}

        net = data.get("network", {})
        network = NetworkConfig(
            subnet=net.get("subnet", DEFAULTS["network"]["subnet"]),
            gateway=net.get("gateway", DEFAULTS["network"]["gateway"]),
            interface=net.get("interface", DEFAULTS["network"]["interface"]),
        )

        notif = data.get("notifications", {})
        webhook = notif.get("webhook", {})
        email = notif.get("email", {})
        ntfy = notif.get("ntfy", {})
        notifications = NotificationConfig(
            stdout=notif.get("stdout", True),
            webhook_url=webhook.get("url") if webhook else None,
            email_smtp_host=email.get("smtp_host") if email else None,
            email_smtp_port=email.get("smtp_port", 587) if email else 587,
            email_from=email.get("from") if email else None,
            email_to=email.get("to") if email else None,
            email_username=email.get("username") if email else None,
            email_password=email.get("password") if email else None,
            ntfy_server=ntfy.get("server", "https://ntfy.sh") if ntfy else "https://ntfy.sh",
            ntfy_topic=ntfy.get("topic") if ntfy else None,
        )

        met = data.get("metrics", {})
        metrics = MetricsConfig(
            retention_days=met.get("retention_days", 365),
            prune_schedule=met.get("prune_schedule", "0 3 * * *"),
        )

        db_raw = data.get("db", {})
        db_config = DbConfig(
            warn_threshold_mb=db_raw.get("warn_threshold_mb", 100),
        )

        return cls(
            network=network,
            notifications=notifications,
            metrics=metrics,
            db=db_config,
            config_path=path,
        )
