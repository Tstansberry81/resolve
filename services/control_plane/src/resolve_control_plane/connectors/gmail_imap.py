"""Gmail — IMAP for reads, SMTP for sends, via GMAIL_ADDRESS +
GMAIL_APP_PASSWORD exactly like the vault1 bot."""

from __future__ import annotations

import email
import imaplib
import os
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText


def configured() -> bool:
    return bool(os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD"))


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    out = ""
    for text, enc in parts:
        out += text.decode(enc or "utf-8", "replace") if isinstance(text, bytes) else text
    return out


def unread_summary(limit: int = 5) -> dict:
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        m.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        m.select("INBOX", readonly=True)
        _, data = m.search(None, "UNSEEN")
        ids = data[0].split()
        subjects = []
        for uid in ids[-limit:]:
            _, msg_data = m.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
            raw = b"".join(p[1] for p in msg_data if isinstance(p, tuple))
            msg = email.message_from_bytes(raw)
            subjects.append(
                {"from": _decode(msg.get("From", "")), "subject": _decode(msg.get("Subject", ""))}
            )
        return {"unread": len(ids), "latest": subjects}
    finally:
        try:
            m.logout()
        except Exception:
            pass


def send_email(to: str, subject: str, body: str) -> dict:
    addr = os.environ["GMAIL_ADDRESS"]
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as s:
        s.login(addr, os.environ["GMAIL_APP_PASSWORD"])
        s.sendmail(addr, [to], msg.as_string())
    return {"sent": True, "to": to, "subject": subject}
