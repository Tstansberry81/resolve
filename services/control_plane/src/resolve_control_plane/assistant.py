"""The assistant loop — Sonnet fronts every command (docs/DIRECTION.md).

Each tool call passes through the policy engine: reads and reversible writes
execute immediately; communication sends and destructive actions create a
pending approval (dashboard banner) and only execute on your decision."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import anthropic
import anyio

from . import bus, costs, executor, store
from .connectors import gcal, gmail_imap, local_llm, notion_api, simplefin, vault_github
from .domain import AutonomyMode
from .policy import PolicyDecision, evaluate_tool_call
from .tools_def import SYSTEM, TOOL_POLICY, TOOLS

log = logging.getLogger("resolve.assistant")

ASSISTANT_MODEL = os.getenv("ASSISTANT_MODEL", "claude-sonnet-4-6")
MAX_TURNS = 6

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
        return local_llm.chat(str(args["prompt"]))
    if name == "get_finance":
        s = simplefin.summary(int(args.get("days", 30)))
        # trim the transaction list for the model — it just needs the shape
        return {**s, "transactions": s.get("transactions", [])[:15]}
    if name == "run_on_laptop":
        from . import local
        return local.enqueue(str(args["task"]))
    raise ValueError(f"unknown tool {name}")


CONNECTOR_AVAILABLE = {
    "calendar": gcal.configured,
    "notion": notion_api.configured,
    "gmail": gmail_imap.configured,
    "vault": vault_github.configured,
    "web": local_llm.configured,  # the "web" dot doubles as the local-AI lane
    "finance": simplefin.configured,
    "local": lambda: __import__("resolve_control_plane.local", fromlist=["online"]).online(),
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


async def run_command(text: str) -> str:
    """Run one assistant command; returns the goal id. Emits everything via the bus."""
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

    asyncio.get_running_loop().create_task(_loop(goal_id, text))
    return goal_id


async def _loop(goal_id: str, text: str) -> None:
    client = anthropic.AsyncAnthropic()
    await bus.set_orb("listening", "Sonnet heard you — parsing the request", ["assistant"])
    await bus.emit(
        "assistant", "goal.accepted", f"Goal accepted: {text[:120]}",
        detail=f"model: {ASSISTANT_MODEL} · autonomy: execute", goal_id=goal_id,
    )
    await bus.set_orb("thinking", "Sonnet is working your request", ["assistant"])

    now = datetime.now(ZoneInfo("America/New_York"))
    system = SYSTEM + (
        f"\n\nRight now it is {now.strftime('%A, %B %d, %Y at %I:%M %p')} Eastern."
        " Resolve every relative date (tomorrow, Sunday, next week) from this —"
        " never guess weekdays. 'Tomorrow' always means the next calendar date,"
        " even between midnight and dawn."
    )
    messages: list[dict[str, Any]] = []
    for prior_user, prior_reply in history:
        messages.append({"role": "user", "content": prior_user})
        messages.append({"role": "assistant", "content": prior_reply})
    messages.append({"role": "user", "content": text})
    final_text = ""
    try:
        for _ in range(MAX_TURNS):
            resp = await client.messages.create(
                model=ASSISTANT_MODEL,
                max_tokens=1500,
                system=system,
                tools=TOOLS,
                messages=messages,
            )
            costs.record("assistant", ASSISTANT_MODEL, resp.usage)
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            texts = [b.text for b in resp.content if b.type == "text"]
            if texts:
                final_text = texts[-1]
            if resp.stop_reason != "tool_use" or not tool_uses:
                break

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
                if not CONNECTOR_AVAILABLE[node]():
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id,
                         "content": f"The {node} connector isn't configured on this deployment yet.",
                         "is_error": True}
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
                        lambda: _connector_call(tu.name, dict(tu.input))
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
        history.append((text, final_text or "Done."))
        await bus.emit(
            "assistant", "assistant.reply", final_text[:160] or "Done.",
            detail=final_text or None, level="success", goal_id=goal_id,
        )
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
    except Exception as exc:
        log.exception("assistant loop failed")
        await bus.emit("core", "goal.failed", f"Assistant loop error: {exc}", level="error",
                       goal_id=goal_id)
        try:
            await anyio.to_thread.run_sync(
                lambda: store.update("goals", {"id": f"eq.{goal_id}"}, {"status": "failed"})
            )
        except Exception:
            pass
        await bus.set_orb("idle", "Sonnet standing by", [])
