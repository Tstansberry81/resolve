"""The assistant loop — Sonnet fronts every command (docs/DIRECTION.md).

Each tool call passes through the policy engine: reads and reversible writes
execute immediately; communication sends and destructive actions create a
pending approval (dashboard banner) and only execute on your decision."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import anthropic
import anyio

from . import artifacts, bus, costs, executor, store
from .connectors import composio, gcal, gmail_imap, local_llm, notion_api, simplefin, vault_github
from .domain import AutonomyMode
from .policy import PolicyDecision, evaluate_tool_call
from .tools_def import SYSTEM, TOOL_POLICY, TOOLS
from .msgutil import cached_system, compact_messages

log = logging.getLogger("resolve.assistant")

ASSISTANT_MODEL = os.getenv("ASSISTANT_MODEL", "claude-haiku-4-5-20251001")
MAX_TURNS = 8

# what to tell Trav to run when his laptop worker is offline
WORKER_RESTART_CMD = "launchctl kickstart -k gui/$(id -u)/com.resolve.localworker"

# A short message that's really a STOP/cancel command — must take priority and
# kill the running task, not queue behind it.
_STOP_STARTS = re.compile(r"^(stop|cancel|abort|halt|quit|kill)\b", re.I)
# "stop by / stop at ..." — the verb is used normally, not as a stop command
_STOP_NOT_STOP = re.compile(r"^stop\s+(by|at|off|for|near|into|onto|in|on|to)\b", re.I)
_STOP_PHRASES = {
    "enough", "wait", "whoa", "hold on", "hold up", "nevermind", "never mind",
    "forget it", "forget that", "scratch that", "cut it out", "drop it",
    "thats enough", "that's enough", "shut it down", "knock it off",
    # "end" is only a stop command in these exact forms (not "end of year report")
    "end it", "end this", "end that", "end task", "end the task", "end this task",
}


def _is_stop(text: str) -> bool:
    """A brief message that means 'stop what you're doing' (not a real task)."""
    t = (text or "").strip().rstrip(".!?").lower()
    words = t.split()
    if not words or len(words) > 8:  # long messages are genuine tasks
        return False
    if t in _STOP_PHRASES:
        return True
    return bool(_STOP_STARTS.match(t)) and not _STOP_NOT_STOP.match(t)

# The model hallucinates in two ways when it ends a turn WITHOUT calling a tool:
# it promises ("creating it now") or falsely claims completion ("Done."). Either
# is a lie if no tool ran. We detect both, plus whether the user's request was
# actionable at all — if it was and nothing ran, that alone is enough to nudge.
_CLAIM_RE = re.compile(
    r"\b(creating|making|building|setting up|working on|generating|drafting|"
    r"putting together|pulling (?:that|it) up|i'?ll|i will|let me|give me a|"
    r"one (?:sec|second|moment)|on it|hang on|hold on|getting (?:that|it)|"
    r"will (?:create|make|do|set|send|add|update|draft|delete|find|check)|"
    r"done|all set|created|made it|added|scheduled|sent|saved|posted|updated|"
    r"deleted|removed|finished|completed|drafted|generated|ready|is live|"
    r"here'?s (?:the|your|a)|i'?ve (?:created|made|added|sent|set|saved|scheduled|"
    r"updated|deleted|drafted|built|put|generated|done))\b",
    re.I,
)
_ACTIONABLE_RE = re.compile(
    r"\b(make|create|build|write|draft|add|send|schedule|set up|put|delete|remove|"
    r"update|edit|book|log|save|generate|email|text|remind|find|pull up|look up)\b",
    re.I,
)


def _claims_action(text: str) -> bool:
    t = (text or "").strip()
    if not t or t.rstrip().endswith("?"):  # a question is a clarification — allowed
        return False
    return bool(_CLAIM_RE.search(t))


def _looks_actionable(text: str) -> bool:
    """The user asked for something to be done — a tool should have run."""
    return bool(_ACTIONABLE_RE.search(text or ""))

