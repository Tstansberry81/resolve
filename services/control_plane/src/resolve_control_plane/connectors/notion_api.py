"""Notion tasks — same database and property schema as the vault1 bot."""

from __future__ import annotations

import os

import requests

NOTION_TASKS_DB = "021c8bf0-0593-48da-8f5f-dfbb2df69a4b"


def configured() -> bool:
    return bool(os.getenv("NOTION_TOKEN"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('NOTION_TOKEN', '')}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def list_open_tasks(limit: int = 20) -> list[dict]:
    flt = {
        "and": [
            {"property": "Status", "select": {"does_not_equal": "Done"}},
            {"property": "Status", "select": {"does_not_equal": "Cancelled"}},
        ]
    }
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_TASKS_DB}/query",
        headers=_headers(),
        json={"filter": flt, "page_size": limit},
        timeout=15,
    )
    r.raise_for_status()
    out = []
    for p in r.json().get("results", []):
        props = p.get("properties", {})
        title = props.get("Task", {}).get("title", [])
        due = (props.get("Due Date", {}).get("date") or {}).get("start")
        out.append(
            {
                "id": p["id"],
                "title": title[0]["plain_text"] if title else "(untitled)",
                "status": (props.get("Status", {}).get("select") or {}).get("name"),
                "priority": (props.get("Priority", {}).get("select") or {}).get("name"),
                "due": due,
            }
        )
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
    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_headers(),
        json={"parent": {"database_id": NOTION_TASKS_DB}, "properties": props},
        timeout=15,
    )
    r.raise_for_status()
    page = r.json()
    return {"id": page["id"], "url": page.get("url"), "title": title}


def archive_page(page_id: str) -> None:
    requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=_headers(),
        json={"archived": True},
        timeout=15,
    ).raise_for_status()
