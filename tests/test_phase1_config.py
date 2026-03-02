"""Tests for Phase 1 config extensions in settings.py."""

from netglance.config.settings import MetricsConfig, NotificationConfig, Settings


def test_notification_config_defaults():
    c = NotificationConfig()
    assert c.stdout is True
    assert c.webhook_url is None
    assert c.email_smtp_port == 587
    assert c.ntfy_server == "https://ntfy.sh"
    assert c.ntfy_topic is None


def test_metrics_config_defaults():
    c = MetricsConfig()
    assert c.retention_days == 365
    assert c.prune_schedule == "0 3 * * *"


def test_settings_includes_notifications(tmp_config):
    settings = Settings.load(tmp_config)
    assert isinstance(settings.notifications, NotificationConfig)
    assert settings.notifications.stdout is True


def test_settings_includes_metrics(tmp_config):
    settings = Settings.load(tmp_config)
    assert isinstance(settings.metrics, MetricsConfig)
    assert settings.metrics.retention_days == 365


def test_settings_load_notifications_from_yaml(tmp_config):
    tmp_config.write_text("""
notifications:
  stdout: false
  webhook:
    url: "https://hooks.slack.com/services/abc"
  email:
    smtp_host: "smtp.gmail.com"
    smtp_port: 465
    from: "netglance@example.com"
    to: "user@example.com"
    username: "user"
    password: "pass"
  ntfy:
    server: "https://ntfy.example.com"
    topic: "my-alerts"
""")
    settings = Settings.load(tmp_config)
    assert settings.notifications.stdout is False
    assert settings.notifications.webhook_url == "https://hooks.slack.com/services/abc"
    assert settings.notifications.email_smtp_host == "smtp.gmail.com"
    assert settings.notifications.email_smtp_port == 465
    assert settings.notifications.email_from == "netglance@example.com"
    assert settings.notifications.email_to == "user@example.com"
    assert settings.notifications.email_username == "user"
    assert settings.notifications.email_password == "pass"
    assert settings.notifications.ntfy_server == "https://ntfy.example.com"
    assert settings.notifications.ntfy_topic == "my-alerts"


def test_settings_load_metrics_from_yaml(tmp_config):
    tmp_config.write_text("""
metrics:
  retention_days: 90
  prune_schedule: "0 4 * * *"
""")
    settings = Settings.load(tmp_config)
    assert settings.metrics.retention_days == 90
    assert settings.metrics.prune_schedule == "0 4 * * *"


def test_settings_missing_notification_section(tmp_config):
    tmp_config.write_text("network:\n  subnet: 10.0.0.0/24\n")
    settings = Settings.load(tmp_config)
    assert settings.notifications.stdout is True
    assert settings.notifications.webhook_url is None


def test_settings_missing_metrics_section(tmp_config):
    tmp_config.write_text("network:\n  subnet: 10.0.0.0/24\n")
    settings = Settings.load(tmp_config)
    assert settings.metrics.retention_days == 365


def test_settings_partial_notification_config(tmp_config):
    tmp_config.write_text("""
notifications:
  stdout: true
  webhook:
    url: "https://hooks.example.com"
""")
    settings = Settings.load(tmp_config)
    assert settings.notifications.stdout is True
    assert settings.notifications.webhook_url == "https://hooks.example.com"
    assert settings.notifications.email_smtp_host is None
    assert settings.notifications.ntfy_topic is None


def test_settings_network_still_works(tmp_config):
    tmp_config.write_text("""
network:
  subnet: 10.0.0.0/16
  gateway: 10.0.0.1
notifications:
  stdout: false
""")
    settings = Settings.load(tmp_config)
    assert settings.network.subnet == "10.0.0.0/16"
    assert settings.notifications.stdout is False


def test_settings_empty_yaml(tmp_config):
    tmp_config.write_text("")
    settings = Settings.load(tmp_config)
    assert settings.notifications.stdout is True
    assert settings.metrics.retention_days == 365
    assert settings.network.subnet == "192.168.1.0/24"