def _connector_call(name: str, args: dict[str, Any]) -> Any:
    if name == "get_calendar":
        return gcal.list_events(int(args.get("days", 7)))
    if name == "create_calendar_event":
        return gcal.create_event(
            args["title"], args["start_iso"], args["end_iso"], args.get("description", "")
        )
    if name == "get_tasks":
        return notion_api.list_open_tasks()
    if name == "create_task":
        return notion_api.create_task(
            args["title"],
            due_date=args.get("due_date"),
            priority=args.get("priority", "Medium"),
            notes=args.get("notes", ""),
        )
    if name == "get_unread_email":
        return gmail_imap.unread_summary()
    if name == "send_email":
        return gmail_imap.send_email(args["to"], args["subject"], args["body"])
    if name == "vault_log":
        return vault_github.append_log(args["title"], list(args.get("lines", [])))
    if name == "save_to_vault":
        return _save_to_vault(str(args["title"]), str(args["content"]),
                              str(args.get("category", "output")))
    if name == "vault_read":
        if args.get("path"):
            return vault_github.read_file(str(args["path"]))
        return vault_github.search_files(str(args.get("query", "")))
    if name == "delete_task":
        notion_api.archive_page(str(args["page_id"]))
        return {"archived": True, "page_id": args["page_id"], "title": args.get("title", "")}
    if name == "delete_calendar_event":
        return gcal.delete_event(str(args["event_id"]))
    if name == "ask_local":
        if not executor.local_exec:
            return ("The local model is OFF. Don't use it — do this yourself or with the "
                    "other tools. (Trav turns it on with the exec toggle.)")
        return local_llm.chat(str(args["prompt"]))
    if name == "get_finance":
        s = simplefin.summary(int(args.get("days", 30)))
        # trim the transaction list for the model — it just needs the shape
        return {**s, "transactions": s.get("transactions", [])[:15]}
    if name == "run_on_laptop":
        from . import local
        return local.enqueue(str(args["task"]))
    if name == "open_folder":
        from . import local
        p = str(args["path"])
        return local.enqueue_action("folder", p, f"Opening {p} in Finder")
    if name == "reveal_in_finder":
        from . import local
        p = str(args["path"])
        return local.enqueue_action("reveal", p, f"Revealing {p} in Finder")
    if name == "open_file":
        from . import local
        p = str(args["path"])
        return local.enqueue_action("file", p, f"Opening {p}")
    if name == "open_app":
        from . import local
        a = str(args["app"])
        return local.enqueue_action("app", a, f"Opening {a}")
    if name == "open_website":
        from . import local
        u = str(args["url"])
        return local.enqueue_action("url", u, f"Opening {u}")
    if name == "create_google_doc":
        res = composio.create_doc(str(args["title"]), str(args.get("content", "")),
                                  folder=args.get("folder") or None)
        _log_gdrive_artifact(res)
        return res
    if name == "create_google_sheet":
        res = composio.create_sheet(str(args["title"]), args.get("rows") or None,
                                    folder=args.get("folder") or None)
        _log_gdrive_artifact(res)
        return res
    if name == "create_google_slides":
        res = composio.create_slides(str(args["title"]), str(args["content"]),
                                     folder=args.get("folder") or None)
        _log_gdrive_artifact(res)
        return res
    if name == "find_google_file":
        return composio.find_file(str(args["query"]))
    if name == "edit_google_doc":
        res = composio.edit_doc(str(args["document_id"]), str(args["content"]))
        _log_gdrive_artifact({**res, "title": args.get("name", "Google Doc")}, action="updated")
        return res
    if name == "edit_google_sheet":
        res = composio.edit_sheet(str(args["spreadsheet_id"]), args["rows"], args.get("sheet"))
        _log_gdrive_artifact({**res, "title": args.get("name", "Google Sheet")}, action="updated")
        return res
    if name == "add_google_slides":
        res = composio.add_slides(str(args["presentation_id"]), str(args["content"]))
        _log_gdrive_artifact({**res, "title": args.get("name", "Google Slides")}, action="updated")
        return res
    if name == "delete_google_file":
        return composio.delete_file(str(args["file_id"]))
    raise ValueError(f"unknown tool {name}")


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return (s[:60] or "note")


