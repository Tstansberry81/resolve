"""Notion — the whole workspace, not one database.

The tasks helpers at the bottom are the original vault1-bot shape and stay for
the get_tasks/create_task/delete_task tools. Everything above them is generic:
search the workspace, read any database's schema, query it, and create or edit
pages anywhere the integration can see.

Reachability is a Notion-side setting, not a code one. The token only sees
pages explicitly shared with the integration, so `search()` returning a short
list means pages need sharing in Notion — see docs/NOTION_ACCESS.md.
"""

from __future__ import annotations

import os
from typing import Any

import requests

NOTION_TASKS_DB = "021c8bf0-0593-48da-8f5f-dfbb2df69a4b"
API = "https://api.notion.com/v1"
TIMEOUT = 20


def configured() -> bool:
    return bool(os.getenv("NOTION_TOKEN"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('NOTION_TOKEN', '')}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def probe(timeout: int = 6) -> str | None:
    """Verify the token works AND can see something. None = live, else why not.

    Notion has a second failure mode no credential check catches: a perfectly
    valid token that's been shared zero pages, which authenticates fine and then
    finds nothing. That reads as "your workspace is empty" unless it's called out
    here.
    """
    if not configured():
        return "NOTION_TOKEN not set"
    try:
        r = requests.get(f"{API}/users/me", headers=_headers(), timeout=timeout)
    except Exception as exc:
        return f"cannot reach api.notion.com ({type(exc).__name__})"
    if r.status_code == 401:
        return "NOTION_TOKEN rejected (401) — revoked or wrong secret"
    if r.status_code != 200:
        return f"Notion returned {r.status_code} on /users/me"
    try:
        found = requests.post(f"{API}/search", headers=_headers(),
                              json={"page_size": 1}, timeout=timeout)
        if found.status_code == 200 and not (found.json().get("results") or []):
            return ("token valid but NO pages are shared with the integration — "
                    "connect a parent page in Notion (see docs/NOTION_ACCESS.md)")
    except Exception:
        pass  # the auth check above already passed; don't fail the probe on this
    return None


def _req(method: str, path: str, **kw) -> dict:
    r = requests.request(method, f"{API}{path}", headers=_headers(), timeout=TIMEOUT, **kw)
    if r.status_code >= 400:
        # Notion's message says which of "not shared" / "bad property" / "bad id"
        # it was; surfacing it verbatim is what lets the model self-correct.
        try:
            detail = r.json().get("message", r.text)
        except ValueError:
            detail = r.text
        raise RuntimeError(f"Notion {r.status_code}: {detail}")
    return r.json()


# --- reading -----------------------------------------------------------------

def _plain(rich: list | None) -> str:
    return "".join(x.get("plain_text", "") for x in (rich or []))


def _title_of(obj: dict) -> str:
    """Title of a page or database, whichever shape it arrives in."""
    if obj.get("object") == "database":
        return _plain(obj.get("title")) or "(untitled)"
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title")) or "(untitled)"
    return "(untitled)"


def _flatten(props: dict) -> dict:
    """Notion's nested property payloads -> plain values the model can read."""
    out: dict[str, Any] = {}
    for name, p in props.items():
        kind = p.get("type")
        if kind == "title":
            out[name] = _plain(p.get("title"))
        elif kind == "rich_text":
            out[name] = _plain(p.get("rich_text"))
        elif kind in ("select", "status"):
            out[name] = (p.get(kind) or {}).get("name")
        elif kind == "multi_select":
            out[name] = [o.get("name") for o in p.get("multi_select") or []]
        elif kind == "date":
            d = p.get("date") or {}
            out[name] = d.get("start") if not d.get("end") else f"{d.get('start')} → {d.get('end')}"
        elif kind in ("number", "checkbox", "url", "email", "phone_number"):
            out[name] = p.get(kind)
        elif kind == "people":
            out[name] = [u.get("name") for u in p.get("people") or []]
        elif kind == "relation":
            out[name] = [r.get("id") for r in p.get("relation") or []]
        elif kind == "formula":
            f = p.get("formula") or {}
            out[name] = f.get(f.get("type"))
        elif kind == "rollup":
            r = p.get("rollup") or {}
            out[name] = r.get(r.get("type"))
        elif kind == "files":
            out[name] = [f.get("name") for f in p.get("files") or []]
        elif kind in ("created_time", "last_edited_time"):
            out[name] = p.get(kind)
    return out


def search(query: str = "", kind: str | None = None, limit: int = 25) -> list[dict]:
    """Find pages and databases by title. kind: 'page' | 'database' | None."""
    body: dict[str, Any] = {"page_size": max(1, min(limit, 100))}
    if query:
        body["query"] = query
    if kind in ("page", "database"):
        body["filter"] = {"property": "object", "value": kind}
    res = _req("POST", "/search", json=body).get("results", [])
    return [
        {
            "id": o["id"],
            "object": o.get("object"),
            "title": _title_of(o),
            "url": o.get("url"),
            "parent": (o.get("parent") or {}).get("type"),
            "last_edited": o.get("last_edited_time"),
        }
        for o in res
    ]


def list_databases(limit: int = 50) -> list[dict]:
    return search("", kind="database", limit=limit)


def get_database(database_id: str) -> dict:
    """Schema of a database: every property, its type, and its allowed options.

    Call this before create_page/update_page against an unfamiliar database —
    it's what makes the difference between a typed write and a guess.
    """
    db = _req("GET", f"/databases/{database_id}")
    props = {}
    for name, p in (db.get("properties") or {}).items():
        kind = p.get("type")
        entry: dict[str, Any] = {"type": kind}
        if kind in ("select", "status", "multi_select"):
            entry["options"] = [o.get("name") for o in (p.get(kind) or {}).get("options", [])]
        props[name] = entry
    return {
        "id": db.get("id"),
        "title": _title_of(db),
        "url": db.get("url"),
        "properties": props,
    }


def query_database(
    database_id: str,
    filter: dict | None = None,
    sorts: list | None = None,
    limit: int = 25,
) -> list[dict]:
    body: dict[str, Any] = {"page_size": max(1, min(limit, 100))}
    if filter:
        body["filter"] = filter
    if sorts:
        body["sorts"] = sorts
    res = _req("POST", f"/databases/{database_id}/query", json=body).get("results", [])
    return [
        {
            "id": p["id"],
            "url": p.get("url"),
            "title": _title_of(p),
            **_flatten(p.get("properties") or {}),
        }
        for p in res
    ]


def _block_text(b: dict) -> str:
    kind = b.get("type", "")
    body = b.get(kind) or {}
    text = _plain(body.get("rich_text"))
    prefix = {
        "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
        "bulleted_list_item": "- ", "numbered_list_item": "1. ",
        "to_do": "[x] " if body.get("checked") else "[ ] ",
        "quote": "> ", "code": "```\n",
    }.get(kind, "")
    if kind == "code":
        return f"```\n{text}\n```"
    return f"{prefix}{text}" if text else ""


def get_page(page_id: str, include_content: bool = True) -> dict:
    page = _req("GET", f"/pages/{page_id}")
    out = {
        "id": page.get("id"),
        "url": page.get("url"),
        "title": _title_of(page),
        "properties": _flatten(page.get("properties") or {}),
    }
    if include_content:
        blocks = _req("GET", f"/blocks/{page_id}/children?page_size=100").get("results", [])
        lines = [t for t in (_block_text(b) for b in blocks) if t]
        out["content"] = "\n".join(lines)
    return out


# --- writing -----------------------------------------------------------------

def _to_prop(kind: str, value: Any) -> dict | None:
    """Coerce a plain value into the payload its property type expects.

    Callers pass {"Name": "Calc I", "Days": ["Mon","Wed"]} and the schema
    decides the shape, so nothing upstream has to know Notion's JSON.
    """
    if value is None:
        return None
    if kind == "title":
        return {"title": [{"text": {"content": str(value)[:2000]}}]}
    if kind == "rich_text":
        return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
    if kind in ("select", "status"):
        return {kind: {"name": str(value)}}
    if kind == "multi_select":
        vals = value if isinstance(value, (list, tuple)) else [value]
        return {"multi_select": [{"name": str(v)} for v in vals]}
    if kind == "date":
        if isinstance(value, dict):
            return {"date": value}
        return {"date": {"start": str(value)}}
    if kind == "number":
        return {"number": float(value)}
    if kind == "checkbox":
        return {"checkbox": bool(value)}
    if kind in ("url", "email", "phone_number"):
        return {kind: str(value)}
    if kind == "relation":
        vals = value if isinstance(value, (list, tuple)) else [value]
        return {"relation": [{"id": str(v)} for v in vals]}
    # formula/rollup/created_time and friends are computed — not writable
    return None


def _build_props(schema: dict, values: dict) -> tuple[dict, list[str]]:
    """Map caller values onto a database schema. Returns (payload, skipped)."""
    props: dict[str, Any] = {}
    skipped: list[str] = []
    lookup = {k.lower(): k for k in schema}
    for name, value in values.items():
        real = lookup.get(str(name).lower())
        if real is None:
            skipped.append(f"{name} (no such property)")
            continue
        payload = _to_prop(schema[real]["type"], value)
        if payload is None:
            skipped.append(f"{name} ({schema[real]['type']} is not writable)")
            continue
        props[real] = payload
    return props, skipped


def _content_blocks(content: str) -> list[dict]:
    """Light markdown -> Notion blocks. Headings, bullets, to-dos, paragraphs."""
    blocks = []
    for raw in (content or "").split("\n"):
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("### "):
            kind, text = "heading_3", line[4:]
        elif line.startswith("## "):
            kind, text = "heading_2", line[3:]
        elif line.startswith("# "):
            kind, text = "heading_1", line[2:]
        elif line.startswith(("- [ ] ", "- [x] ")):
            blocks.append({
                "object": "block", "type": "to_do",
                "to_do": {
                    "rich_text": [{"text": {"content": line[6:]}}],
                    "checked": line[3] == "x",
                },
            })
            continue
        elif line.startswith(("- ", "* ")):
            kind, text = "bulleted_list_item", line[2:]
        elif line.startswith("> "):
            kind, text = "quote", line[2:]
        else:
            kind, text = "paragraph", line
        blocks.append({
            "object": "block", "type": kind,
            kind: {"rich_text": [{"text": {"content": text[:2000]}}]},
        })
    return blocks[:100]


def create_page(
    parent_id: str,
    properties: dict | None = None,
    title: str | None = None,
    content: str = "",
    parent_is_page: bool = False,
) -> dict:
    """Create a page in any database (or under any page).

    In a database, `properties` are matched against the live schema and typed
    automatically; `title` fills whichever property is the title column.
    """
    properties = dict(properties or {})
    skipped: list[str] = []

    if parent_is_page:
        parent = {"page_id": parent_id}
        props = {"title": {"title": [{"text": {"content": title or "Untitled"}}]}}
    else:
        schema = get_database(parent_id)["properties"]
        if title is not None:
            title_prop = next((n for n, p in schema.items() if p["type"] == "title"), None)
            if title_prop:
                properties.setdefault(title_prop, title)
        props, skipped = _build_props(schema, properties)
        parent = {"database_id": parent_id}

    body: dict[str, Any] = {"parent": parent, "properties": props}
    if content:
        body["children"] = _content_blocks(content)
    page = _req("POST", "/pages", json=body)
    out = {"id": page["id"], "url": page.get("url"), "title": _title_of(page)}
    if skipped:
        out["skipped"] = skipped
    return out


def update_page(page_id: str, properties: dict) -> dict:
    """Edit properties of an existing page, typed against its parent database."""
    page = _req("GET", f"/pages/{page_id}")
    parent = page.get("parent") or {}
    if parent.get("type") == "database_id":
        schema = get_database(parent["database_id"])["properties"]
        props, skipped = _build_props(schema, properties)
    else:  # a standalone page only has a title
        props = {"title": {"title": [{"text": {"content": str(next(iter(properties.values())))}}]}}
        skipped = []
    updated = _req("PATCH", f"/pages/{page_id}", json={"properties": props})
    out = {"id": updated["id"], "url": updated.get("url"), "title": _title_of(updated),
           "updated": list(props.keys())}
    if skipped:
        out["skipped"] = skipped
    return out


def append_to_page(page_id: str, content: str) -> dict:
    blocks = _content_blocks(content)
    _req("PATCH", f"/blocks/{page_id}/children", json={"children": blocks})
    return {"page_id": page_id, "blocks_added": len(blocks)}


def create_database(parent_page_id: str, title: str, properties: dict) -> dict:
    """Create a database under a page. `properties` is {name: type}, e.g.
    {"Name": "title", "Day": "select", "Time": "rich_text"}."""
    schema: dict[str, Any] = {}
    for name, kind in properties.items():
        if kind in ("select", "status", "multi_select"):
            schema[name] = {kind: {"options": []}}
        else:
            schema[name] = {kind: {}}
    if not any("title" in v for v in schema.values()):
        schema["Name"] = {"title": {}}
    db = _req("POST", "/databases", json={
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": schema,
    })
    return {"id": db["id"], "url": db.get("url"), "title": title,
            "properties": list(schema.keys())}


def archive_page(page_id: str) -> None:
    _req("PATCH", f"/pages/{page_id}", json={"archived": True})


# --- tasks (the original Tasks-database helpers) -----------------------------

def list_open_tasks(limit: int = 20) -> list[dict]:
    flt = {
        "and": [
            {"property": "Status", "select": {"does_not_equal": "Done"}},
            {"property": "Status", "select": {"does_not_equal": "Cancelled"}},
        ]
    }
    res = _req("POST", f"/databases/{NOTION_TASKS_DB}/query",
               json={"filter": flt, "page_size": limit}).get("results", [])
    out = []
    for p in res:
        props = p.get("properties", {})
        due = (props.get("Due Date", {}).get("date") or {}).get("start")
        out.append({
            "id": p["id"],
            "title": _title_of(p),
            "status": (props.get("Status", {}).get("select") or {}).get("name"),
            "priority": (props.get("Priority", {}).get("select") or {}).get("name"),
            "due": due,
        })
    return out


def create_task(
    title: str,
    due_date: str | None = None,
    priority: str = "Medium",
    category: str = "Personal",
    notes: str = "",
) -> dict:
    props: dict = {
        "Task": {"title": [{"text": {"content": title}}]},
        "Status": {"select": {"name": "Inbox"}},
        "Priority": {"select": {"name": priority}},
        "Category": {"select": {"name": category}},
        "Source": {"select": {"name": "Agent"}},
        "Notes": {"rich_text": [{"text": {"content": notes}}]},
    }
    if due_date:
        props["Due Date"] = {"date": {"start": due_date}}
    page = _req("POST", "/pages",
                json={"parent": {"database_id": NOTION_TASKS_DB}, "properties": props})
    return {"id": page["id"], "url": page.get("url"), "title": title}
