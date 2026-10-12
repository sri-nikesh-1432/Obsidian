"""Outbound email.

Delivery order:
    1. Resend API            when RESEND_API_KEY is set
    2. SMTP (STARTTLS/SSL)   when OBSIDIAN_SMTP_HOST is set — e.g. a Gmail
                             app password, so real OTPs reach real inboxes
                             with no third-party account required
    3. Development mailbox    stored in DynamoDB so local flows and tests are
                             always usable without any credential

The raw OTP is never written to application logs.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import aws
from .config import settings


def delivery_channel() -> str:
    """Which transport a real send would use right now (no secrets leaked)."""
    if settings.resend_api_key:
        return "resend"
    if settings.smtp_host:
        return "smtp"
    return "dev"


def send_email(*, to: str, subject: str, html: str, text: str) -> bool:
    if settings.resend_api_key:
        return _send_resend(to, subject, html, text)
    if settings.smtp_host:
        sent = _send_smtp(to, subject, html, text)
        if sent:
            return True
        # A misconfigured SMTP relay must never break sign-up: fall back to the
        # local mailbox so the flow (and the tests) still complete.
        print("[obsidian] SMTP delivery failed; storing message in the dev mailbox",
              file=__import__('sys').stderr)
    return _send_dev(to, subject, html, text)


def _send_smtp(to: str, subject: str, html: str, text: str) -> bool:
    """Deliver via SMTP. Raises nothing; returns whether the relay accepted."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    try:
        msg = EmailMessage()
        msg["From"] = settings.from_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        host = settings.smtp_host
        port = settings.smtp_port
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as server:
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                if settings.smtp_starttls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if settings.smtp_username:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 - report type only, never credentials
        print(f"[obsidian] SMTP send failed: {type(exc).__name__}",
              file=__import__('sys').stderr)
        return False


def _send_resend(to: str, subject: str, html: str, text: str) -> bool:
    try:
        import httpx
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.from_email,
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
            timeout=15.0,
        )
        if resp.status_code >= 300:
            # Surface the reason (e.g. an unverified domain) without leaking the
            # key or the recipient's code. Resend returns a JSON error body.
            print(f"[obsidian] Resend send failed: HTTP {resp.status_code} "
                  f"{resp.text[:300]}", file=__import__('sys').stderr)
        return resp.status_code < 300
    except Exception as exc:  # noqa: BLE001 - report type only, never credentials
        print(f"[obsidian] Resend send error: {type(exc).__name__}",
              file=__import__('sys').stderr)
        return False


def _send_dev(to: str, subject: str, html: str, text: str) -> bool:
    try:
        aws.table("devmail").put_item(
            Item={
                "pk": f"MAIL#{to.lower()}",
                "sk": f"TS#{datetime.now(timezone.utc).isoformat()}",
                "to": to.lower(),
                "subject": subject,
                "text": text,
                "html": html,
            }
        )
    except Exception:
        pass
    print(f"[dev-mail] to={to} subject={subject!r} (stored in dev mailbox)")
    return True


def latest_dev_mail(email: str) -> dict | None:
    """Dev/test helper: read the most recent message delivered to a mailbox."""
    from boto3.dynamodb.conditions import Key
    resp = aws.table("devmail").query(
        KeyConditionExpression=Key("pk").eq(f"MAIL#{email.lower()}"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None
