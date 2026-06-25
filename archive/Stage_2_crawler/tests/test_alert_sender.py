"""
Unit tests for grantglobe_crawler.alerts.alert_sender.

Tests:
Email:
  - send_email_alert returns False when HOST is missing
  - send_email_alert returns False when TO is missing
  - send_email_alert calls smtplib.SMTP with starttls() + sendmail()
  - send_email_alert returns False and does not raise on SMTP exception
  - ALERT_EMAIL_PASSWORD never appears in any log output (caplog)

Webhook:
  - send_webhook_alert returns False when URL is missing
  - send_webhook_alert uses "text" key for Slack URL
  - send_webhook_alert uses "content" key for Discord URL
  - send_webhook_alert returns False on non-2xx HTTP response
  - send_webhook_alert returns False and does not raise on network exception
"""

from __future__ import annotations

import json
import logging
from io import BytesIO
from unittest.mock import MagicMock, patch, call

import pytest

from grantglobe_crawler.alerts.alert_sender import send_email_alert, send_webhook_alert

_MESSAGE = "CRITICAL: 5 domains failed (25.0% of total)"
_PASSWORD = "super_secret_pw_99"

_FULL_EMAIL_SETTINGS = {
    "ALERT_EMAIL_HOST": "smtp.example.com",
    "ALERT_EMAIL_PORT": "587",
    "ALERT_EMAIL_USER": "alerts@example.com",
    "ALERT_EMAIL_PASSWORD": _PASSWORD,
    "ALERT_EMAIL_TO": "ops@example.com",
}

_FULL_WEBHOOK_SETTINGS = {
    "ALERT_WEBHOOK_URL": "https://hooks.slack.com/services/T00/B00/xyz",
}

_DISCORD_SETTINGS = {
    "ALERT_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
}


# ---------------------------------------------------------------------------
# Email tests
# ---------------------------------------------------------------------------


