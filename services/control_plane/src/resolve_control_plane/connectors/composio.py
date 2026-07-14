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
    data = body.get("data") or {}
    # the v3 execute API sometimes nests the real payload under response_data
    # (and uses snake_case); flatten it so callers see one consistent shape
    inner = data.get("response_data")
    if isinstance(inner, dict):
        data = {**data, **inner}
    return data


def _col_letter(n: int) -> str:
    """1-indexed column number → A1 letters (1→A, 27→AA)."""
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


# ── folder placement ────────────────────────────────────────────────────────


def _folder_id(name: str) -> str | None:
    """Resolve a Drive folder by name, creating it in root if it doesn't exist."""
    name = (name or "").strip()
    if not name:
        return None
    q = ("mimeType = 'application/vnd.google-apps.folder' and trashed = false "
         f"and name = '{name}'")
    data = execute("GOOGLEDRIVE_FIND_FILE", {"q": q, "fields": "files(id,name)", "pageSize": 3})
    files = data.get("files") or []
    if files:
        return files[0].get("id")
    made = execute("GOOGLEDRIVE_CREATE_FOLDER", {"name": name})
    return made.get("id") or made.get("fileId") or made.get("folderId")


def _place_in_folder(file_id: str, folder: str | None) -> None:
    """Move a freshly created file from root into the named folder (best-effort)."""
    if not folder or not file_id:
        return
    fid = _folder_id(folder)
    if fid:
        execute("GOOGLEDRIVE_MOVE_FILE",
                {"file_id": file_id, "add_parents": fid, "remove_parents": "root"})


# ── high-level helpers (return {url, id, ...}) ──────────────────────────────


def create_doc(title: str, markdown_text: str = "", folder: str | None = None) -> dict:
    data = execute(
        "GOOGLEDOCS_CREATE_DOCUMENT_MARKDOWN",
        {"title": title, "markdown_text": markdown_text or ""},
    )
    doc_id = data.get("documentId") or data.get("document_id")
    _place_in_folder(doc_id, folder)
    url = data.get("display_url") or (
        f"https://docs.google.com/document/d/{doc_id}/edit" if doc_id else ""
    )
    return {"url": url, "id": doc_id, "title": title, "folder": folder}


def create_sheet(title: str, rows: list[list] | None = None, folder: str | None = None) -> dict:
    data = execute("GOOGLESHEETS_CREATE_GOOGLE_SHEET1", {"title": title})
    sid = data.get("spreadsheetId") or data.get("spreadsheet_id")
    _place_in_folder(sid, folder)
    url = data.get("spreadsheetUrl") or data.get("display_url") or (
        f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid else ""
    )
    wrote = 0
    if rows and sid:
        _sheet_append(sid, "Sheet1", rows)
        wrote = len(rows)
    return {"url": url, "id": sid, "title": title, "rowsWritten": wrote, "folder": folder}


def _sheet_append(spreadsheet_id: str, sheet: str, rows: list[list]) -> None:
    # VALUES_UPDATE isn't available on this deployment; APPEND is. camelCase args.
    execute(
        "GOOGLESHEETS_SPREADSHEETS_VALUES_APPEND",
        {
            "spreadsheetId": spreadsheet_id,
            "range": sheet,
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
            "values": rows,
        },
    )


def create_slides(title: str, markdown_text: str, folder: str | None = None) -> dict:
    data = execute(
        "GOOGLESLIDES_CREATE_SLIDES_MARKDOWN",
        {"title": title, "markdown_text": markdown_text},
    )
    pid = data.get("presentation_id") or data.get("presentationId")
    _place_in_folder(pid, folder)
    url = f"https://docs.google.com/presentation/d/{pid}/edit" if pid else ""
    return {"url": url, "id": pid, "title": title, "slides": data.get("slide_count"),
            "folder": folder}


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


def edit_doc(document_id: str, text: str) -> dict:
    """Append text to the end of an existing Google Doc (plain text). This
    deployment requires insertion_index even for append; append_to_end wins, so
    the index is a placeholder."""
    execute(
        "GOOGLEDOCS_INSERT_TEXT_ACTION",
        {"document_id": document_id, "text_to_insert": text,
         "append_to_end": True, "insertion_index": 1},
    )
    return {"url": f"https://docs.google.com/document/d/{document_id}/edit", "id": document_id}


def edit_sheet(spreadsheet_id: str, rows: list[list], sheet: str | None = None) -> dict:
    """Append rows to a Google Sheet (defaults to the Sheet1 tab)."""
    _sheet_append(spreadsheet_id, sheet or "Sheet1", rows)
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


def delete_file(file_id: str) -> dict:
    """Permanently delete a Drive file (irreversible — approval-gated upstream)."""
    execute("GOOGLEDRIVE_GOOGLE_DRIVE_DELETE_FOLDER_OR_FILE_ACTION", {"fileId": file_id})
    return {"deleted": True, "id": file_id}
