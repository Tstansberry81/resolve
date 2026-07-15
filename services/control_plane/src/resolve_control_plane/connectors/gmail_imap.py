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


def inbox_recent(limit: int = 25) -> dict:
    """Latest INBOX messages (newest first) with STABLE IMAP UIDs, unread flag
    and a short plain-text snippet — the raw material for a triage pass. The
    uid values feed archive_messages directly."""
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        m.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        m.select("INBOX", readonly=True)
        _, data = m.uid("search", None, "ALL")
        uids = (data[0] or b"").split()[-int(limit):]
        out = []
        for u in reversed(uids):  # newest first
            try:
                _, md = m.uid("fetch", u, "(FLAGS BODY.PEEK[]<0.2048>)")
                raw = b"".join(p[1] for p in md if isinstance(p, tuple))
                flags = b" ".join(p[0] for p in md if isinstance(p, tuple))
                msg = email.message_from_bytes(raw)
                snippet = ""
                try:
                    part = msg
                    if msg.is_multipart():
                        for cand in msg.walk():
                            if cand.get_content_type() == "text/plain":
                                part = cand
                                break
                    payload = part.get_payload(decode=True) or b""
                    snippet = payload.decode("utf-8", "replace")[:200].strip()
                except Exception:
                    pass  # truncated MIME decodes best-effort; headers still land
                out.append({
                    "uid": u.decode(),
                    "from": _decode(msg.get("From", "")),
                    "subject": _decode(msg.get("Subject", "")),
                    "date": msg.get("Date", ""),
                    "unread": b"\\Seen" not in flags,
                    "snippet": snippet,
                })
            except Exception:
                continue  # one bad message never kills the listing
        return {"count": len(out), "messages": out}
    finally:
        try:
            m.logout()
        except Exception:
            pass


def archive_messages(uids: list[str]) -> dict:
    """Archive INBOX messages by UID. Gmail semantics: the message keeps living
    in All Mail (reversible — it just loses the Inbox label)."""
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        m.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        m.select("INBOX")
        ok, failed = 0, []
        for uid in uids:
            u = str(uid).strip().encode()
            try:
                m.uid("copy", u, "[Gmail]/All Mail")  # survive even aggressive expunge settings
                m.uid("store", u, "+FLAGS", "(\\Deleted)")
                ok += 1
            except Exception:
                failed.append(str(uid))
        m.expunge()
        res: dict = {"archived": ok, "requested": len(uids)}
        if failed:
            res["failed_uids"] = failed
        return res
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
