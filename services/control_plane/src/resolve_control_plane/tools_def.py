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
    "save_to_vault": ("vault.write", "vault"),
    "vault_read": ("vault.read", "vault"),
    "plan_project": ("plan.project", "planner"),
    "delete_task": ("notion.page.archive", "notion"),
    "delete_calendar_event": ("calendar.delete", "calendar"),
    "ask_local": ("local.ask", "web"),
    "get_finance": ("finance.read", "finance"),
    "run_on_laptop": ("laptop.dispatch", "local"),
    "open_folder": ("laptop.display", "local"),
    "reveal_in_finder": ("laptop.display", "local"),
    "open_file": ("laptop.display", "local"),
    "open_app": ("laptop.display", "local"),
    "open_website": ("laptop.display", "local"),
    "create_google_doc": ("gdrive.create", "google"),
    "create_google_sheet": ("gdrive.create", "google"),
    "create_google_slides": ("gdrive.create", "google"),
    "find_google_file": ("gdrive.read", "google"),
    "edit_google_doc": ("gdrive.edit", "google"),
    "edit_google_sheet": ("gdrive.edit", "google"),
    "add_google_slides": ("gdrive.edit", "google"),
    "delete_google_file": ("gdrive.delete", "google"),
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
        "name": "run_on_laptop",
        "description": "Dispatch a task to Trav's laptop (the local worker): files in his workspace, running shell commands (asks approval), and REAL WEB BROWSING via Playwright — navigate a site, read/extract content, click, fill forms, screenshot. Use for anything that needs his machine OR interacting with a website (not just opening it). Give a clear, self-contained task; it runs in the background and streams into the feed.",
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
        "description": "Hand a complex multi-step goal to the Planner (Opus 4.8) and the Opus executor. Call ONCE with a clear objective; steps run in the background (the executor can research the web) and stream into the event feed.",
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
- Deletes (delete_task, delete_calendar_event) also queue for approval — look up the id first,
  then call the delete tool and tell him it's waiting on his banner.
- When Trav wants something done ON his laptop (his files, running a command, reading a web
  page for him), use run_on_laptop with a clear task. Shell commands there ask for his approval.
- To OPEN things on his Mac for him (hands-free, no approval): open_folder (a folder in Finder),
  reveal_in_finder (one file), open_app (launch an app), open_website (a URL in his browser).
  Resolve vague targets yourself — 'the news' -> https://news.google.com, 'my downloads' ->
  ~/Downloads, 'spotify' -> open_app Spotify. Just do it and tell him it's opening; these need
  the laptop worker to be online.
- For Google Docs/Sheets/Slides, use create_google_doc / create_google_sheet / create_google_slides.
  Write real content (Markdown), not placeholders, and give Trav the returned link.
  To change an existing file, call find_google_file to get its id, then edit_google_doc /
  edit_google_sheet / add_google_slides. To remove one, find it then delete_google_file
  (permanent delete — it asks for Trav's approval first).
- EXECUTION DISCIPLINE (critical): When Trav asks for something, DO IT this turn by
  calling the tool — never announce that you're "about to", "creating it now", "on it",
  "give me a sec", or that you'll do it. Those phrases without an actual tool call are
  lies. Either call the tool now, or ask ONE specific clarifying question.
- NEVER say "Done", "Created", "Here's your…", or claim you finished ANYTHING unless a
  tool actually ran and returned a result in THIS conversation. If you did not call a
  tool, you did nothing — saying otherwise is a hallucination and is unacceptable. When
  you create something, the reply MUST contain the real link/result the tool returned.
- Only reply when EITHER (a) the task is fully done — then report the real result (the
  link, the outcome), or (b) you need a clarifying question to proceed. Nothing in between.
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
- For complex multi-step requests (several distinct actions, research projects, bulk work),
  call plan_project ONCE with the full objective. The Planner (Opus 4.8) plans it, the Opus
  executor runs the steps in the background (and can research the web). Tell Trav the plan is
  queued and list the steps."""


