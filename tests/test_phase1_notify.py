"""Tests for the notification system in netglance/notify.py."""

from datetime import datetime

from netglance.notify import (
    EmailNotifier,
    NotificationManager,
    NtfyNotifier,
    StdoutNotifier,
    WebhookNotifier,
    build_notifiers_from_config,
)
from netglance.store.models import Alert


def _make_alert(**kwargs) -> Alert:
    defaults = dict(
        severity="warning",
        category="test",
        title="Test Alert",
        message="Something happened",
    )
    defaults.update(kwargs)
    return Alert(**defaults)


class TestStdoutNotifier:
    def test_send_returns_true(self):
        n = StdoutNotifier()
        assert n.send(_make_alert()) is True

    def test_send_all_severities(self):
        n = StdoutNotifier()
        for sev in ("info", "warning", "critical"):
            assert n.send(_make_alert(severity=sev)) is True


class TestWebhookNotifier:
    def test_send_calls_http_fn(self):
        calls = []

        def mock_post(url, payload):
            calls.append((url, payload))

        n = WebhookNotifier(url="https://hooks.example.com/test", _http_fn=mock_post)
        result = n.send(_make_alert())
        assert result is True
        assert len(calls) == 1
        assert calls[0][0] == "https://hooks.example.com/test"
        assert calls[0][1]["severity"] == "warning"
        assert calls[0][1]["title"] == "Test Alert"

    def test_send_returns_false_on_error(self):
        def failing_post(url, payload):
            raise ConnectionError("nope")

        n = WebhookNotifier(url="https://hooks.example.com/test", _http_fn=failing_post)
        assert n.send(_make_alert()) is False

    def test_payload_includes_timestamp(self):
        captured = {}

        def mock_post(url, payload):
            captured.update(payload)

        n = WebhookNotifier(url="https://x.com", _http_fn=mock_post)
        n.send(_make_alert())
        assert "timestamp" in captured


class TestEmailNotifier:
    def test_send_calls_smtp_fn(self):
        messages = []

        def mock_smtp(msg):
            messages.append(msg)

        n = EmailNotifier(
            smtp_host="smtp.test.com",
            smtp_port=587,
            from_addr="from@test.com",
            to_addr="to@test.com",
            _smtp_fn=mock_smtp,
        )
        result = n.send(_make_alert(severity="critical", title="DB down"))
        assert result is True
        assert len(messages) == 1
        assert "CRITICAL" in messages[0]["Subject"]
        assert "DB down" in messages[0]["Subject"]

    def test_send_returns_false_on_error(self):
        def failing_smtp(msg):
            raise ConnectionError("smtp failed")

        n = EmailNotifier(
            smtp_host="smtp.test.com",
            smtp_port=587,
            from_addr="from@test.com",
            to_addr="to@test.com",
            _smtp_fn=failing_smtp,
        )
        assert n.send(_make_alert()) is False

    def test_email_body_content(self):
        messages = []

        def mock_smtp(msg):
            messages.append(msg)

        n = EmailNotifier(
            smtp_host="smtp.test.com",
            smtp_port=587,
            from_addr="from@test.com",
            to_addr="to@test.com",
            _smtp_fn=mock_smtp,
        )
        n.send(_make_alert(category="arp_spoof", message="Gateway changed"))
        body = messages[0].get_content()
        assert "Gateway changed" in body
        assert "arp_spoof" in body