def _save_to_vault(title: str, content: str, category: str = "output") -> dict[str, Any]:
    """Write a FULL note/document to the vault (the default home for real output)."""
    cat = re.sub(r"[^a-z0-9/_-]+", "", (category or "output").lower()) or "output"
    path = f"wiki/{cat}/{_slug(title)}.md"
    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M")
    body = f"# {title}\n\n*saved by RESOLVE · {stamp}*\n\n{content.strip()}\n"
    vault_github.write_file(path, body, message=f"agent: save {title[:60]}")
    url = f"https://github.com/{vault_github.VAULT_REPO}/blob/main/{path}"
    return {"saved": True, "path": path, "url": url, "title": title}


def _log_task_summary(request: str, reply: str) -> None:
    """Always-on: drop a BRIEF one-liner for every task into the vault log so
    nothing goes untracked (the full artifact save is separate/case-by-case)."""
    if not vault_github.configured():
        return
    r = " ".join((reply or "").split())[:280]
    q = " ".join((request or "").split())[:200]
    try:
        vault_github.append_log(f"agent · {q[:60]}",
                                [f"- **Asked:** {q}", f"- **Result:** {r or '(done)'}"])
    except Exception:
        pass  # logging must never break the reply


def _log_gdrive_artifact(res: dict[str, Any], action: str = "created") -> None:
    """Drop a created/edited Google file into the Artifacts dock with its link."""
    url = res.get("url")
    if not url:
        return
    try:
        artifacts.record(str(res.get("title") or "Google file"), url,
                         location="gdrive", href=url, action=action)
    except Exception:
        pass


CONNECTOR_AVAILABLE = {
    "calendar": gcal.configured,
    "notion": notion_api.configured,
    "gmail": gmail_imap.configured,
    "vault": vault_github.configured,
    "web": local_llm.configured,  # the "web" dot doubles as the local-AI lane
    "finance": simplefin.configured,
    "local": lambda: __import__("resolve_control_plane.local", fromlist=["online"]).online(),
    "google": composio.configured,
}

# pending approval id → the action to run on approve
pending_actions: dict[str, dict[str, Any]] = {}

# recent (user_text, assistant_reply) exchanges — gives follow-up commands
# conversational context; process-local, resets on deploy
history: deque[tuple[str, str]] = deque(maxlen=8)


async def _queue_approval(goal_id: str, tool: str, args: dict[str, Any], risk: str) -> str:
    preview: list[str] = [f"{k}: {str(v)[:90]}" for k, v in args.items()]
    summary = {
        "send_email": f"Send email to {args.get('to', '?')}: “{args.get('subject', '')[:60]}”",
    }.get(tool, f"{tool} — needs your approval")
    row = {
        "action_summary": summary,
        "risk_class": risk,
        "request_json": {"tool": tool, "args": args},
        "preview_json": preview,
        "status": "pending",
    }
    if len(goal_id) == 36:
        row["goal_id"] = goal_id
    try:
        saved = await anyio.to_thread.run_sync(lambda: store.insert("approvals", row))
        approval_id = str(saved.get("id", uuid.uuid4()))
    except Exception:
        approval_id = str(uuid.uuid4())
    pending_actions[approval_id] = {
        "tool": tool,
        "args": args,
        "goal_id": goal_id,
        "summary": summary,
        "preview": preview,
        "risk": risk,
    }
    await bus.emit(
        "core", "approval.requested", summary,
        detail=f"risk: {risk} — waiting on you", level="approval", goal_id=goal_id,
    )
    _fanout_approval(approval_id, summary, risk, preview, "pending")
    # Push to Telegram with inline Approve/Reject buttons (approvable from phone).
    try:
        from .connectors import telegram_notify

        if telegram_notify.configured():
            await anyio.to_thread.run_sync(
                lambda: telegram_notify.send_approval(approval_id, summary, risk)
            )
    except Exception:
        pass  # notification must never block queuing the approval
    return approval_id


def _fanout_approval(approval_id: str, summary: str, risk: str, preview: list[str], status: str):
    bus._fanout(
        {
            "kind": "approval",
            "approval": {
                "id": approval_id,
                "goalId": approval_id,
                "actionSummary": summary,
                "risk": risk,
                "preview": preview,
                "recipient": None,
                "undoWindow": None,
                "status": status,
            },
        }
    )


