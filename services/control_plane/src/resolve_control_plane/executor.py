"""Worker phase: the Planner (Opus 4.8) plans, the Opus executor works the queue.

Sonnet hands complex goals off via her plan_project tool. The Planner
(claude-opus-4-8, on Anthropic) writes a short step list; steps persist to the
tasks table and an in-process executor coroutine works them one at a time with
claude-opus-4-8 under the same policy engine as the assistant. The executor can
also research the web (Anthropic server-side web search) mid-step. The /v1/stop
flag halts the worker between steps — that is the emergency stop's backend teeth.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import anthropic
import anyio

from . import bus, costs, store
from .domain import AutonomyMode
from .policy import PolicyDecision, evaluate_tool_call

log = logging.getLogger("resolve.executor")

PLANNER_MODEL = os.getenv("PLANNER_MODEL", "claude-opus-4-8")
EXECUTOR_MODEL = os.getenv("EXECUTOR_MODEL", "claude-opus-4-8")
MAX_STEP_TURNS = 6

# Anthropic server-side web search — lets the executor research mid-step.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
halted = False

PLANNER_SYSTEM = (
    "You are the RESOLVE Planner (Opus). Break the user's goal into 2-6 concrete,"
    " sequential steps the executor can do with these tools: get_calendar,"
    " create_calendar_event, get_tasks, create_task, get_unread_email, send_email,"
    " vault_log, and web_search (for research). Steps must be self-contained with"
    " no placeholders. Call submit_plan exactly once with your step list."
)

PLAN_TOOL = {
    "name": "submit_plan",
    "description": "Record the ordered plan for the executor.",
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "instructions": {"type": "string"},
                    },
                    "required": ["title", "instructions"],
                },
            }
        },
        "required": ["steps"],
    },
}


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


async def set_halted(value: bool) -> None:
    global halted
    halted = value
    if value:
        await bus.emit("core", "system.emergency_stop",
                       "Emergency stop — executor halted between steps", level="error")
        await bus.set_orb("idle", "EMERGENCY STOP — executor halted", [])
    else:
        await bus.emit("core", "system.resumed", "Executor re-enabled", level="success")


async def plan_project(goal_id: str, objective: str) -> dict[str, Any]:
    """Sonnet's plan_project tool body: the Planner (Opus) plans, steps queue."""
    await bus.emit("assistant", "handoff.planner", f"Sonnet → Planner: {objective[:110]}",
                   edge={"from": "assistant", "to": "planner"}, goal_id=goal_id)
    await bus.set_orb("thinking", "Planner (Opus) is designing the plan", ["assistant", "planner"])

    client = anthropic.AsyncAnthropic()
    resp = await client.messages.create(
        model=PLANNER_MODEL, max_tokens=1500, system=PLANNER_SYSTEM,
        tools=[PLAN_TOOL], tool_choice={"type": "tool", "name": "submit_plan"},
        messages=[{"role": "user", "content": objective}],
    )
    costs.record("planner", PLANNER_MODEL, resp.usage)
    plan = next((b.input for b in resp.content if b.type == "tool_use"), {}) or {}
    steps = (plan.get("steps") or [])[:6]
    if not steps:
        return {"error": "Planner returned no steps"}

    titles = [s.get("title", "step") for s in steps]
    await bus.emit("planner", "plan.ready", f"Planner set {len(steps)} steps: " + "; ".join(titles)[:140],
                   detail=json.dumps(steps)[:400],
                   edge={"from": "planner", "to": "executor"}, goal_id=goal_id)

    for i, step in enumerate(steps):
        row = {
            "title": str(step.get("title", f"step {i + 1}"))[:200],
            "kind": "executor_step",
            "status": "ready",
            "model_role": "executor",
            "input_json": {"instructions": step.get("instructions", ""), "objective": objective},
            "priority": i,
        }
        if len(goal_id) == 36:
            row["goal_id"] = goal_id
        try:
            saved = await anyio.to_thread.run_sync(lambda r=row: store.insert("tasks", r))
            task_id = str(saved.get("id", ""))
        except Exception:
            task_id = ""
        await queue.put({"goal_id": goal_id, "task_id": task_id,
                         "title": row["title"],
                         "instructions": step.get("instructions", ""),
                         "objective": objective})
    return {"queued": len(steps), "steps": titles}