class TestNtfyNotifier:
    def test_send_calls_http_fn(self):
        calls = []

        def mock_post(url, body, headers):
            calls.append((url, body, headers))

        n = NtfyNotifier(server="https://ntfy.sh", topic="test-topic", _http_fn=mock_post)
        result = n.send(_make_alert())
        assert result is True
        assert len(calls) == 1
        assert calls[0][0] == "https://ntfy.sh/test-topic"
        assert calls[0][2]["Title"] == "Test Alert"

    def test_priority_mapping(self):
        calls = []

        def mock_post(url, body, headers):
            calls.append(headers)

        n = NtfyNotifier(topic="t", _http_fn=mock_post)

        n.send(_make_alert(severity="critical"))
        assert calls[-1]["Priority"] == "5"

        n.send(_make_alert(severity="warning"))
        assert calls[-1]["Priority"] == "3"

        n.send(_make_alert(severity="info"))
        assert calls[-1]["Priority"] == "2"

    def test_send_returns_false_on_error(self):
        def failing_post(url, body, headers):
            raise ConnectionError("nope")

        n = NtfyNotifier(topic="t", _http_fn=failing_post)
        assert n.send(_make_alert()) is False

    def test_server_trailing_slash_stripped(self):
        calls = []

        def mock_post(url, body, headers):
            calls.append(url)

        n = NtfyNotifier(server="https://ntfy.sh/", topic="t", _http_fn=mock_post)
        n.send(_make_alert())
        assert calls[0] == "https://ntfy.sh/t"


class TestNotificationManager:
    def test_empty_manager(self):
        mgr = NotificationManager()
        results = mgr.notify(_make_alert())
        assert results == []

    def test_fan_out(self):
        calls = []

        class MockNotifier:
            def send(self, alert):
                calls.append(alert)
                return True

        mgr = NotificationManager([MockNotifier(), MockNotifier()])
        results = mgr.notify(_make_alert())
        assert results == [True, True]
        assert len(calls) == 2

    def test_add_notifier(self):
        class MockNotifier:
            def send(self, alert):
                return True

        mgr = NotificationManager()
        mgr.add(MockNotifier())
        results = mgr.notify(_make_alert())
        assert results == [True]

    def test_mixed_results(self):
        class GoodNotifier:
            def send(self, alert):
                return True

        class BadNotifier:
            def send(self, alert):
                return False

        mgr = NotificationManager([GoodNotifier(), BadNotifier(), GoodNotifier()])
        results = mgr.notify(_make_alert())
        assert results == [True, False, True]


class TestBuildNotifiersFromConfig:
    def test_stdout_only(self):
        mgr = build_notifiers_from_config({"stdout": True})
        assert len(mgr._notifiers) == 1
        assert isinstance(mgr._notifiers[0], StdoutNotifier)

    def test_stdout_disabled(self):
        mgr = build_notifiers_from_config({"stdout": False})
        assert len(mgr._notifiers) == 0

    def test_webhook(self):
        mgr = build_notifiers_from_config({
            "stdout": False,
            "webhook": {"url": "https://hooks.example.com/test"},
        })
        assert len(mgr._notifiers) == 1
        assert isinstance(mgr._notifiers[0], WebhookNotifier)

    def test_email(self):
        mgr = build_notifiers_from_config({
            "stdout": False,
            "email": {
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "from": "a@b.com",
                "to": "c@d.com",
            },
        })
        assert len(mgr._notifiers) == 1
        assert isinstance(mgr._notifiers[0], EmailNotifier)

    def test_ntfy(self):
        mgr = build_notifiers_from_config({
            "stdout": False,
            "ntfy": {"server": "https://ntfy.sh", "topic": "test"},
        })
        assert len(mgr._notifiers) == 1
        assert isinstance(mgr._notifiers[0], NtfyNotifier)

    def test_all_backends(self):
        mgr = build_notifiers_from_config({
            "stdout": True,
            "webhook": {"url": "https://hooks.example.com"},
            "email": {
                "smtp_host": "smtp.test.com",
                "smtp_port": 587,
                "from": "a@b.com",
                "to": "c@d.com",
            },
            "ntfy": {"topic": "test"},
        })
        assert len(mgr._notifiers) == 4

    def test_empty_config(self):
        mgr = build_notifiers_from_config({})
        # stdout defaults to True
        assert len(mgr._notifiers) == 1

    def test_email_missing_required_fields(self):
        mgr = build_notifiers_from_config({
            "stdout": False,
            "email": {"smtp_host": "smtp.test.com"},  # missing from/to
        })
        assert len(mgr._notifiers) == 0

    def test_ntfy_missing_topic(self):
        mgr = build_notifiers_from_config({
            "stdout": False,
            "ntfy": {"server": "https://ntfy.sh"},  # missing topic
        })
        assert len(mgr._notifiers) == 0
