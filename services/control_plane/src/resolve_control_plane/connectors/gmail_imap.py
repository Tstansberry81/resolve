"""Gmail — IMAP for reads, SMTP for sends, via GMAIL_ADDRESS +
GMAIL_APP_PASSWORD exactly like the vault1 bot."""

from __future__ import annotations

import datetime
import email
import imaplib
import os
import re
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


def inbox_recent(limit: int = 25, days: int | None = None) -> dict:
    """Latest INBOX messages (newest first) with STABLE IMAP UIDs, unread flag
    and a plain-text snippet — the raw material for triage and the daily
    inbox→calendar sweep. `days` narrows to messages since N days ago (IMAP
    SINCE). One batched FETCH for all messages, not a round-trip each."""
    lim = max(1, int(limit))  # 0/negative would slice the whole mailbox
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        m.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        m.select("INBOX", readonly=True)
        if days:
            since = (datetime.date.today() - datetime.timedelta(days=int(days))).strftime("%d-%b-%Y")
            _, data = m.uid("search", None, "SINCE", since)
        else:
            _, data = m.uid("search", None, "ALL")
        uids = (data[0] or b"").split()[-lim:]
        out = []
        by_uid: dict[bytes, tuple[bytes, bytes]] = {}
        if uids:
            _, md = m.uid("fetch", b",".join(uids), "(FLAGS BODY.PEEK[]<0.4096>)")
            for p in md or []:
                if not isinstance(p, tuple) or len(p) < 2:
                    continue
                head = p[0] or b""
                mu = re.search(rb"UID (\d+)", head)
                if mu:
                    by_uid[mu.group(1)] = (head, p[1] or b"")
        for u in reversed(uids):  # newest first
            head, raw = by_uid.get(u, (b"", b""))
            if not raw:
                continue
            try:
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
                    snippet = payload.decode("utf-8", "replace")[:300].strip()
                except Exception:
                    pass  # truncated MIME decodes best-effort; headers still land
                out.append({
                    "uid": u.decode(),
                    "from": _decode(msg.get("From", "")),
                    "subject": _decode(msg.get("Subject", "")),
                    "date": msg.get("Date", ""),
                    "unread": b"\\Seen" not in head,
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
