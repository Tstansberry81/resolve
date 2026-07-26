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
import re

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


def read_doc(document_id: str, limit: int = 40_000) -> dict:
    """Read a Google Doc back as plain text.

    Append-only editing was half a feature: RESOLVE could write a doc and never
    look at it again, so "fix the intro" or "what did we say about X" was
    impossible and it had to guess at content it wrote itself. Reading first is
    also what makes replace_in_doc safe — you match text you've actually seen."""
    data = execute("GOOGLEDOCS_GET_DOCUMENT_PLAINTEXT", {"document_id": document_id})
    text = ""
    for key in ("plain_text", "plaintext", "text", "content"):
        if isinstance(data.get(key), str):
            text = data[key]
            break
    truncated = len(text) > limit
    return {"id": document_id, "content": text[:limit], "truncated": truncated,
            "url": f"https://docs.google.com/document/d/{document_id}/edit"}


def replace_in_doc(document_id: str, find_text: str, replace_text: str,
                   match_case: bool = False) -> dict:
    """Find-and-replace inside an existing Google Doc — the actual edit primitive.

    Deleting is `replace_text=""`. Rewriting a section means replacing its old
    text with the new text. Everything append-only couldn't do routes through here.
    """
    if not find_text:
        raise ValueError("find_text can't be empty — that would match nothing.")
    data = execute("GOOGLEDOCS_REPLACE_ALL_TEXT", {
        "document_id": document_id, "find_text": find_text,
        "replace_text": replace_text, "match_case": match_case,
    })
    # The API reports how many matches it changed; 0 means the text wasn't found,
    # which must surface as a failure rather than a cheerful "done".
    changed = data.get("occurrences_changed", data.get("occurrencesChanged"))
    return {"id": document_id, "replaced": changed,
            "url": f"https://docs.google.com/document/d/{document_id}/edit"}


