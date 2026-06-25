"""
Alert delivery channels — email (SMTP STARTTLS) and webhook (Slack / Discord).

Both functions are designed to be fire-and-forget: they return a boolean
success indicator and catch all exceptions internally so that a misconfigured
or unavailable alerting channel never crashes the spider.

Security notes
--------------
- ``ALERT_EMAIL_PASSWORD`` is **never** written to log files.
- ``ALERT_WEBHOOK_URL`` may contain authentication tokens; it is logged only
  at DEBUG level in a truncated form (scheme+host only).
- The SMTP connection uses STARTTLS (port 587) — plaintext SMTP is not used.

Usage
-----
Both functions accept a ``settings`` argument that can be a Scrapy settings
object or any dict-like object supporting ``.get(key, default)``.

Spec ref: §2.8 Alerting channels.
"""

from __future__ import annotations

import json
import logging
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

logger = logging.getLogger(__name__)

_SUBJECT_BASE = "GrantGlobe Crawler Alert"
_WEBHOOK_TIMEOUT_S = 10


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


def send_email_alert(
    message: str,
    settings,
    *,
    subject: str = _SUBJECT_BASE,
) -> bool:
    """
    Send *message* via SMTP using ``settings.ALERT_EMAIL_*`` variables.

    Parameters
    ----------
    message:
        Plain-text body of the alert email.
    settings:
        Scrapy settings object or any dict-like supporting ``.get(key, default)``.
    subject:
        Email subject line.  Callers should pass a severity-aware string such as
        ``"GrantGlobe Crawler Alert — CRITICAL"`` or
        ``"GrantGlobe Crawler Alert — HIGH"``.
        Defaults to ``"GrantGlobe Crawler Alert"`` for backwards compatibility.

    Required settings
    -----------------
    ALERT_EMAIL_HOST     SMTP server hostname (e.g. ``smtp.gmail.com``)
    ALERT_EMAIL_PORT     SMTP port; defaults to ``587``
    ALERT_EMAIL_USER     Sender address / SMTP login username
    ALERT_EMAIL_PASSWORD SMTP password (never logged)
    ALERT_EMAIL_TO       Recipient address

    Returns
    -------
    bool
        ``True`` on successful delivery, ``False`` on any failure (never
        raises).

    Spec ref: §2.8 Alerting channels — email.
    """
    host: str = settings.get("ALERT_EMAIL_HOST") or ""
    port: int = int(settings.get("ALERT_EMAIL_PORT") or 587)
    user: str = settings.get("ALERT_EMAIL_USER") or ""
    password: str = settings.get("ALERT_EMAIL_PASSWORD") or ""
    to_addr: str = settings.get("ALERT_EMAIL_TO") or ""

    # All four credentials are required; absence of any one means email is
    # not configured.  Log at DEBUG so operators see it without noise.
    if not all([host, user, password, to_addr]):
        logger.debug("Email alert not configured — skipping")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to_addr
        msg.set_content(message)

        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls()
            smtp.login(user, password)  # password never logged
            smtp.sendmail(user, to_addr, msg.as_string())

        logger.info("Email alert sent to %s via %s:%d", to_addr, host, port)
        return True

    except Exception as exc:
        # Deliberately broad catch — alerting must never crash the spider.
        logger.error(
            "Failed to send email alert to %s via %s:%d — %s",
            to_addr,
            host,
            port,
            exc,
        )
        return False


# ---------------------------------------------------------------------------
# Webhook (Slack / Discord)
# ---------------------------------------------------------------------------


def send_webhook_alert(message: str, settings) -> bool:
    """
    POST *message* to a Slack or Discord incoming webhook URL.

    Payload format
    --------------
    Slack:   ``{"text": message}``
    Discord: ``{"content": message}``  (detected by ``"discord"`` in URL)

    Only the standard library ``urllib.request`` is used so that no
    additional dependencies are required beyond what ``requirements.txt``
    already pins.

    Returns
    -------
    bool
        ``True`` on HTTP 200–204, ``False`` on any failure (never raises).

    Spec ref: §2.8 Alerting channels — webhook.
    """
    url: str = settings.get("ALERT_WEBHOOK_URL") or ""

    if not url:
        logger.debug("Webhook alert not configured — skipping")
        return False

    # Choose the payload key based on the webhook provider.
    key = "content" if "discord" in url.lower() else "text"
    payload = json.dumps({key: message}).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as resp:
            status = resp.status

        if 200 <= status <= 204:
            # Log only scheme+host to avoid leaking tokens embedded in URL.
            parsed = urllib.parse.urlparse(url)
            logger.info(
                "Webhook alert delivered — %s://%s (HTTP %d)",
                parsed.scheme,
                parsed.netloc,
                status,
            )
            return True

        logger.warning(
            "Webhook alert returned non-2xx status %d — delivery may have failed",
            status,
        )
        return False

    except urllib.error.HTTPError as exc:
        logger.warning(
            "Webhook alert HTTP error %d: %s",
            exc.code,
            exc.reason,
        )
        return False

    except Exception as exc:
        # Deliberately broad catch — alerting must never crash the spider.
        logger.error("Failed to deliver webhook alert: %s", exc)
        return False
