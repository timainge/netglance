"""Notification system for netglance alerts."""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from typing import Protocol

from rich.console import Console
from rich.panel import Panel

from netglance.store.models import Alert


class Notifier(Protocol):
    """Protocol for notification backends."""

    def send(self, alert: Alert) -> bool: ...


class StdoutNotifier:
    """Print alerts to terminal via rich."""

    def __init__(self) -> None:
        self._console = Console()

    def send(self, alert: Alert) -> bool:
        color = {"critical": "red", "warning": "yellow", "info": "blue"}.get(
            alert.severity, "white"
        )
        self._console.print(
            Panel(
                f"[bold]{alert.title}[/bold]\n{alert.message}",
                title=f"[{color}]{alert.severity.upper()}[/{color}] [{alert.category}]",
                border_style=color,
            )
        )
        return True


class WebhookNotifier:
    """POST JSON to a webhook URL (Slack, Discord, Teams, generic)."""

    def __init__(self, url: str, *, _http_fn=None) -> None:
        self.url = url
        self._http_fn = _http_fn

    def send(self, alert: Alert) -> bool:
        payload = {
            "severity": alert.severity,
            "category": alert.category,
            "title": alert.title,
            "message": alert.message,
            "data": alert.data,
            "timestamp": alert.timestamp.isoformat(),
        }
        try:
            http_fn = self._http_fn or self._default_post
            http_fn(self.url, payload)
            return True
        except Exception:
            return False

    @staticmethod
    def _default_post(url: str, payload: dict) -> None:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)


class EmailNotifier:
    """Send via SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_addr: str,
        to_addr: str,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        *,
        _smtp_fn=None,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self._smtp_fn = _smtp_fn

    def send(self, alert: Alert) -> bool:
        msg = EmailMessage()
        msg["Subject"] = f"[netglance {alert.severity.upper()}] {alert.title}"
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr
        msg.set_content(f"{alert.title}\n\n{alert.message}\n\nCategory: {alert.category}\nSeverity: {alert.severity}\nTime: {alert.timestamp.isoformat()}")

        try:
            if self._smtp_fn:
                self._smtp_fn(msg)
                return True

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(msg)
            return True
        except Exception:
            return False


class NtfyNotifier:
    """Push to ntfy.sh or self-hosted ntfy server."""

    def __init__(
        self,
        server: str = "https://ntfy.sh",
        topic: str = "netglance",
        *,
        _http_fn=None,
    ) -> None:
        self.server = server.rstrip("/")
        self.topic = topic
        self._http_fn = _http_fn

    def send(self, alert: Alert) -> bool:
        url = f"{self.server}/{self.topic}"
        priority_map = {"critical": "5", "warning": "3", "info": "2"}
        headers = {
            "Title": alert.title,
            "Priority": priority_map.get(alert.severity, "3"),
            "Tags": alert.category,
        }
        try:
            http_fn = self._http_fn or self._default_post
            http_fn(url, alert.message, headers)
            return True
        except Exception:
            return False

    @staticmethod
    def _default_post(url: str, body: str, headers: dict) -> None:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=body.encode(),
            headers=headers,
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)


class NotificationManager:
    """Fan-out to multiple notifiers."""

    def __init__(self, notifiers: list[Notifier] | None = None) -> None:
        self._notifiers: list[Notifier] = list(notifiers) if notifiers else []

    def add(self, notifier: Notifier) -> None:
        self._notifiers.append(notifier)

    def notify(self, alert: Alert) -> list[bool]:
        return [n.send(alert) for n in self._notifiers]


def build_notifiers_from_config(settings: dict) -> NotificationManager:
    """Factory: read the notifications section of config and return configured manager."""
    manager = NotificationManager()

    if settings.get("stdout", True):
        manager.add(StdoutNotifier())

    webhook = settings.get("webhook")
    if webhook and webhook.get("url"):
        manager.add(WebhookNotifier(url=webhook["url"]))

    email = settings.get("email")
    if email and email.get("smtp_host") and email.get("from") and email.get("to"):
        manager.add(
            EmailNotifier(
                smtp_host=email["smtp_host"],
                smtp_port=email.get("smtp_port", 587),
                from_addr=email["from"],
                to_addr=email["to"],
                username=email.get("username"),
                password=email.get("password"),
                use_tls=email.get("use_tls", True),
            )
        )

    ntfy = settings.get("ntfy")
    if ntfy and ntfy.get("topic"):
        manager.add(
            NtfyNotifier(
                server=ntfy.get("server", "https://ntfy.sh"),
                topic=ntfy["topic"],
            )
        )

    return manager