def read_sheet(spreadsheet_id: str, cell_range: str = "A1:Z200") -> dict:
    """Read cells out of a Google Sheet so the model can work off real values
    instead of assuming what's in the tracker it wrote last week."""
    data = execute("GOOGLESHEETS_VALUES_GET",
                   {"spreadsheet_id": spreadsheet_id, "range": cell_range})
    values = data.get("values") or []
    return {"id": spreadsheet_id, "range": cell_range, "rows": values[:200],
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"}


def update_sheet(spreadsheet_id: str, cell_range: str, rows: list[list]) -> dict:
    """Overwrite a specific range in a Google Sheet.

    Distinct from edit_sheet, which only appends to the bottom. Correcting one
    cell, updating a column of statuses, or fixing a bad row all need this.
    USER_ENTERED so a typed '=SUM(...)' becomes a real formula and '5' a number,
    matching what Trav would get typing it himself.
    """
    execute("GOOGLESHEETS_VALUES_UPDATE", {
        "spreadsheet_id": spreadsheet_id, "range": cell_range,
        "values": rows, "value_input_option": "USER_ENTERED",
    })
    return {"id": spreadsheet_id, "range": cell_range, "rowsWritten": len(rows),
            "url": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"}


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


def create_gmail_draft(to: str, subject: str, body: str,
                       thread_id: str | None = None) -> dict:
    """Put a draft in Trav's Gmail rather than only in the chat.

    send_email is approval-gated and fires immediately on approval. A draft is
    the softer half of that: RESOLVE writes it, Gmail holds it, and Trav edits
    and sends from his phone in the native app on his own time. That's what
    inbox triage actually wants — it drafts replies today, but they live in a
    chat message he has to copy out by hand.
    """
    args: dict = {"recipient_email": to, "body": body, "is_html": False}
    # Gmail keeps a draft in the same thread only when the subject is omitted;
    # setting one forks a new thread, which is never what a reply wants.
    if thread_id:
        args["thread_id"] = thread_id
    else:
        args["subject"] = subject
    data = execute("GMAIL_CREATE_EMAIL_DRAFT", args)
    draft_id = data.get("id") or data.get("draft_id") or ""
    return {"drafted": True, "draftId": draft_id, "to": to, "subject": subject,
            "url": "https://mail.google.com/mail/u/0/#drafts"}


# --- Spotify ---------------------------------------------------------------
# Trav has Premium (required — the playback endpoints 403 without it) and TWO
# connected Spotify accounts, so Composio can't pick one on its own. Pin the
# right one with COMPOSIO_ACCOUNTS='{"spotify":"spotify_acture-borago"}'; without
# it playback calls fail with an account-selection error, which _spotify_hint
# below turns into an instruction instead of a stack trace.

def _spotify(slug: str, args: dict | None = None) -> dict:
    try:
        return execute(slug, args or {})
    except RuntimeError as exc:
        raise RuntimeError(_spotify_hint(str(exc))) from exc


def _spotify_hint(msg: str) -> str:
    low = msg.lower()
    # Scope errors first: a 403 from a history call means the connection was
    # authorized without user-top-read / user-read-recently-played, and no amount
    # of retrying fixes it. Reconnecting in Composio does.
    if "scope" in low or "insufficient" in low:
        return (
            "Spotify won't share that without extra permissions. Reconnect Spotify in "
            "Composio and grant user-top-read, user-read-recently-played, and "
            "user-library-read — then ask me again.")
    if "no active device" in low or "404" in low:
        return ("No active Spotify device — open Spotify on your phone, Mac, or a "
                "speaker and play something for a second, then ask me again.")
    if "premium" in low or "403" in low:
        return ("Spotify refused that. Either it needs Premium, or the connection is "
                "missing a permission — for listening history, reconnect Spotify in "
                "Composio with user-top-read and user-read-recently-played.")
    if "account" in low and "select" in low:
        return ("Two Spotify accounts are connected, so I can't tell which to use — "
                "set COMPOSIO_ACCOUNTS with a \"spotify\" entry to pin one.")
    return msg


def _tracks(items: list, key: str | None = None) -> list[dict]:
    """Flatten Spotify track objects down to what a recommendation actually needs.

    Full track objects are enormous (available_markets alone is ~180 country
    codes per track). Sending 50 of them raw would cost thousands of tokens to
    say what four fields say.
    """
    out = []
    for it in items or []:
        track = (it.get(key) if key else it) or {}
        if not isinstance(track, dict) or not track.get("name"):
            continue
        out.append({
            "name": track.get("name"),
            "artist": ", ".join(a.get("name", "") for a in (track.get("artists") or [])
                                if isinstance(a, dict)),
            "uri": track.get("uri"),
        })
    return out


def spotify_recent(limit: int = 25) -> dict:
    data = _spotify("SPOTIFY_GET_RECENTLY_PLAYED_TRACKS",
                    {"limit": max(1, min(limit, 50))})
    return {"recentlyPlayed": _tracks(data.get("items") or [], key="track")}


def spotify_taste(time_range: str = "medium_term") -> dict:
    """A compact picture of what Trav actually listens to.

    Deliberately NOT Spotify's /recommendations endpoint: Spotify closed that to
    new apps in late 2024, along with audio-features and related-artists. So the
    recommending happens in the assistant instead, which is the better outcome
    anyway — it can weigh mood, occasion and season, explain WHY a track fits,
    and suggest things outside the algorithmic bubble Spotify would return.

    Genres come from top ARTISTS rather than tracks because Spotify only tags
    genre at the artist level; it's the strongest single signal for taste.
    """
    if time_range not in ("short_term", "medium_term", "long_term"):
        time_range = "medium_term"

    artists = _spotify("SPOTIFY_GET_USER_S_TOP_ARTISTS",
                       {"limit": 20, "time_range": time_range})
    tracks = _spotify("SPOTIFY_GET_USER_S_TOP_TRACKS",
                      {"limit": 25, "time_range": time_range})

    top_artists, genres = [], {}
    for a in (artists.get("items") or []):
        if not isinstance(a, dict) or not a.get("name"):
            continue
        top_artists.append(a["name"])
        for g in (a.get("genres") or []):
            genres[g] = genres.get(g, 0) + 1

    window = {"short_term": "the last ~4 weeks",
              "medium_term": "the last ~6 months",
              "long_term": "the last ~year"}[time_range]

    return {
        "window": window,
        "topArtists": top_artists,
        # Ranked by how many of his top artists carry the genre - a far better
        # summary of taste than any single artist name.
        "topGenres": [g for g, _ in sorted(genres.items(), key=lambda kv: -kv[1])][:12],
        "topTracks": _tracks(tracks.get("items") or []),
    }


def spotify_queue(uris: list[str]) -> dict:
    """Queue tracks behind whatever is playing. Recommending is only useful if he
    can act on it without a second round trip."""
    queued = []
    for uri in (uris or [])[:10]:
        if ":track:" not in str(uri):
            continue
        _spotify("SPOTIFY_ADD_ITEM_TO_PLAYBACK_QUEUE", {"uri": uri})
        queued.append(uri)
    return {"queued": len(queued), "uris": queued}


def spotify_search(query: str, kind: str = "track", limit: int = 5) -> dict:
    data = _spotify("SPOTIFY_SEARCH_FOR_ITEM",
                    {"q": query, "type": [kind], "limit": max(1, min(limit, 10))})
    items = (((data.get(kind + "s") or {}).get("items")) or [])[:limit]
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        artists = ", ".join(a.get("name", "") for a in (it.get("artists") or [])
                            if isinstance(a, dict))
        out.append({"name": it.get("name"), "artist": artists, "uri": it.get("uri")})
    return {"query": query, "kind": kind, "results": out}


def spotify_play(query: str = "", uri: str = "") -> dict:
    """Play something, or resume if given neither.

    A track URI goes in `uris`; an album/playlist/artist URI is a `context_uri`.
    Sending the wrong one is a silent no-op, so the shape is chosen from the URI.
    """
    target = uri
    label = uri
    if not target and query:
        found = spotify_search(query, "track", 1)["results"]
        if not found:
            return {"played": False, "note": f"Couldn't find anything on Spotify for “{query}”."}
        target, label = found[0]["uri"], f'{found[0]["name"]} — {found[0]["artist"]}'
    args: dict = {}
    if target:
        args["uris" if ":track:" in target else "context_uri"] = (
            [target] if ":track:" in target else target)
    _spotify("SPOTIFY_START_RESUME_PLAYBACK", args)
    return {"played": True, "what": label or "resumed"}


def spotify_control(action: str) -> dict:
    slug = {"pause": "SPOTIFY_PAUSE_PLAYBACK",
            "next": "SPOTIFY_SKIP_TO_NEXT",
            "previous": "SPOTIFY_SKIP_TO_PREVIOUS"}.get(action)
    if not slug:
        raise ValueError(f"unknown playback action: {action}")
    _spotify(slug)
    return {"ok": True, "action": action}


def spotify_now_playing() -> dict:
    data = _spotify("SPOTIFY_GET_PLAYBACK_STATE")
    item = data.get("item") or {}
    if not item:
        return {"playing": False, "note": "Nothing's playing right now."}
    artists = ", ".join(a.get("name", "") for a in (item.get("artists") or [])
                        if isinstance(a, dict))
    return {"playing": bool(data.get("is_playing")), "track": item.get("name"),
            "artist": artists, "album": (item.get("album") or {}).get("name")}


def _price_value(row: dict) -> float | None:
    """Numeric price for a shopping row — prefer extracted_price, else parse the
    display string ('$41.99', '£1,299.00') so rows without extracted_price still
    filter/sort correctly instead of being silently dropped."""
    v = row.get("extracted_price")
    if isinstance(v, (int, float)):
        return float(v)
    s = row.get("price")
    if isinstance(s, str):
        m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
        if m:
            try:
                return float(m.group().replace(",", ""))
            except ValueError:
                return None
    return None


def search_products(query: str, *, max_price: int | None = None,
                    min_price: int | None = None,
                    sort_by: int | None = None, limit: int = 8) -> dict:
    """Product/shopping search across retailers (Amazon/Best Buy/Target/Walmart…
    via Google Shopping) with live prices, ratings and links. Auth-less Composio
    search tool. Returns a normalized, ranked list."""
    args: dict = {"query": query}
    if max_price is not None:
        args["max_price"] = int(max_price)
    if min_price is not None:
        args["min_price"] = int(min_price)
    if sort_by is not None:
        args["sort_by"] = int(sort_by)
    data = execute("COMPOSIO_SEARCH_SHOPPING_SEARCH", args)
    results = (data.get("results") or {})
    rows = results.get("shopping_results") or data.get("shopping_results") or []
    products = [
        {
            "title": p.get("title"),
            "price": p.get("price"),
            "priceValue": _price_value(p),  # coerced once, reused for filter/sort
            "source": p.get("source"),
            "rating": p.get("rating"),
            "link": p.get("product_link") or p.get("link"),
        }
        for p in rows
    ]
    # The upstream SERP doesn't reliably honor price filters/sort — enforce here.
    # Keep rows whose price we couldn't parse rather than dropping them (avoids a
    # spurious "nothing found" when only some rows lack a numeric price).
    if max_price is not None:
        products = [p for p in products if p["priceValue"] is None or p["priceValue"] <= max_price]
    if min_price is not None:
        products = [p for p in products if p["priceValue"] is None or p["priceValue"] >= min_price]
    if sort_by in (1, 2):
        products.sort(key=lambda p: (p["priceValue"] is None, p["priceValue"] or 0.0),
                      reverse=(sort_by == 2))
    products = products[:limit]
    return {"query": query, "count": len(products), "products": products}
