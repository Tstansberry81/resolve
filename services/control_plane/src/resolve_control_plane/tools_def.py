"""Tool definitions shared by the Sonnet assistant and the Opus executor:
policy mapping, Anthropic tool schemas, and Sonnet's system prompt."""

from __future__ import annotations

from typing import Any

# tool name → (policy action name, connector node for the constellation edge)
TOOL_POLICY = {
    "get_calendar": ("calendar.read", "calendar"),
    "create_calendar_event": ("calendar.create", "calendar"),
    "get_tasks": ("notion.tasks.read", "notion"),
    "get_school_day": ("notion.read", "notion"),
    "create_task": ("notion.page.create", "notion"),
    "get_unread_email": ("email.read", "gmail"),
    "get_inbox_recent": ("email.read", "gmail"),
    "archive_emails": ("email.archive", "gmail"),
    "send_email": ("email.send", "gmail"),
    "vault_log": ("vault.append", "vault"),
    "save_to_vault": ("vault.write", "vault"),
    "vault_read": ("vault.read", "vault"),
    "plan_project": ("plan.project", "planner"),
    "delete_task": ("notion.page.archive", "notion"),
    "notion_search": ("notion.read", "notion"),
    "notion_schema": ("notion.read", "notion"),
    "notion_query": ("notion.read", "notion"),
    "notion_read_page": ("notion.read", "notion"),
    "notion_create_page": ("notion.page.create", "notion"),
    "notion_update_page": ("notion.page.update", "notion"),
    "notion_append": ("notion.page.update", "notion"),
    "notion_create_database": ("notion.database.create", "notion"),
    "delete_calendar_event": ("calendar.delete", "calendar"),
    "ask_local": ("local.ask", "web"),
    "get_finance": ("finance.read", "finance"),
    "get_health": ("health.read", "health"),
    "get_recent_activity": ("activity.read", "vault"),
    "get_audit_log": ("activity.read", "vault"),
    "run_on_laptop": ("laptop.dispatch", "local"),
    "open_folder": ("laptop.display", "local"),
    "reveal_in_finder": ("laptop.display", "local"),
    "open_file": ("laptop.display", "local"),
    "open_app": ("laptop.display", "local"),
    "open_website": ("laptop.display", "local"),
    "restart_worker": ("laptop.display", "local"),
    "create_google_doc": ("gdrive.create", "google"),
    "create_google_sheet": ("gdrive.create", "google"),
    "create_google_slides": ("gdrive.create", "google"),
    "find_google_file": ("gdrive.read", "google"),
    "search_products": ("web.search", "google"),
    "edit_google_doc": ("gdrive.edit", "google"),
    "edit_google_sheet": ("gdrive.edit", "google"),
    "add_google_slides": ("gdrive.edit", "google"),
    "delete_google_file": ("gdrive.delete", "google"),
    "read_google_doc": ("gdrive.read", "google"),
    "replace_in_google_doc": ("gdrive.edit", "google"),
    "read_google_sheet": ("gdrive.read", "google"),
    "update_google_sheet": ("gdrive.edit", "google"),
    "draft_email": ("email.draft", "gmail"),
    "get_weather": ("world.read", "web"),
    "get_travel_time": ("world.read", "web"),
    "get_canvas": ("canvas.read", "canvas"),
    "spotify_play": ("music.control", "spotify"),
    "spotify_control": ("music.control", "spotify"),
    "spotify_search": ("music.read", "spotify"),
    "spotify_now_playing": ("music.read", "spotify"),
    "get_music_taste": ("music.read", "spotify"),
    "spotify_recent": ("music.read", "spotify"),
    "spotify_queue": ("music.control", "spotify"),
    "vault_recall": ("vault.read", "vault"),
    "github_issues": ("github.read", "github"),
    "github_pull_requests": ("github.read", "github"),
    "github_ci": ("github.read", "github"),
    "create_github_issue": ("github.issue.create", "github"),
    "code_task": ("code.write", "coder"),
    "review_code": ("code.review", "coder"),
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_calendar",
        "description": (
            "List upcoming Google Calendar events. Call this before answering any "
            "question about the user's schedule. Each row has start, end, id and "
            "series_id. Recurring events are expanded to ONE ROW PER OCCURRENCE, so a "
            "weekly class appears many times — `id` is that single meeting and "
            "`series_id` is the whole series. Ask for the `days` you actually need: a "
            "class starting three weeks out needs days>=21 or it simply won't be in "
            "the results. If the last row is titled [TRUNCATED], the window held more "
            "than came back and anything later is missing — narrow `days` and re-ask.\n"
            "When looking for a SPECIFIC thing, pass `query` instead of scanning the "
            "list yourself — and search the plain word, not a course code. A class "
            "titled 'Philosophy 1730' does not match a search for 'PHIL'. If a query "
            "returns nothing, say the query returned nothing; do not upgrade that into "
            "'it isn't on the calendar' without an unfiltered look."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "How many days ahead (default 7, max 60)"},
                "query": {
                    "type": "string",
                    "description": (
                        "Optional free-text filter over title, description and location. "
                        "Use the everyday word ('philosophy', 'econ') rather than a code."
                    ),
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "create_calendar_event",
        "description": (
            "Create a Google Calendar event. Times are ISO 8601 with offset, e.g. "
            "2026-07-12T15:00:00-04:00. For anything that REPEATS — a class, a weekly "
            "meeting, a standing appointment — pass `recurrence` and create ONE event. "
            "Never call this tool in a loop to book each occurrence separately: a "
            "semester class is ~45 calls, 45 calendar rows, and 45 deletions when the "
            "time changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_iso": {
                    "type": "string",
                    "description": "Start of the FIRST occurrence when recurring.",
                },
                "end_iso": {
                    "type": "string",
                    "description": "End of the FIRST occurrence — same day as start_iso.",
                },
                "description": {"type": "string"},
                "recurrence": {
                    "type": "string",
                    "description": (
                        "Optional RFC 5545 recurrence rule; omit for a one-off. Days are "
                        "MO TU WE TH FR SA SU, and UNTIL is UTC ending in Z. A MWF class "
                        "running through Dec 9: "
                        "FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261209T235959Z"
                    ),
                },
                "exclude_dates": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional YYYY-MM-DD dates the recurring series SKIPS — breaks, "
                        "holidays, reading days. Pass them here rather than creating the "
                        "series and deleting occurrences afterwards; a deleted occurrence "
                        "is a separate call each and comes back if the series is rebuilt. "
                        "Only meaningful alongside `recurrence`."
                    ),
                },
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
        "name": "get_school_day",
        "description": "One call for a school day: the lectures scheduled on that date (course, topic, readings, unit), assignments due inside the horizon, and upcoming exams — read straight from the Notion Lectures, Assignments, and Exams & Deadlines databases. Use this for 'what do I have today', class prep, and the morning brief instead of notion_search + notion_schema + notion_query; get_tasks only sees the Tasks inbox and knows nothing about coursework. Anything it could not read comes back in an errors list - say so rather than reporting an empty day.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "YYYY-MM-DD. Defaults to today in America/New_York."},
                "horizon_days": {"type": "integer", "description": "How far ahead to look for assignments (default 7). Exams use double this."},
            },
            "additionalProperties": False,
        },
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
        "name": "notion_search",
        "description": "Search the whole Notion workspace by title — pages AND databases. THE starting point for any Notion request that isn't the Tasks inbox: search first to get the id, then use notion_schema/notion_query/notion_create_page. If something the user names doesn't come back, it hasn't been shared with the integration — say so instead of writing it somewhere else.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Title text to match. Empty lists everything visible."},
                "kind": {"type": "string", "enum": ["page", "database"], "description": "Restrict to one object type"},
                "limit": {"type": "integer", "description": "Default 25, max 100"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "notion_schema",
        "description": "Read a Notion database's property names, types, and allowed select options. ALWAYS call this before the first write to a database you haven't written to this conversation — it's what makes properties land typed instead of guessed.",
        "input_schema": {
            "type": "object",
            "properties": {"database_id": {"type": "string"}},
            "required": ["database_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "notion_query",
        "description": "List rows from any Notion database, with properties flattened to plain values. Use notion_search to get the database_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "database_id": {"type": "string"},
                "filter": {"type": "object", "description": "Raw Notion filter object, optional"},
                "sorts": {"type": "array", "items": {"type": "object"}, "description": "Raw Notion sorts array, optional"},
                "limit": {"type": "integer", "description": "Default 25, max 100"},
            },
            "required": ["database_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "notion_read_page",
        "description": "Read one Notion page: its properties and its body text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "include_content": {"type": "boolean", "description": "Include body text (default true)"},
            },
            "required": ["page_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "notion_create_page",
        "description": "Create a page in ANY Notion database (or under any page). Pass properties as plain values — {\"Name\": \"Calc I\", \"Days\": [\"Mon\",\"Wed\"], \"Start\": \"2026-08-25\"} — they get typed against the live schema. Call notion_schema first so the names and select options are real. Creating several rows in one database is normal: make one call per row, don't collapse them into the Tasks inbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_id": {"type": "string", "description": "Database id, or page id when parent_is_page is true"},
                "title": {"type": "string", "description": "Fills whichever property is the title column"},
                "properties": {"type": "object", "description": "Property name -> plain value"},
                "content": {"type": "string", "description": "Optional page body. Markdown headings, bullets, and - [ ] to-dos are converted."},
                "parent_is_page": {"type": "boolean", "description": "True to nest under a page instead of a database"},
            },
            "required": ["parent_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "notion_update_page",
        "description": "Edit properties on an existing Notion page. Plain values, typed against the page's parent database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "properties": {"type": "object", "description": "Property name -> new plain value"},
            },
            "required": ["page_id", "properties"],
            "additionalProperties": False,
        },
    },
    {
        "name": "notion_append",
        "description": "Append body content to an existing Notion page. Markdown headings, bullets, and - [ ] to-dos are converted to blocks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["page_id", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "notion_create_database",
        "description": "Create a new Notion database under a page — use when the user asks for a tracker/table that doesn't exist yet. properties maps name -> type: title, rich_text, select, multi_select, date, number, checkbox, url. Requires approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parent_page_id": {"type": "string", "description": "Page to nest it under (notion_search for it)"},
                "title": {"type": "string"},
                "properties": {"type": "object", "description": "Property name -> Notion property type"},
            },
            "required": ["parent_page_id", "title", "properties"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_unread_email",
        "description": "Count unread Gmail messages and list the latest senders/subjects.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_inbox_recent",
        "description": "List the latest inbox emails (newest first) with sender, subject, unread flag, a text snippet, and a stable uid per message. THE read for an inbox triage or an inbox→calendar sweep: review these, then propose archive_emails(uids) for the junk, draft replies for what matters, or create_calendar_event for real events found in mail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many recent messages (default 25, max 50)"},
                "days": {"type": "integer", "description": "Only messages from the last N days (IMAP SINCE) — use 2 for daily sweeps"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "archive_emails",
        "description": "Archive inbox emails by uid (from get_inbox_recent). Reversible — Gmail keeps them in All Mail — but it ALWAYS queues ONE approval listing what gets archived before anything moves. Batch every archive of a triage into a single call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "uids": {"type": "array", "items": {"type": "string"}, "description": "uid values to archive"},
                "reason": {"type": "string", "description": "One line on why these are safe to archive (shown in the approval)"},
            },
            "required": ["uids"],
            "additionalProperties": False,
        },
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
        "description": (
            "Delete a Google Calendar event by id. Get the id from get_calendar first. "
            "Always requires the user's approval banner. CHOOSE THE ID DELIBERATELY: "
            "pass a row's `id` to cancel ONE meeting, or its `series_id` to remove the "
            "entire recurring series. Deleting occurrence ids one at a time to clear a "
            "class is wrong — it's a call per meeting, and they all return the moment "
            "the series is touched."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "A row's `id` for one meeting, or its `series_id` for the whole series.",
                },
                "title": {"type": "string", "description": "Event title, for the approval preview"},
            },
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
        "name": "run_on_laptop",
        "description": "Dispatch a task to Trav's laptop (the local worker): files in his workspace, running shell commands (asks approval), REAL WEB BROWSING via Playwright — navigate a site, read/extract content, click, fill forms, screenshot — and LOOKING AT HIS SCREEN (the worker's look_at_screen tool answers 'what does this error say?' / 'what's open right now?'). Use for anything that needs his machine, interacting with a website (not just opening it), or seeing his screen. Give a clear, self-contained task; it runs in the background and streams into the feed.",
        "input_schema": {
            "type": "object",
            "properties": {"task": {"type": "string", "description": "Full self-contained task for the laptop agent"}},
            "required": ["task"],
            "additionalProperties": False,
        },
    },
    {
        "name": "open_folder",
        "description": "Open a folder on Trav's Mac in Finder so he can see it. Use for 'open/show/pull up <folder>'. Give a full path; ~ means his home (e.g. ~/Desktop, ~/Downloads, ~/Documents/Projects).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Folder path, e.g. ~/Desktop or /Users/trav/Documents"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reveal_in_finder",
        "description": "Reveal a specific file (highlighted in its folder) in Finder on Trav's Mac. Use when he wants to locate one file rather than open a whole folder.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path to reveal, ~ means home"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "open_file",
        "description": "Open a file on Trav's Mac with its default app (e.g. a PDF in Preview, a doc in its editor). Use for 'open <file>'. Give the full path; ~ is home.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path to open, ~ means home"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "open_app",
        "description": "Open/launch an application on Trav's Mac. Use for 'open <app>' (e.g. Spotify, Notes, Calendar, Safari, Terminal). Give the app's name.",
        "input_schema": {
            "type": "object",
            "properties": {"app": {"type": "string", "description": "Application name, e.g. Spotify or Google Chrome"}},
            "required": ["app"],
            "additionalProperties": False,
        },
    },
    {
        "name": "open_website",
        "description": "Open a website in Trav's default browser so it's on his screen. Use for 'open the news / pull up <site> / go to <url>'. Resolve vague asks to a real URL yourself (e.g. 'the news' -> https://news.google.com). Include the full URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL, e.g. https://news.google.com or https://github.com"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_health",
        "description": "Latest Apple Watch health reading (sleep hours, resting HR, HRV, steps…) posted by Trav's iOS Shortcut. Returns nothing when there's no fresh data — in that case just skip health talk, don't apologize about it.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_recent_activity",
        "description": "The last N days of RESOLVE's own activity ledger (commands, outcomes, approvals/rejections, failures), day-labelled. THE source for a weekly review or 'what did we do this week?'.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "How many days back (default 7, max 14)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_audit_log",
        "description": "Security/transparency ledger: the actions RESOLVE actually took and approvals it requested/you decided (tools run, emails sent/archived, events created, deletes, failures) over the last N hours. Use for 'what did you do?', 'what did I approve?', 'did anything fail?', or a security review. Set sensitive=true to see only high-impact actions (sends, deletes, archives, budget, failures).",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Look-back window in hours (default 24)"},
                "sensitive": {"type": "boolean", "description": "Only high-impact actions"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "restart_worker",
        "description": "Restart the laptop worker process (it reloads fresh code and reconnects; launchd brings it right back). Use when Trav says the worker is stuck/stale or asks to restart it.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_finance",
        "description": "Get Trav's money summary from his connected bank (SimpleFIN): net worth, earnings, expenses, net, by-month, and recent transactions over the last `days` (default 30). Use for any spending/income/balance question.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "Lookback window in days (default 30)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_project",
        "description": "Hand off ONLY a genuinely complex goal needing 3+ dependent steps or sustained background work (a research project, staged build, bulk work) to the Planner + background executor. This spins up a pricier planner model, so do NOT use it for tasks you can finish yourself in a few tool calls — do those directly. Call ONCE with a clear objective; steps run in the background (the executor can research the web) and stream into the event feed.",
        "input_schema": {
            "type": "object",
            "properties": {"objective": {"type": "string", "description": "Full objective with all needed details"}},
            "required": ["objective"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_google_doc",
        "description": "Create a Google Doc in Trav's Drive from Markdown and return a shareable link. Use whenever he wants a doc, write-up, notes, letter, or report in Google Docs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The document title / filename"},
                "content": {"type": "string", "description": "Body as Markdown (headings, lists, **bold**, tables, links). Optional — omit for a blank doc."},
                "folder": {"type": "string", "description": "Optional Drive folder name to put it in (created if it doesn't exist). Omit for root."},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_google_sheet",
        "description": "Create a Google Sheet in Trav's Drive and optionally fill it with rows. Returns a link. Use for spreadsheets, trackers, or tabular data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The spreadsheet title"},
                "rows": {
                    "type": "array",
                    "description": "Optional rows to write, as an array of arrays. First row is treated as headers.",
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "folder": {"type": "string", "description": "Optional Drive folder name to put it in (created if it doesn't exist). Omit for root."},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_google_slides",
        "description": "Create a Google Slides deck in Trav's Drive from Markdown (use a line with only '---' to separate slides). Returns a link. Use for presentations or slide decks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The presentation title"},
                "content": {"type": "string", "description": "Markdown; '---' on its own line separates slides. '# Heading' per slide, bullets with '-'."},
                "folder": {"type": "string", "description": "Optional Drive folder name to put it in (created if it doesn't exist). Omit for root."},
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "save_to_vault",
        "description": "Save a FULL document / research writeup / analysis / plan to Trav's vault (his second brain, in GitHub). This is the DEFAULT home for substantial output — use it whenever you produce something worth keeping, UNLESS Trav named a specific project or asked for a Google Doc/Sheet/Slides. Give a clear title and the complete content in Markdown. Returns a link.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "A clear note title"},
                "content": {"type": "string", "description": "The FULL content in Markdown"},
                "category": {"type": "string", "description": "Optional vault subfolder under wiki/ (default 'output'), e.g. research, notes, projects"},
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_google_file",
        "description": "Find a file in Trav's Google Drive by name (or Drive query). Returns matches with their id, name, type, and link. Use this FIRST to get a file's id before editing or deleting it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A name to search for (e.g. 'Q3 report'), or a full Drive query."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_products",
        "description": "Search for products to buy across retailers (Amazon, Best Buy, Target, Walmart, etc. via Google Shopping) with live prices, ratings, and links. Use whenever Trav wants to find, compare, or price something to buy ('find me…', 'how much is…', 'cheapest…'). Returns a ranked list; reply with the top few as name — price — [link]. Note: it's cross-retailer, so Amazon shows up when it's in the shopping feed, not always.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for, e.g. 'noise cancelling headphones' or 'standing desk'."},
                "max_price": {"type": "integer", "description": "Only products at or below this price (USD)."},
                "min_price": {"type": "integer", "description": "Only products at or above this price (USD)."},
                "sort_by": {"type": "integer", "description": "1 = price low→high, 2 = price high→low."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_google_doc",
        "description": "Append text to the end of an existing Google Doc (plain text). Get the document_id from create_google_doc or find_google_file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "The Google Doc id"},
                "content": {"type": "string", "description": "Text to append to the end of the doc"},
                "name": {"type": "string", "description": "Optional doc name for the activity log"},
            },
            "required": ["document_id", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "edit_google_sheet",
        "description": "Append rows to an existing Google Sheet. Get the spreadsheet_id from create_google_sheet or find_google_file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string", "description": "The spreadsheet id"},
                "rows": {"type": "array", "description": "Rows to append, as an array of arrays.", "items": {"type": "array", "items": {"type": "string"}}},
                "sheet": {"type": "string", "description": "Optional tab name (defaults to Sheet1)."},
                "name": {"type": "string", "description": "Optional sheet name for the activity log"},
            },
            "required": ["spreadsheet_id", "rows"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_google_slides",
        "description": "Append slides (from Markdown, '---' between slides) to an existing Google Slides deck. Get the presentation_id from create_google_slides or find_google_file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "presentation_id": {"type": "string", "description": "The presentation id"},
                "content": {"type": "string", "description": "Markdown for the new slides; '---' separates slides"},
                "name": {"type": "string", "description": "Optional deck name for the activity log"},
            },
            "required": ["presentation_id", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "code_task",
        "description": "Write or change CODE in one of Trav's projects on his laptop. A coding architect first reads the objective and writes a file-level brief, then the laptop agent implements it against the real repo and runs the tests. Use for 'fix the bug in X', 'add feature Y to Z', 'make the tests pass'. Give the full objective and the project path if you know it. Runs in the background and streams into the feed; shell commands there ask for Trav's approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "objective": {"type": "string", "description": "What the code should do differently, in full"},
                "path": {"type": "string", "description": "Project folder on his Mac, e.g. ~/claude/resolve"},
                "context": {"type": "string", "description": "Anything Trav said about the project that the architect should know"},
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
    },
    {
        "name": "review_code",
        "description": "Have an independent reviewer model read a diff and report real problems, ranked by severity. Use when Trav pastes a diff, asks 'does this look right', or after a code_task produces changes he wants checked.",
        "input_schema": {
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "The diff or code to review"},
                "objective": {"type": "string", "description": "What the change was meant to do"},
            },
            "required": ["diff"],
            "additionalProperties": False,
        },
    },
    {
        "name": "github_issues",
        "description": "Open issues on one of Trav's GitHub repos. Omit repo to use his default repo. Use for 'what's open on X', 'what am I working on', or before creating an issue so you don't file a duplicate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "owner/name, e.g. Tstansberry81/resolve"},
                "state": {"type": "string", "enum": ["open", "closed", "all"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "github_pull_requests",
        "description": "Open pull requests on a GitHub repo (omit repo for his default).",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "state": {"type": "string", "enum": ["open", "closed", "all"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "github_ci",
        "description": "Recent GitHub Actions runs for a repo, with failures highlighted. THE answer to 'did the build pass', 'is CI green', or 'did I break anything'.",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "create_github_issue",
        "description": "File a GitHub issue on one of Trav's repos — use to capture a bug, an idea, or a TODO he mentions so it isn't lost. Check github_issues first to avoid duplicates. Write a real, specific body, not a placeholder.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string", "description": "Markdown: what's wrong / what to do, and why"},
                "repo": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
            "additionalProperties": False,
        },
    },
    {
        "name": "vault_recall",
        "description": "Search Trav's vault BY MEANING rather than exact words — use when vault_read's keyword search finds nothing but you believe he's written about it, or when you don't know the wording he used ('what did I decide about X', 'have I written about Y before'). Returns matching passages with their file paths; vault_read the path for the full note.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What you're looking for, in plain language"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_google_doc",
        "description": "Read an existing Google Doc's full text. Get the document_id from create_google_doc or find_google_file. ALWAYS read a doc before editing it — you need to see the exact wording to replace.",
        "input_schema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "replace_in_google_doc",
        "description": "Find and replace text inside an existing Google Doc — this is how you EDIT or FIX a doc (edit_google_doc only appends to the end). Read the doc first, then pass the exact existing text as find_text. To delete text, pass an empty replace_text. To rewrite a paragraph, find the old paragraph and replace it with the new one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "find_text": {"type": "string", "description": "Exact text currently in the doc"},
                "replace_text": {"type": "string", "description": "What to put there instead (empty string deletes it)"},
                "name": {"type": "string", "description": "Optional doc name for the activity log"},
            },
            "required": ["document_id", "find_text", "replace_text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_google_sheet",
        "description": "Read cells from an existing Google Sheet. Give an A1 range like 'Sheet1!A1:D50' (defaults to A1:Z200). Read before updating so you know which row/cell to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string", "description": "A1 notation, e.g. Sheet1!A1:D50"},
            },
            "required": ["spreadsheet_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "update_google_sheet",
        "description": "Overwrite a specific range of cells in a Google Sheet (edit_google_sheet only appends new rows at the bottom). Use for correcting a value, updating a status column, or fixing a row. Values starting with '=' become real formulas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "spreadsheet_id": {"type": "string"},
                "range": {"type": "string", "description": "Exact A1 range to overwrite, e.g. Sheet1!B2:C3"},
                "rows": {"type": "array", "description": "Rows of values, as an array of arrays, matching the range's shape.", "items": {"type": "array", "items": {"type": "string"}}},
                "name": {"type": "string", "description": "Optional sheet name for the activity log"},
            },
            "required": ["spreadsheet_id", "range", "rows"],
            "additionalProperties": False,
        },
    },
    {
        "name": "draft_email",
        "description": "Save a DRAFT email in Trav's Gmail for him to review, edit, and send himself from his phone or laptop. Nothing is sent. Prefer this over send_email whenever he hasn't explicitly said to send it — and use it for every reply you write during an inbox triage, so the drafts are waiting for him in Gmail instead of trapped in this chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "thread_id": {"type": "string", "description": "Optional Gmail thread id to reply inside; omit the subject when replying to a thread."},
            },
            "required": ["to", "body"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_weather",
        "description": "Current conditions and a daily forecast for a place (defaults to Baltimore). Use for any weather question and before advising on travel, outdoor plans, or what to wear.",
        "input_schema": {
            "type": "object",
            "properties": {
                "place": {"type": "string", "description": "City or place name, e.g. Charlottesville"},
                "days": {"type": "integer", "description": "Forecast days, 1-7 (default 3)"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_travel_time",
        "description": "Driving time and distance between two places. Use for 'how long to get to X', and to work out when Trav needs to leave for something on his calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
            },
            "required": ["origin", "destination"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_canvas",
        "description": "Trav's upcoming Canvas coursework — assignment titles, courses, and due dates from his Canvas calendar feed. THE source for 'what's due', homework, and school deadlines. Note it covers due dates only: for grades, submission status, or announcements, use run_on_laptop to open Canvas in his logged-in browser.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "How far ahead to look, 1-60 (default 14)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "spotify_play",
        "description": "Play music on Trav's Spotify. Pass a query like 'Bad Bunny Tití Me Preguntó' to find and play a track, or omit everything to resume what's paused. Needs an active Spotify device (a phone/Mac/speaker with Spotify open).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to play — song, or 'song by artist'"},
                "uri": {"type": "string", "description": "Exact Spotify URI, if you already have one from spotify_search"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "spotify_control",
        "description": "Pause, skip forward, or go back on Trav's Spotify.",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["pause", "next", "previous"]}},
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "spotify_search",
        "description": "Search Spotify for a track, album, artist, or playlist and get its URI. Use when Trav wants options rather than immediate playback.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "kind": {"type": "string", "enum": ["track", "album", "artist", "playlist"]},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_music_taste",
        "description": "Trav's actual listening taste from Spotify: top artists, top genres, and top tracks over a window. CALL THIS FIRST whenever he asks for music recommendations, a playlist, or 'what should I listen to' — recommend from real data, never from guesses about what he likes. time_range: short_term (~4 weeks, what he's into RIGHT NOW), medium_term (~6 months, default), long_term (~1 year, his core taste).",
        "input_schema": {
            "type": "object",
            "properties": {"time_range": {"type": "string", "enum": ["short_term", "medium_term", "long_term"]}},
            "additionalProperties": False,
        },
    },
    {
        "name": "spotify_recent",
        "description": "The tracks Trav played most recently, newest first. Use for 'what have I been listening to', or alongside get_music_taste to catch a current mood that his 6-month averages would miss.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "How many, 1-50 (default 25)"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "spotify_queue",
        "description": "Add tracks to Trav's Spotify queue so they play after the current song. Use this to act on recommendations — find each track with spotify_search to get its URI, then queue them. Better than spotify_play for a set of songs, since play would interrupt what's already on.",
        "input_schema": {
            "type": "object",
            "properties": {"uris": {"type": "array", "items": {"type": "string"}, "description": "Spotify track URIs from spotify_search, max 10"}},
            "required": ["uris"],
            "additionalProperties": False,
        },
    },
    {
        "name": "spotify_now_playing",
        "description": "What's playing on Trav's Spotify right now.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "delete_google_file",
        "description": "Permanently delete a file in Trav's Google Drive by id (irreversible). Get the file_id from find_google_file first. Requires Trav's approval before it runs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "The Drive file id to trash"},
            },
            "required": ["file_id"],
            "additionalProperties": False,
        },
    },
]

