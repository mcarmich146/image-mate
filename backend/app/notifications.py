from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr
import html
import smtplib
import ssl
from typing import Any


def _recipients(watch: dict[str, Any], settings: Any) -> list[str]:
    raw = watch.get("email_to") or getattr(settings, "alert_email_to", []) or []
    if isinstance(raw, str):
        values = raw.split(",")
    else:
        values = list(raw)
    return [str(value).strip() for value in values if str(value).strip()]


def send_archive_watch_email(watch: dict[str, Any], items: list[dict[str, Any]], settings: Any) -> dict[str, Any]:
    """Send a notification using environment-configured SMTP settings.

    The caller supplies Image-Mate proxy links, not provider-signed URLs. A
    missing mail configuration is reported as a status so local development
    can use the watch workflow without unexpectedly attempting delivery.
    """
    recipients = _recipients(watch, settings)
    host = str(getattr(settings, "smtp_host", "") or "").strip()
    if not recipients or not host:
        return {"status": "not_configured", "recipients": recipients, "count": len(items)}

    sender = str(getattr(settings, "smtp_from", "") or getattr(settings, "smtp_username", "") or "").strip()
    if not sender:
        raise RuntimeError("IMAGE_MATE_SMTP_FROM or IMAGE_MATE_SMTP_USERNAME is required for email delivery")

    name = str(watch.get("name") or "Archive watch")
    count = len(items)
    subject = f"[Image-Mate] New imagery: {name} ({count})"
    rows = []
    text_rows = []
    for item in items:
        item_id = str(item.get("item_id") or item.get("id") or "unknown")
        captured = str(item.get("datetime") or "Unknown capture time")
        collection = str(item.get("collection") or watch.get("collection_id") or "")
        preview_url = str(item.get("preview_url") or item.get("image_url") or "")
        rows.append(
            "<li><strong>{}</strong> &mdash; {}<br><span>{}</span><br><a href=\"{}\">Open image in Image-Mate</a></li>".format(
                html.escape(item_id), html.escape(captured), html.escape(collection), html.escape(preview_url, quote=True)
            )
        )
        text_rows.append(f"- {item_id} | {captured} | {collection}\n  {preview_url}")

    text_body = (
        f"Image-Mate archive watch: {name}\n\n"
        f"{count} new archive item(s) were found in the subscribed polygon.\n\n"
        + "\n".join(text_rows)
        + "\n\nThis message contains Image-Mate proxy links; provider credentials and signed asset URLs are not included."
    )
    html_body = (
        "<html><body>"
        f"<h2>New imagery for {html.escape(name)}</h2>"
        f"<p>{count} new archive item(s) were found in the subscribed polygon.</p>"
        f"<ol>{''.join(rows)}</ol>"
        "<p>Links use the Image-Mate preview proxy; provider credentials and signed asset URLs are not included.</p>"
        "</body></html>"
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(("Image-Mate", sender))
    message["To"] = ", ".join(recipients)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    port = int(getattr(settings, "smtp_port", 587) or 587)
    timeout = max(5, int(getattr(settings, "smtp_timeout_seconds", 30) or 30))
    username = str(getattr(settings, "smtp_username", "") or "").strip()
    password = str(getattr(settings, "smtp_password", "") or "")
    use_ssl = bool(getattr(settings, "smtp_use_ssl", False))
    use_tls = bool(getattr(settings, "smtp_use_tls", True)) and not use_ssl

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context()) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)

    return {"status": "sent", "recipients": recipients, "count": count}
