"""Tool definitions shared by the Sonnet assistant and the Opus executor:
policy mapping, Anthropic tool schemas, and Sonnet's system prompt."""

from __future__ import annotations

from typing import Any

# tool name → (policy action name, connector node for the constellation edge)
TOOL_POLICY = {
    "get_calendar": ("calendar.read", "calendar"),
    "create_calendar_event": ("calendar.create", "calendar"),
    "get_tasks": ("notion.tasks.read", "notion"),
    "create_task": ("notion.page.create", "notion"),
    "get_unread_email": ("email.read", "gmail"),
    "send_email": ("email.send", "gmail"),
    "vault_log": ("vault.append", "vault"),
    "vault_read": ("vault.read", "vault"),
    "plan_project": ("plan.project", "sol"),
    "delete_task": ("notion.page.archive", "notion"),
    "delete_calendar_event": ("calendar.delete", "calendar"),
    "ask_local": ("local.ask", "web"),
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_calendar",
        "description": "List upcoming Google Calendar events. Call this before answering any question about the user's schedule.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "How many days ahead (default 7)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a Google Calendar event. Times are ISO 8601 with offset, e.g. 2026-07-12T15:00:00-04:00.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_iso": {"type": "string"},
                "end_iso": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title", "start_iso", "end_iso"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_tasks",
        "description": "List open tasks from the user's Notion Tasks database.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "create_task",
        "description": "Create a task in the user's Notion Tasks database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD, optional"},
                "priority": {"type": "string", "enum": ["Low", "Medium", "High"]},
                "notes": {"type": "string"},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_unread_email",
        "description": "Count unread Gmail messages and list the latest senders/subjects.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "send_email",
        "description": "Send an email from the user's Gmail. ALWAYS requires the user's explicit approval before it actually sends — calling this queues it for approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "vault_log",
        "description": "Append a summary entry to the user's Obsidian vault (second brain) via GitHub. Use for durable summaries worth remembering.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short entry title"},
                "lines": {"type": "array", "items": {"type": "string"}, "description": "Bullet lines"},
            },
            "required": ["title", "lines"],
            "additionalProperties": False,
        },
    },
    {
        "name": "vault_read",
        "description": "Read from the user's Obsidian vault (second brain). Give a path to read a file, or a query to search file names. Use this to pull context about the user's life and projects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Exact file path, e.g. wiki/log.md"},
                "query": {"type": "string", "description": "Substring to search file names for"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_task",
        "description": "Archive (delete) a Notion task by page id. Get the id from get_tasks first. Always requires the user's approval banner.",
        "input_schema": {
            "type": "object",
            "properties": {"page_id": {"type": "string"}, "title": {"type": "string", "description": "Task title, for the approval preview"}},
            "required": ["page_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete a Google Calendar event by id. Get the id from get_calendar first. Always requires the user's approval banner.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}, "title": {"type": "string", "description": "Event title, for the approval preview"}},
            "required": ["event_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_local",
        "description": "Ask Trav's local AI model (Qwen on his own hardware) a question. Use for brainstorming, drafts, or private reasoning when he asks for the local model.",
        "input_schema": {
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
            "required": ["prompt"],
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_project",
        "description": "Hand a complex multi-step goal to Sol (planner) and the Opus executor. Call ONCE with a clear objective; steps run in the background and stream into the event feed.",
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string", "description": "Full objective with all needed details"}},
            "required": ["objective"],
            "additionalProperties": False,
        },
    },
]

SYSTEM = """You are Sonnet, the RESOLVE assistant — the front door for Trav's personal
agent platform. You handle menial work directly with your tools: calendar reads/writes,
Notion tasks, email checks, single email sends (approval-gated), and vault log entries.

Rules:
- Answer questions about schedule/tasks/email by CALLING TOOLS first. Never invent data.
- Use ISO 8601 datetimes with the America/New_York offset for calendar writes.
- send_email only queues for the user's approval; tell him it's waiting on his approval banner.
- Deletes (delete_task, delete_calendar_event) also queue for approval — look up the id first,
  then call the delete tool and tell him it's waiting on his banner.
- Be brief and warm. One short paragraph max in your final reply.
- For complex multi-step requests (several distinct actions, research projects, bulk work),
  call plan_project ONCE with the full objective. Sol plans it, the Opus executor runs the
  steps in the background. Tell the user the plan is queued and list the steps."""