async def _mark_task(task_id: str, status: str) -> None:
    if not task_id:
        return
    try:
        await anyio.to_thread.run_sync(
            lambda: store.update("tasks", {"id": f"eq.{task_id}"}, {"status": status})
        )
    except Exception:
        pass


async def _run_step(item: dict[str, Any]) -> None:
    from .assistant import (CONNECTOR_AVAILABLE, TOOL_POLICY, TOOLS,
                            _connector_call, _queue_approval)

    goal_id, title = item["goal_id"], item["title"]
    await _mark_task(item["task_id"], "running")
    await bus.set_orb("executing", f"Executor working: {title}", ["executor"])
    await bus.emit("executor", "task.started", f"Executor picked up: {title}",
                   goal_id=goal_id)

    client = anthropic.AsyncAnthropic()
    system = (
        "You are the RESOLVE executor (Opus). Complete exactly this step of a larger"
        f" plan, then summarize the outcome in one sentence.\nGoal: {item['objective']}\n"
        f"Step: {title}\nInstructions: {item['instructions']}"
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": f"Execute the step now: {title}"}]
    outcome = ""
    for _ in range(MAX_STEP_TURNS):
        resp = await client.messages.create(
            model=EXECUTOR_MODEL, max_tokens=1500, system=system,
            tools=TOOLS + [WEB_SEARCH_TOOL], messages=messages,
        )
        costs.record("executor", EXECUTOR_MODEL, resp.usage)
        texts = [b.text for b in resp.content if b.type == "text"]
        if texts:
            outcome = texts[-1]
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        # pause_turn: server-side web search hit its loop cap; resend to resume.
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        if resp.stop_reason != "tool_use" or not tool_uses:
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for tu in tool_uses:
            action_name, node = TOOL_POLICY.get(tu.name, (None, "web"))
            if action_name is None:
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": "unknown tool", "is_error": True})
                continue
            verdict = evaluate_tool_call(action_name, AutonomyMode.EXECUTE)
            if verdict.decision == PolicyDecision.DENY:
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": f"Denied by policy: {verdict.reason}", "is_error": True})
                continue
            if verdict.decision == PolicyDecision.REQUIRE_APPROVAL:
                await _queue_approval(goal_id, tu.name, dict(tu.input), verdict.risk.value)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": "Queued for the user's approval banner; do not retry."})
                continue
            if not CONNECTOR_AVAILABLE[node]():
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": f"The {node} connector isn't configured.", "is_error": True})
                continue
            started = time.monotonic()
            try:
                result = await anyio.to_thread.run_sync(
                    lambda: _connector_call(tu.name, dict(tu.input))
                )
                ms = int((time.monotonic() - started) * 1000)
                await bus.emit("executor", "tool.call", f"{tu.name} — ok in {ms}ms",
                               detail=json.dumps(result, default=str)[:400],
                               edge={"from": "executor", "to": node}, goal_id=goal_id)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": json.dumps(result, default=str)[:4000]})
            except Exception as exc:
                await bus.emit("executor", "tool.error", f"{tu.name} failed: {exc}",
                               level="error", goal_id=goal_id)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": f"Error: {exc}", "is_error": True})
        messages.append({"role": "user", "content": results})

    await _mark_task(item["task_id"], "succeeded")
    await bus.emit("executor", "task.completed", f"Done: {title} — {outcome[:120]}",
                   detail=outcome or None, level="success", goal_id=goal_id)


async def worker_loop() -> None:
    """Single in-process worker: one step at a time, halt flag between steps."""
    log.info("executor worker loop started")
    while True:
        item = await queue.get()
        if halted:
            await _mark_task(item["task_id"], "cancelled")
            await bus.emit("executor", "task.cancelled",
                           f"Halted — dropped: {item['title']}", level="warn",
                           goal_id=item["goal_id"])
            continue
        try:
            await _run_step(item)
        except Exception as exc:
            log.exception("executor step failed")
            await _mark_task(item["task_id"], "failed")
            await bus.emit("executor", "task.failed", f"{item['title']} failed: {exc}",
                           level="error", goal_id=item["goal_id"])
        if queue.empty():
            await bus.set_orb("idle", "Sonnet standing by", [])
