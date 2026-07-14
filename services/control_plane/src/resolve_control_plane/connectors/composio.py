"""Composio bridge — gives RESOLVE's agents Google Docs / Sheets / Slides,
which the control plane can't reach directly (its Google service account can't
create files in a personal Gmail Drive). Auth lives in Composio: the user OAuths
Google there once, and we execute tools by slug over Composio's v3 REST API.

Env:
  COMPOSIO_API_KEY  — required to enable (from the Composio dashboard, same
                      account where Google Docs/Sheets/Slides/Drive were connected)
  COMPOSIO_USER_ID  — the Composio user/entity holding those connections
                      (default "default")
  COMPOSIO_BASE_URL — override the API base (default v3 backend)
"""

from __future__ import annotations

import json
import os

import requests

BASE = (os.getenv("COMPOSIO_BASE_URL") or "https://backend.composio.dev/api/v3").rstrip("/")


def configured() -> bool:
    return bool(os.getenv("COMPOSIO_API_KEY"))


def _user_id() -> str:
    return os.getenv("COMPOSIO_USER_ID", "default")


def _accounts() -> dict:
    """Optional per-toolkit connected-account pins, e.g.
    COMPOSIO_ACCOUNTS='{"googledocs":"ca_...","googlesheets":"ca_..."}'. Used as
    a fallback when execution-by-user_id can't resolve the right connection."""
    try:
        return json.loads(os.getenv("COMPOSIO_ACCOUNTS", "") or "{}")
    except Exception:
        return {}


def execute(tool_slug: str, arguments: dict) -> dict:
    """Run one Composio tool and return its `data` payload (raises on failure)."""
    key = os.getenv("COMPOSIO_API_KEY", "")
    if not key:
        raise RuntimeError("Composio not configured (COMPOSIO_API_KEY unset)")
    body: dict = {"user_id": _user_id(), "arguments": arguments}
    toolkit = tool_slug.split("_", 1)[0].lower()  # GOOGLEDOCS_CREATE... -> googledocs
    acct = _accounts().get(toolkit)
    if acct:
        body["connected_account_id"] = acct
    r = requests.post(
        f"{BASE}/tools/execute/{tool_slug}",
        headers={"x-api-key": key, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Composio {tool_slug} HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    if not body.get("successful", body.get("success", False)):
        raise RuntimeError(f"Composio {tool_slug} failed: {str(body.get('error'))[:200]}")
    return body.get("data") or {}


def _col_letter(n: int) -> str:
    """1-indexed column number → A1 letters (1→A, 27→AA)."""
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


# ── high-level helpers (return {url, id, ...}) ──────────────────────────────


def create_doc(title: str, markdown_text: str = "") -> dict:
    data = execute(
        "GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN",
        {"title": title, "markdown_text": markdown_text or ""},
    )
    doc_id = data.get("documentId") or data.get("document_id")
    url = data.get("display_url") or (
        f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else ""
    )
    return {"url": url, "id": doc_id, "title": title}


def create_sheet(title: str, rows: list[list] | None = None) -> dict:
    data = execute("GOOGLESHEETS_CREATE_GOOGLE_SHEET1", {"title": title})
    sid = data.get("spreadsheetId") or data.get("spreadsheet_id")
    url = data.get("spreadsheetUrl") or data.get("display_url") or (
        f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid else ""
    )
    wrote = 0
    if rows and sid:
        ncols = max((len(r) for r in rows), default=0)
        rng = f"Sheet1!A1:{_col_letter(max(ncols, 1))}{len(rows)}"
        execute(
            "GOOGLESHEETS_VALUES_UPDATE",
            {
                "spreadsheet_id": sid,
                "range": rng,
                "value_input_option": "USER_ENTERED",
                "values": rows,
            },
        )
        wrote = len(rows)
    return {"url": url, "id": sid, "title": title, "rowsWritten": wrote}


def create_slides(title: str, markdown_text: str) -> dict:
    data = execute(
        "GOOGLESLIDES_CREATE_SLIDES_MARKDOWN",
        {"title": title, "markdown_text": markdown_text},
    )
    pid = data.get("presentation_id") or data.get("presentationId")
    url = f"https://docs.google.com/presentation/d/{pid}/edit" if pid else ""
    return {"url": url, "id": pid, "title": title, "slides": data.get("slide_count")}


# ── find / edit / delete ────────────────────────────────────────────────────


def find_file(query: str, limit: int = 8) -> dict:
    """Search the user's Drive. Plain text → name-contains; full Drive query syntax
    (name/mimeType/etc.) is passed through."""
    q = (query or "").strip()
    ops = ("=", "contains", " in ", ">", "<", "mimeType", "trashed")
    qexpr = q if any(o in q for o in ops) else f"name contains '{q}' and trashed = false"
    data = execute(
        "GOOGLEDRIVE_FIND_FILE",
        {"q": qexpr, "fields": "files(id,name,mimeType,webViewLink)", "pageSize": limit},
    )
    files = data.get("files") or []
    return {
        "files": [
            {"id": f.get("id"), "name": f.get("name"),
             "mimeType": f.get("mimeType"), "url": f.get("webViewLink")}
            for f in files
        ]
    }


def edit_doc(document_id: str, markdown_text: str) -> dict:
    """Append Markdown to an existing Google Doc."""
    data = execute(
        "GOOGLEDOCS_UPDATE_DOCUMENT_SECTION_MARKDOWN",
        {"document_id": document_id, "markdown_text": markdown_text},
    )
    did = data.get("documentId") or document_id
    url = data.get("display_url") or f"https://docs.google.com/document/d/{did}/edit"
    return {"url": url, "id": did}


def edit_sheet(spreadsheet_id: str, rows: list[list], cell_range: str | None = None) -> dict:
    """Write rows into a Google Sheet (defaults to Sheet1 from A1)."""
    if not cell_range:
        ncols = max((len(r) for r in rows), default=1)
        cell_range = f"Sheet1!A1:{_col_letter(max(ncols, 1))}{len(rows)}"
    execute(
        "GOOGLESHEETS_VALUES_UPDATE",
        {"spreadsheet_id": spreadsheet_id, "range": cell_range,
         "value_input_option": "USER_ENTERED", "values": rows},
    )
    return {"url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
            "id": spreadsheet_id, "rowsWritten": len(rows)}


def add_slides(presentation_id: str, markdown_text: str) -> dict:
    """Append slides (from Markdown, '---' between slides) to an existing deck."""
    execute(
        "GOOGLESLIDES_PRESENTATIONS_BATCH_UPDATE",
        {"presentationId": presentation_id, "markdown_text": markdown_text},
    )
    return {"url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
            "id": presentation_id}


def trash_file(file_id: str) -> dict:
    """Move a Drive file to trash (soft delete — recoverable)."""
    data = execute("GOOGLEDRIVE_TRASH_FILE", {"file_id": file_id})
    return {"trashed": True, "id": data.get("id", file_id),
            "name": data.get("name", ""), "url": data.get("display_url", "")}