async def decide_approval(approval_id: str, decision: str) -> dict[str, Any]:
    # local-worker shell approvals are decided here too, but executed on the
    # laptop (not in the cloud) — just record the decision for the worker to poll.
    from . import local
    if local.is_local_approval(approval_id):
        local.decide(approval_id, "approved" if decision == "approved" else "rejected")
        return {"ok": True, "local": True, "decision": decision}
    action = pending_actions.pop(approval_id, None)
    status = "approved" if decision == "approved" else "rejected"
    try:
        await anyio.to_thread.run_sync(
            lambda: store.update("approvals", {"id": f"eq.{approval_id}"}, {"status": status})
        )
    except Exception:
        pass
    if action is None:
        return {"ok": False, "error": "unknown or already-decided approval"}
    _fanout_approval(approval_id, action["summary"], action["risk"], action["preview"], status)
    if decision != "approved":
        await bus.emit(
            "assistant", "action.held", f"Rejected — {action['summary']} stays parked",
            level="warn", goal_id=action["goal_id"],
        )
        return {"ok": True, "executed": False}
    node = TOOL_POLICY[action["tool"]][1]
    try:
        result = await anyio.to_thread.run_sync(
            lambda: _connector_call(action["tool"], action["args"])
        )
        await bus.emit(
            node, f"{action['tool']}.executed", f"Approved and executed — {action['summary']}",
            detail=json.dumps(result)[:300], level="success",
            edge={"from": "assistant", "to": node}, goal_id=action["goal_id"],
        )
        return {"ok": True, "executed": True, "result": result}
    except Exception as exc:
        await bus.emit(
            node, f"{action['tool']}.failed", f"Approved but failed: {exc}",
            level="error", goal_id=action["goal_id"],
        )
        return {"ok": True, "executed": False, "error": str(exc)}


# ── one-task-at-a-time serialization ────────────────────────────────────────
# Everything runs through a single-consumer queue: the current task ALWAYS
# finishes before the next starts, so a stray mic pickup (or a second command)
# can never interrupt what's already running — it just waits its turn.
_cmd_queue: "asyncio.Queue[tuple[str, str]] | None" = None
_processor: "asyncio.Task | None" = None
_current_goal: str | None = None
_current_task: "asyncio.Task | None" = None  # the _loop running right now


def _ensure_processor() -> None:
    global _cmd_queue, _processor
    if _cmd_queue is None:
        _cmd_queue = asyncio.Queue()
    if _processor is None or _processor.done():
        _processor = asyncio.get_running_loop().create_task(_command_processor())


async def _command_processor() -> None:
    global _current_goal, _current_task
    assert _cmd_queue is not None
    while True:
        goal_id, text = await _cmd_queue.get()
        _current_goal = goal_id
        try:
            # run as a cancellable task so 'stop' can kill it mid-flight
            _current_task = asyncio.create_task(_loop(goal_id, text))
            await _current_task
        except asyncio.CancelledError:
            pass  # stopped on purpose
        except Exception:
            log.exception("command processing failed")
        finally:
            _current_task = None
            _current_goal = None
            _cmd_queue.task_done()


def queue_status() -> dict[str, Any]:
    """What's running now and how many are waiting — for the snapshot/UI."""
    return {"running": _current_goal is not None,
            "queued": _cmd_queue.qsize() if _cmd_queue is not None else 0}


