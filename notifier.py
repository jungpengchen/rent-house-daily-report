"""
Notification dispatch module.

Supports:
  - Telegram Bot API  (primary)
  - Email via SMTP    (secondary)
  - LINE Notify       (optional)

Credentials are read from config first, then from environment variables.
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

logger = logging.getLogger(__name__)

_TELEGRAM_MAX_LEN = 4096


def _get(cfg_section: dict, key: str, env_var: str) -> str:
    """Return value from config dict, falling back to environment variable."""
    return cfg_section.get(key) or os.environ.get(env_var, "")


# ── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(message: str, cfg: dict) -> bool:
    tg = cfg.get("notification", {}).get("telegram", {})
    if not tg.get("enabled", False):
        return False

    token = _get(tg, "bot_token", "TELEGRAM_BOT_TOKEN")
    chat_id = _get(tg, "chat_id", "TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("Telegram: bot_token or chat_id not configured")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Telegram has a 4096-char limit; split if needed
    chunks = [message[i:i + _TELEGRAM_MAX_LEN] for i in range(0, len(message), _TELEGRAM_MAX_LEN)]
    success = True

    for chunk in chunks:
        try:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("Telegram: message sent (%d chars)", len(chunk))
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            success = False

    return success


# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(message: str, cfg: dict) -> bool:
    em = cfg.get("notification", {}).get("email", {})
    if not em.get("enabled", False):
        return False

    smtp_host = _get(em, "smtp_host", "EMAIL_SMTP_HOST") or "smtp.gmail.com"
    smtp_port = int(em.get("smtp_port") or os.environ.get("EMAIL_SMTP_PORT", 587))
    username = _get(em, "username", "EMAIL_USERNAME")
    password = _get(em, "password", "EMAIL_PASSWORD")
    to_addr = _get(em, "to", "EMAIL_TO")

    if not all([username, password, to_addr]):
        logger.warning("Email: missing credentials or recipient")
        return False

    from datetime import date
    subject = f"台北租屋日報 {date.today().isoformat()}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = to_addr
    msg.attach(MIMEText(message, "plain", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(username, password)
            server.sendmail(username, to_addr, msg.as_string())
        logger.info("Email sent to %s", to_addr)
        return True
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False


# ── LINE Notify ───────────────────────────────────────────────────────────────

def send_line_notify(message: str, cfg: dict) -> bool:
    ln = cfg.get("notification", {}).get("line_notify", {})
    if not ln.get("enabled", False):
        return False

    token = _get(ln, "token", "LINE_NOTIFY_TOKEN")
    if not token:
        logger.warning("LINE Notify: token not configured")
        return False

    # LINE Notify has a 1000-char limit per message
    chunks = [message[i:i + 1000] for i in range(0, len(message), 1000)]
    success = True

    for chunk in chunks:
        try:
            resp = requests.post(
                "https://notify-api.line.me/api/notify",
                headers={"Authorization": f"Bearer {token}"},
                data={"message": chunk},
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("LINE Notify: message sent (%d chars)", len(chunk))
        except Exception as exc:
            logger.error("LINE Notify send failed: %s", exc)
            success = False

    return success


# ── Dispatch ──────────────────────────────────────────────────────────────────

def dispatch(message: str, cfg: dict) -> int:
    """
    Send via all enabled channels.
    Returns the number of channels that succeeded.
    """
    results = [
        send_telegram(message, cfg),
        send_email(message, cfg),
        send_line_notify(message, cfg),
    ]
    return sum(1 for r in results if r)