class TestSendEmailAlert:
    def test_returns_false_when_host_missing(self):
        settings = {**_FULL_EMAIL_SETTINGS, "ALERT_EMAIL_HOST": ""}
        assert send_email_alert(_MESSAGE, settings) is False

    def test_returns_false_when_to_missing(self):
        settings = {**_FULL_EMAIL_SETTINGS, "ALERT_EMAIL_TO": None}
        assert send_email_alert(_MESSAGE, settings) is False

    def test_returns_false_when_user_missing(self):
        settings = {**_FULL_EMAIL_SETTINGS, "ALERT_EMAIL_USER": ""}
        assert send_email_alert(_MESSAGE, settings) is False

    def test_returns_false_when_password_missing(self):
        settings = {**_FULL_EMAIL_SETTINGS, "ALERT_EMAIL_PASSWORD": ""}
        assert send_email_alert(_MESSAGE, settings) is False

    def test_calls_smtp_starttls_and_sendmail(self):
        """With full settings, SMTP.starttls() and SMTP.sendmail() are called."""
        mock_smtp_instance = MagicMock()
        mock_smtp_ctx = MagicMock()
        mock_smtp_ctx.__enter__ = MagicMock(return_value=mock_smtp_instance)
        mock_smtp_ctx.__exit__ = MagicMock(return_value=False)

        with patch(
            "grantglobe_crawler.alerts.alert_sender.smtplib.SMTP",
            return_value=mock_smtp_ctx,
        ) as mock_smtp_cls:
            result = send_email_alert(_MESSAGE, _FULL_EMAIL_SETTINGS)

        assert result is True
        mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with(
            "alerts@example.com", _PASSWORD
        )
        mock_smtp_instance.sendmail.assert_called_once()
        # Verify correct sender/recipient
        send_args = mock_smtp_instance.sendmail.call_args[0]
        assert send_args[0] == "alerts@example.com"
        assert send_args[1] == "ops@example.com"

    def test_returns_false_on_smtp_exception(self):
        """SMTP error is caught; False returned; no exception propagates."""
        with patch(
            "grantglobe_crawler.alerts.alert_sender.smtplib.SMTP",
            side_effect=Exception("Connection refused"),
        ):
            result = send_email_alert(_MESSAGE, _FULL_EMAIL_SETTINGS)
        assert result is False

    def test_password_never_in_logs(self, caplog):
        """ALERT_EMAIL_PASSWORD must not appear in any log record."""
        with patch(
            "grantglobe_crawler.alerts.alert_sender.smtplib.SMTP",
            side_effect=Exception("SMTP failure"),
        ):
            with caplog.at_level(logging.DEBUG, logger="grantglobe_crawler.alerts.alert_sender"):
                send_email_alert(_MESSAGE, _FULL_EMAIL_SETTINGS)

        full_log = "\n".join(r.getMessage() for r in caplog.records)
        assert _PASSWORD not in full_log, (
            f"Password '{_PASSWORD}' must not appear in any log output"
        )

    def test_debug_log_when_not_configured(self, caplog):
        """DEBUG message is emitted when email is not configured."""
        settings = {"ALERT_EMAIL_HOST": None, "ALERT_EMAIL_TO": None}
        with caplog.at_level(logging.DEBUG, logger="grantglobe_crawler.alerts.alert_sender"):
            send_email_alert(_MESSAGE, settings)

        assert any("not configured" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Webhook tests
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    """Minimal urllib response stub."""
    def __init__(self, status: int, body: bytes = b"ok"):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestSendWebhookAlert:
    def test_returns_false_when_url_missing(self):
        assert send_webhook_alert(_MESSAGE, {}) is False
        assert send_webhook_alert(_MESSAGE, {"ALERT_WEBHOOK_URL": ""}) is False
        assert send_webhook_alert(_MESSAGE, {"ALERT_WEBHOOK_URL": None}) is False

    def test_uses_text_key_for_slack(self):
        """Slack webhooks receive {"text": message}."""
        captured: list[bytes] = []

        def fake_urlopen(req, timeout):
            captured.append(req.data)
            return _FakeHTTPResponse(200)

        with patch(
            "grantglobe_crawler.alerts.alert_sender.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = send_webhook_alert(_MESSAGE, _FULL_WEBHOOK_SETTINGS)

        assert result is True
        payload = json.loads(captured[0])
        assert "text" in payload
        assert payload["text"] == _MESSAGE
        assert "content" not in payload

    def test_uses_content_key_for_discord(self):
        """Discord webhooks receive {"content": message}."""
        captured: list[bytes] = []

        def fake_urlopen(req, timeout):
            captured.append(req.data)
            return _FakeHTTPResponse(200)

        with patch(
            "grantglobe_crawler.alerts.alert_sender.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            result = send_webhook_alert(_MESSAGE, _DISCORD_SETTINGS)

        assert result is True
        payload = json.loads(captured[0])
        assert "content" in payload
        assert payload["content"] == _MESSAGE
        assert "text" not in payload

    def test_returns_false_on_non_2xx(self):
        """HTTP 400 response → False, WARNING logged."""
        with patch(
            "grantglobe_crawler.alerts.alert_sender.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(400),
        ):
            result = send_webhook_alert(_MESSAGE, _FULL_WEBHOOK_SETTINGS)
        assert result is False

    def test_returns_true_on_204(self):
        """HTTP 204 (Discord empty success) is treated as success."""
        with patch(
            "grantglobe_crawler.alerts.alert_sender.urllib.request.urlopen",
            return_value=_FakeHTTPResponse(204),
        ):
            result = send_webhook_alert(_MESSAGE, _FULL_WEBHOOK_SETTINGS)
        assert result is True

    def test_returns_false_on_network_exception(self):
        """Network error is caught; False returned; no exception propagates."""
        with patch(
            "grantglobe_crawler.alerts.alert_sender.urllib.request.urlopen",
            side_effect=OSError("Network unreachable"),
        ):
            result = send_webhook_alert(_MESSAGE, _FULL_WEBHOOK_SETTINGS)
        assert result is False

    def test_debug_log_when_not_configured(self, caplog):
        """DEBUG message emitted when webhook URL is absent."""
        with caplog.at_level(logging.DEBUG, logger="grantglobe_crawler.alerts.alert_sender"):
            send_webhook_alert(_MESSAGE, {})
        assert any("not configured" in r.getMessage() for r in caplog.records)

    def test_content_type_header_is_json(self):
        """Request Content-Type must be application/json."""
        captured_headers: list[dict] = []

        def fake_urlopen(req, timeout):
            captured_headers.append(dict(req.headers))
            return _FakeHTTPResponse(200)

        with patch(
            "grantglobe_crawler.alerts.alert_sender.urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):
            send_webhook_alert(_MESSAGE, _FULL_WEBHOOK_SETTINGS)

        assert captured_headers, "urlopen was not called"
        # Headers are title-cased by urllib internally
        headers = {k.lower(): v for k, v in captured_headers[0].items()}
        assert "content-type" in headers
        assert "application/json" in headers["content-type"]