async def stop_current() -> dict[str, Any]:
    """Immediately stop whatever's running: cancel the assistant turn, cancel the
    executor's current research step and drop the rest, and clear the queue.
    This is the 'stop' cutoff — it takes priority over everything."""
    # 1) drop anything waiting in line
    dropped_cmds = 0
    if _cmd_queue is not None:
        while not _cmd_queue.empty():
            try:
                _cmd_queue.get_nowait()
                _cmd_queue.task_done()
                dropped_cmds += 1
            except asyncio.QueueEmpty:
                break
    # 2) kill the executor's running research step + its remaining steps
    try:
        ex_result = await executor.stop_current()
    except Exception:
        ex_result = {}
    # 3) cancel the assistant turn in flight
    cancelled = False
    if _current_task is not None and not _current_task.done():
        _current_task.cancel()
        cancelled = True
    # 4) cancel any pending approvals — "stop" means the queued send/delete does
    #    NOT get to fire later if Trav taps approve
    dropped_approvals = 0
    for aid, act in list(pending_actions.items()):
        pending_actions.pop(aid, None)
        dropped_approvals += 1
        bus._fanout({"kind": "approval", "approval": {
            "id": aid, "goalId": act.get("goal_id", ""),
            "actionSummary": act.get("summary", ""), "risk": act.get("risk", ""),
            "preview": [], "status": "rejected"}})
        try:
            await anyio.to_thread.run_sync(
                lambda a=aid: store.update("approvals", {"id": f"eq.{a}"}, {"status": "rejected"}))
        except Exception:
            pass
    await bus.set_orb("idle", "Stopped — standing by", [])
    await bus.emit("assistant", "system.stopped",
                   "Stopped. Cancelled the running task and cleared the queue.",
                   level="warn")
    return {"cancelledAssistant": cancelled, "droppedQueued": dropped_cmds,
            "cancelledApprovals": dropped_approvals, **ex_result}