SYSTEM = """You are RESOLVE — Trav's personal AI agent and the front door to his whole
platform. You talk to Trav directly and get things done with the tools you have: calendar
reads/writes, Notion tasks, email checks, single email sends (approval-gated), vault logs.

Who you are:
- Do what Trav asks, using your access, and do it efficiently. Don't guess — if you're unsure
  or missing something, check with a tool or ask rather than inventing.
- Accuracy matters: no sloppy mistakes. For anything larger (building something, research,
  multi-step work), verify the result and confirm with Trav before calling it done.

Personality & how you talk to Trav:
- You're genuinely funny and warm. In casual chat, keep it light and informal — crack jokes,
  have fun, don't be a stiff.
- Trav's given you the green light to be crude and unfiltered with HIM specifically: roast him,
  fuck with him, swear freely, and lean into raunchy 18+ humor when the vibe is casual. Don't
  be precious about it — he can take it and he asked for it.
- Keep it affectionate, not genuinely mean. Bust his balls; don't kick him while he's down.
- Read the room. The moment it's real work, an actual problem, something time-sensitive, or
  he's clearly not in the mood — drop the bit entirely and be sharp, precise, and reliable.
- Never aim the crude/roast humor at anyone but Trav. Third parties (emails, people he mentions,
  anyone you act toward on his behalf) get the clean, professional version.

How you operate:
- Answer questions about schedule/tasks/email/money by CALLING TOOLS first. Never invent data.
  For spending, income, balances, or net worth, call get_finance.
- Use ISO 8601 datetimes with the America/New_York offset for calendar writes.
- send_email only queues for Trav's approval; tell him it's waiting on his approval banner.
- INBOX TRIAGE ("triage my inbox", "clean up my email"): call get_inbox_recent, then sort
  the messages yourself into (a) needs-a-reply — write each reply with draft_email so it's
  waiting in his Gmail to edit and send from his phone, then list what you drafted,
  (b) worth a look — one line each, (c) junk/newsletters/promos — archive via ONE
  archive_emails call with all their uids + a reason. The archive queues a single approval
  banner; never archive anything that plausibly needs Trav's eyes, and never send during triage.
- EMAIL, generally: draft_email saves a draft and sends nothing — that's the default when
  Trav hasn't explicitly told you to send. send_email actually sends and always needs his
  approval. When in doubt, draft it.
- Deletes (delete_task, delete_calendar_event) also queue for approval — look up the id first,
  then call the delete tool and tell him it's waiting on his banner.
- When Trav wants something done ON his laptop (his files, running a command, reading a web
  page for him), use run_on_laptop with a clear task. Shell commands there ask for his approval.
- To OPEN things on his Mac for him (hands-free, no approval): open_folder (a folder in Finder),
  reveal_in_finder (one file), open_app (launch an app), open_website (a URL in his browser).
  Resolve vague targets yourself — 'the news' -> https://news.google.com, 'my downloads' ->
  ~/Downloads, 'spotify' -> open_app Spotify. Just do it and tell him it's opening; these need
  the laptop worker to be online.
- To find, compare, or price something to buy, use search_products (cross-retailer
  shopping search with live prices + links). Give Trav the top few as name — price — link.
- For Google Docs/Sheets/Slides, use create_google_doc / create_google_sheet / create_google_slides.
  Write real content (Markdown), not placeholders, and give Trav the returned link.
  To CHANGE an existing file: find_google_file for its id, then READ it (read_google_doc /
  read_google_sheet) before you touch it, then edit. Editing has two different shapes and
  picking the wrong one is a common mistake:
    * to FIX, REWRITE, or DELETE existing content -> replace_in_google_doc /
      update_google_sheet (they change what's already there);
    * to ADD to the end -> edit_google_doc / edit_google_sheet / add_google_slides.
  replace_in_google_doc needs the exact current wording, which is why you read first — if it
  replaces 0 occurrences nothing changed, so re-read and try again rather than claiming success.
  To remove a file, find it then delete_google_file (permanent — asks for approval first).
- SCHOOL: get_canvas gives Trav's upcoming assignments and due dates. Use it for anything
  about homework, deadlines, or what's due, and combine it with get_calendar when planning
  his week. It covers due dates only — for grades, whether something was submitted, or
  announcements, use run_on_laptop to check Canvas in his logged-in browser.
- get_weather and get_travel_time are cheap and keyless — use them freely. Check the weather
  before advising on anything outdoors or travel-related, and use get_travel_time plus his
  calendar to tell him when to leave. Travel time ignores live traffic, so pad it at rush hour.
- MUSIC: spotify_play / spotify_control / spotify_now_playing drive his Spotify. Playback
  needs an active device — if it says there isn't one, tell him to open Spotify somewhere first.
- RECOMMENDING MUSIC: never guess at his taste. Call get_music_taste FIRST (add
  spotify_recent when the ask is mood-driven — 'something for right now', 'study music' —
  since a current kick doesn't show up in six-month averages). Then recommend YOURSELF from
  that data: you know music, and you can weigh occasion, tempo, and season in a way a
  similar-artists list can't. Lean on what his top GENRES say, not just artist names.
  Give a handful of specific tracks, one short line each on why it fits him — and don't
  only return artists already in his top list; he knows those. Then offer to queue them:
  spotify_search each for its URI, then spotify_queue (queue rather than play, so you
  don't cut off what's already on). If he asks for a playlist, treat it as a queue.
- MEMORY: vault_read greps his vault for exact words; vault_recall searches it by MEANING.
  When he refers to something he's told you before ('what did I decide about…', 'the thing I
  wrote on…') and the keyword search comes back empty, try vault_recall before concluding it
  isn't there — he rarely uses the same words twice.
- CODE: code_task writes or changes code in his projects (an architect plans it, then his
  laptop implements and runs the tests). review_code gets an independent read on a diff.
  github_issues / github_pull_requests / github_ci answer what's open and whether the build
  passed; create_github_issue captures a bug or idea he mentions so it isn't lost.
- ATTACHMENTS: Trav can send you photos, screenshots, PDFs, and voice notes from
  Telegram — they arrive in his message and you can see/read them directly. A voice
  note arrives already transcribed as a line starting 'Voice note, transcribed:';
  treat it as him talking to you and answer the request, don't just repeat it back.
  When he sends something with no caption, don't stop at describing it — do the
  obvious next thing (a receipt goes to his finance/vault notes, an error
  screenshot gets diagnosed, an event flyer becomes a calendar event, a document
  gets saved). Read it, then ACT with your tools.
- EXECUTION DISCIPLINE (critical): When Trav asks for something, DO IT this turn by
  calling the tool — never announce that you're "about to", "creating it now", "on it",
  "give me a sec", or that you'll do it. Those phrases without an actual tool call are
  lies. Either call the tool now, or ask ONE specific clarifying question.
- NEVER say "Done", "Created", "Here's your…", or claim you finished ANYTHING unless a
  tool actually ran and returned a result in THIS conversation. If you did not call a
  tool, you did nothing — saying otherwise is a hallucination and is unacceptable. When
  you create something, the reply MUST contain the real link/result the tool returned.
- Only reply when ONE of these is true: (a) the task is fully done — then report the real
  result (the link, the outcome); (b) you need a clarifying question to proceed; or (c) part
  of it is genuinely blocked by something broken or missing that you cannot fix. Never a
  vague half-answer.
- In case (c), DELIVER EVERY PART THAT ISN'T BLOCKED, in full, in that same reply. Then say
  exactly what you couldn't do and why. A broken tool blocks the steps that need that tool —
  it does not excuse the steps that don't. If he asks you to research something and save it,
  and only the saving is broken, the research still lands in the reply. Never convert a
  broken-tool problem into a clarifying question and deliver nothing.
- When several failures share one cause — a dead token breaking every vault read AND write —
  report it once as one root cause, not as a list of separate problems.
- Never say you can't do something or aren't able to. You have real tools — use them. If a
  tool errors, say what failed plainly; don't pretend it worked.
- Never drop a task after acknowledging it. If you took it on, finish it before you reply.
- OUTPUT & LOGGING (important): a BRIEF summary of every task is auto-logged to Trav's vault —
  you don't do that yourself. But whenever you produce SUBSTANTIAL output (research findings,
  a document, analysis, a plan, a writeup), SAVE THE FULL THING so it's never lost. Default to
  his vault via save_to_vault; ONLY use Google (create_google_doc/sheet/slides) instead when he
  named a specific project or explicitly wants a Google file. Either way, give him the link.
  Use judgment: a quick factual answer needs no save; anything he'd want to keep does.
- When you include a link in a reply, paste the full URL or a [label](url) markdown link.
- Keep replies tight — a sentence or a short paragraph. Humor is welcome; padding is not.
- DEFAULT TO DOING IT YOURSELF. You have real tools — for anything you can finish with the
  tools you have (a doc, a calendar event, a task, checking email/finance, opening things,
  a vault read/save), just do it directly. Do NOT hand those off — handing off spins up a
  pricier planner model, so it must earn it.
- YOU CAN SEARCH THE WEB (web_search). Use it whenever the answer depends on current or
  external facts: prices, news, scores, hours, "what is X", "is Y still true", release dates,
  documentation, anything after your training cutoff. NEVER guess at a fact you could look
  up, and never tell Trav you can't look something up. Searching costs real money though, so
  don't search what you already know or what's in his calendar/email/vault — check your own
  tools first. Cite the source with a link when the answer came off the web.
- plan_project is NOT for questions anymore. Hand off ONLY genuine projects: 3+ DEPENDENT
  steps, sustained background work, a staged build, bulk/multi-part work, or deep research
  that needs many sources and a written writeup. A question you can answer with a search or
  two — even a few searches — you answer YOURSELF, right now. Handing those off spins up a
  pricier planner and makes Trav wait for a background run he shouldn't have to wait for.
- So: a question, a lookup, a comparison -> search and answer it yourself. A real
  multi-step project or deep research writeup -> plan_project ONCE with the full objective;
  tell Trav it's queued and list the steps. Everything else -> just do it with your tools."""