async def run_command(text: str) -> str:
    """Accept a command; returns the goal id. Runs are SERIALIZED — if one is
    already in flight, this waits in line and never interrupts it. EXCEPT a
    'stop' command, which jumps the line and cancels the running task."""
    if _is_stop(text):
        busy = (_current_goal is not None
                or (_cmd_queue is not None and not _cmd_queue.empty())
                or executor.is_working())
        res = await stop_current()
        reply = ("Stopped." if busy else "Nothing was running, but I'm clear and standing by.")
        await bus.emit("assistant", "assistant.reply", reply, detail=reply, level="success")
        return "stopped"

    goal_row = {
        "objective": text[:300],
        "category": "personal",
        "status": "active",
        "autonomy_mode": "execute",
        "max_cost_usd": 2,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        saved = await anyio.to_thread.run_sync(lambda: store.insert("goals", goal_row))
        goal_id = str(saved.get("id", uuid.uuid4()))
    except Exception:
        goal_id = str(uuid.uuid4())

    _ensure_processor()
    busy = _current_goal is not None
    # show the user's message immediately (even while it waits in line)
    await bus.emit("assistant", "goal.accepted", f"Goal accepted: {text[:120]}",
                   detail=text, goal_id=goal_id)
    if busy:
        await bus.emit(
            "assistant", "goal.queued",
            "Queued — I'll finish what I'm doing first, then get to this.",
            detail=text, goal_id=goal_id,
        )
    await _cmd_queue.put((goal_id, text))
    return goal_id


async def _loop(goal_id: str, text: str) -> None:
    # goal.accepted is emitted in run_command (so it shows immediately, even when
    # queued). Here we just flip the orb busy as this task actually starts.
    client = anthropic.AsyncAnthropic()
    await bus.set_orb("thinking", "Sonnet is working your request", ["assistant"])

    now = datetime.now(ZoneInfo("America/New_York"))
    # Static SYSTEM + tools are prompt-cached (billed 0.1x after the first turn);
    # the datetime line is a tiny uncached block so it can't bust that cache.
    system = cached_system(SYSTEM, (
        f"Right now it is {now.strftime('%A, %B %d, %Y at %I:%M %p')} Eastern."
        " Resolve every relative date (tomorrow, Sunday, next week) from this —"
        " never guess weekdays. 'Tomorrow' always means the next calendar date,"
        " even between midnight and dawn."
    ))
    messages: list[dict[str, Any]] = []
    for prior_user, prior_reply in history:
        messages.append({"role": "user", "content": prior_user})
        messages.append({"role": "assistant", "content": prior_reply})
    messages.append({"role": "user", "content": text})
    # Only offer the local-model tool when the exec toggle is on — otherwise
    # Sonnet must never route to Qwen (it's likely offline and it's opt-in).
    active_tools = TOOLS if executor.local_exec else [t for t in TOOLS if t["name"] != "ask_local"]
    final_text = ""
    tools_ran = False   # did any tool actually execute this request?
    nudges = 0          # anti-hallucination re-prompts used
    try:
        for _ in range(MAX_TURNS):
            # trim stale tool_result blobs so a long loop doesn't re-send them full
            compact_messages(messages)
            resp = await client.messages.create(
                model=ASSISTANT_MODEL,
                # big enough to hold a full doc/sheet's content inside a single
                # tool call — 1500 truncated long docs mid-call so nothing ran
                max_tokens=8000,
                system=system,
                tools=active_tools,
                messages=messages,
            )
            costs.record("assistant", ASSISTANT_MODEL, resp.usage)
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            texts = [b.text for b in resp.content if b.type == "text"]
            # Cut off mid-response by the token cap — usually a truncated tool
            # call that never ran. Retry asking for tighter content, don't fake it.
            if resp.stop_reason == "max_tokens" and not tools_ran:
                if nudges < 2:
                    nudges += 1
                    # can't append the truncated tool call; use a synthetic turn to
                    # keep roles alternating, then ask for tighter content
                    messages.append({"role": "assistant",
                                     "content": "(my last attempt was cut off before it ran)"})
                    messages.append({"role": "user", "content":
                        "That was cut off by length before the tool ran, so NOTHING was "
                        "created. Make the content more concise so the whole tool call fits, "
                        "and call the tool now."})
                    continue
                final_text = ("That got cut off before it went through — nothing was created. "
                              "Try again and I'll keep it tighter.")
                break
            if texts:
                final_text = texts[-1]
            if resp.stop_reason != "tool_use" or not tool_uses:
                # It ended without calling a tool. If NOTHING has actually run yet
                # and either the request was actionable or the reply claims/promises
                # work, that's a hallucination — force it to act (or ask), never let
                # "Done." with no tool call be the final answer.
                reply_is_question = final_text.rstrip().endswith("?")
                _should = (not tool_uses and not tools_ran and nudges < 2 and not reply_is_question
                           and (_looks_actionable(text) or _claims_action(final_text)))
                if _should:
                    nudges += 1
                    messages.append({"role": "assistant", "content": resp.content})
                    messages.append({"role": "user", "content":
                        "STOP. You did NOT call any tool, so nothing actually happened — "
                        "the doc/task does not exist. Never claim you did something ('Done', "
                        "'Created', 'Here's your…') or that you're about to — you have real "
                        "tools, so CALL the tool now to actually do it, or ask one specific "
                        "clarifying question. Only answer once it's truly done, with the real "
                        "result from the tool."})
                    continue
                break

            tools_ran = True
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                action_name, node = TOOL_POLICY.get(tu.name, (None, "web"))
                if action_name is None:
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": "unknown tool", "is_error": True}
                    )
                    continue
                verdict = evaluate_tool_call(action_name, AutonomyMode.EXECUTE)
                if verdict.decision == PolicyDecision.DENY:
                    await bus.emit(
                        "core", "policy.denied", f"Policy denied {action_name}",
                        detail=verdict.reason, level="warn", goal_id=goal_id,
                    )
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": f"Denied by policy: {verdict.reason}", "is_error": True}
                    )
                    continue
                if verdict.decision == PolicyDecision.REQUIRE_APPROVAL:
                    await _queue_approval(goal_id, tu.name, dict(tu.input), verdict.risk.value)
                    await bus.set_orb("waiting", "Sonnet is waiting on your approval", ["assistant"])
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": "Queued for the user's approval banner. Do not retry; "
                                    "tell the user it is waiting on their approval."}
                    )
                    continue
                if tu.name == "plan_project":
                    if not executor.available():
                        results.append(
                            {"type": "tool_result", "tool_use_id": tu.id,
                             "content": "Planner unavailable: ANTHROPIC_API_KEY not configured.",
                             "is_error": True}
                        )
                        continue
                    try:
                        plan_result = await executor.plan_project(
                            goal_id, str(tu.input.get("objective", text))
                        )
                    except Exception as exc:
                        plan_result = {"error": f"Planner failed: {exc}. Do the steps"
                                       " yourself with your own tools instead."}
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": json.dumps(plan_result, default=str)[:2000]}
                    )
                    continue
                if not CONNECTOR_AVAILABLE.get(node, lambda: True)():
                    if node == "local":
                        msg = (
                            "Trav's laptop worker is OFFLINE, so this can't run right now. "
                            "Tell him his RESOLVE worker is down and give him this to turn it "
                            "back on — run in Terminal:\n\n"
                            f"    {WORKER_RESTART_CMD}\n\n"
                            "(or, if that doesn't work: `cd ~/claude/resolve/apps/local-worker "
                            "&& ./run.sh`). Once it's back, ask me again."
                        )
                    elif node == "web":
                        msg = ("The local model isn't reachable (LOCAL_MODEL_URL not set or the "
                               "box is offline). Answer it yourself instead.")
                    else:
                        msg = f"The {node} connector isn't configured on this deployment yet."
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": msg, "is_error": True}
                    )
                    await bus.emit(
                        node, "connector.unavailable", f"{node} not configured — {tu.name} skipped",
                        level="warn", goal_id=goal_id,
                    )
                    continue
                await bus.set_orb("executing", f"Sonnet is calling {tu.name}", ["assistant", node])
                started = time.monotonic()
                try:
                    result = await anyio.to_thread.run_sync(
                        lambda n=tu.name, inp=dict(tu.input): _connector_call(n, inp)
                    )
                    ms = int((time.monotonic() - started) * 1000)
                    await bus.emit(
                        "assistant", "tool.call",
                        f"{tu.name} — ok in {ms}ms",
                        detail=json.dumps(result, default=str)[:400],
                        edge={"from": "assistant", "to": node}, goal_id=goal_id,
                    )
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": json.dumps(result, default=str)[:4000]}
                    )
                except Exception as exc:
                    await bus.emit(
                        "assistant", "tool.error", f"{tu.name} failed: {exc}",
                        level="error", goal_id=goal_id,
                    )
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": f"Error: {exc}", "is_error": True}
                    )
            messages.append({"role": "user", "content": results})

        status = "waiting_approval" if pending_actions else "completed"
        # Honest fallback: only say "Done." if a tool actually ran. Otherwise don't
        # imply success — that was the source of the "Done." hallucination.
        if not final_text:
            final_text = "Done." if (tools_ran or pending_actions) else (
                "I couldn't complete that — nothing was created. Mind trying again?")
        history.append((text, final_text))
        await bus.emit(
            "assistant", "assistant.reply", final_text[:160],
            detail=final_text or None, level="success", goal_id=goal_id,
        )
        # always log a brief summary of the task to the vault (best-effort)
        try:
            await anyio.to_thread.run_sync(lambda: _log_task_summary(text, final_text))
        except Exception:
            pass
        try:
            await anyio.to_thread.run_sync(
                lambda: store.update(
                    "goals", {"id": f"eq.{goal_id}"},
                    {"status": status,
                     "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                )
            )
        except Exception:
            pass
        if pending_actions:
            await bus.set_orb("waiting", "Sonnet is waiting on your approval", ["assistant"])
        else:
            await bus.set_orb("idle", "Sonnet standing by", [])
    except asyncio.CancelledError:
        raise  # a 'stop' — let the processor handle it, no error reply
    except Exception as exc:
        log.exception("assistant loop failed")
        await bus.emit("core", "goal.failed", f"Assistant loop error: {exc}", level="error",
                       goal_id=goal_id)
        # give Trav an actual reply instead of a silent failure + idle orb
        await bus.emit("assistant", "assistant.reply",
                       "Something went wrong on my end and I couldn't finish that — try again?",
                       detail=f"error: {exc}", level="error", goal_id=goal_id)
        await bus.set_orb("idle", "Sonnet standing by", [])
        try:
            await anyio.to_thread.run_sync(
                lambda: store.update("goals", {"id": f"eq.{goal_id}"}, {"status": "failed"})
            )
        except Exception:
            pass
        await bus.set_orb("idle", "Sonnet standing by", [])
