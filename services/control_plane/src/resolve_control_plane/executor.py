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
from .connectors import local_llm
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
# When True (and a local model is configured + reachable), executor steps run on
# Trav's local Qwen instead of Opus. The planner always stays on Opus. Toggled
# live from the dashboard; falls back to Opus if the local box is unreachable.
local_exec = False

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


async def set_local_exec(value: bool) -> None:
    global local_exec
    local_exec = bool(value)
    where = "local Qwen" if local_exec else "Opus"
    await bus.emit("core", "system.exec_backend", f"Executor now runs on {where}",
                   level="info")


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


async def _dispatch_tool(name: str, args: dict[str, Any], goal_id: str) -> tuple[str, bool]:
    """Shared policy + connector execution for both executor backends (Opus and
    local Qwen). Returns (content_str, is_error)."""
    from .assistant import CONNECTOR_AVAILABLE, TOOL_POLICY, _connector_call, _queue_approval

    action_name, node = TOOL_POLICY.get(name, (None, "web"))
    if action_name is None:
        return "unknown tool", True
    verdict = evaluate_tool_call(action_name, AutonomyMode.EXECUTE)
    if verdict.decision == PolicyDecision.DENY:
        return f"Denied by policy: {verdict.reason}", True
    if verdict.decision == PolicyDecision.REQUIRE_APPROVAL:
        await _queue_approval(goal_id, name, dict(args), verdict.risk.value)
        return "Queued for the user's approval banner; do not retry.", False
    if not CONNECTOR_AVAILABLE[node]():
        return f"The {node} connector isn't configured.", True
    started = time.monotonic()
    try:
        result = await anyio.to_thread.run_sync(lambda: _connector_call(name, dict(args)))
        ms = int((time.monotonic() - started) * 1000)
        await bus.emit("executor", "tool.call", f"{name} — ok in {ms}ms",
                       detail=json.dumps(result, default=str)[:400],
                       edge={"from": "executor", "to": node}, goal_id=goal_id)
        return json.dumps(result, default=str)[:4000], False
    except Exception as exc:
        await bus.emit("executor", "tool.error", f"{name} failed: {exc}",
                       level="error", goal_id=goal_id)
        return f"Error: {exc}", True


async def _execute_opus(item: dict[str, Any], system: str) -> str:
    """Anthropic tool-use loop on claude-opus-4-8 (default executor backend)."""
    from .assistant import TOOLS

    goal_id, title = item["goal_id"], item["title"]
    client = anthropic.AsyncAnthropic()
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
            content, is_err = await _dispatch_tool(tu.name, dict(tu.input), goal_id)
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": content, "is_error": is_err})
        messages.append({"role": "user", "content": results})
    return outcome


def _openai_tools() -> list[dict[str, Any]]:
    """Translate the Anthropic tool schema into OpenAI function-tool schema."""
    from .assistant import TOOLS

    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t.get("description", ""),
                      "parameters": t["input_schema"]}}
        for t in TOOLS
    ]


async def _execute_local(item: dict[str, Any], system: str) -> str:
    """OpenAI-compatible tool-calling loop against the local model (Qwen via the
    Cloudflare tunnel). No Anthropic server web-search here — that's Opus-only.
    Raises on connection failure so _run_step can fall back to Opus."""
    from openai import AsyncOpenAI

    goal_id, title = item["goal_id"], item["title"]
    base = os.environ["LOCAL_MODEL_URL"].rstrip("/")
    model = os.getenv("LOCAL_MODEL_NAME", "qwen2.5:32b")
    client = AsyncOpenAI(base_url=base, api_key=os.getenv("LOCAL_MODEL_KEY") or "local")
    tools = _openai_tools()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Execute the step now: {title}"},
    ]
    outcome = ""
    for _ in range(MAX_STEP_TURNS):
        resp = await client.chat.completions.create(
            model=model, messages=messages, tools=tools, max_tokens=1500,
        )
        msg = resp.choices[0].message
        if msg.content:
            outcome = msg.content
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            break
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            content, _err = await _dispatch_tool(tc.function.name, args, goal_id)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    return outcome


async def _run_step(item: dict[str, Any]) -> None:
    goal_id, title = item["goal_id"], item["title"]
    await _mark_task(item["task_id"], "running")
    await bus.set_orb("executing", f"Executor working: {title}", ["executor"])
    await bus.emit("executor", "task.started", f"Executor picked up: {title}",
                   goal_id=goal_id)

    system = (
        "You are the RESOLVE executor. Complete exactly this step of a larger"
        f" plan, then summarize the outcome in one sentence.\nGoal: {item['objective']}\n"
        f"Step: {title}\nInstructions: {item['instructions']}"
    )

    outcome = ""
    backend = "Opus"
    # Route to the local model when the toggle is on and it's configured; if the
    # box is unreachable, fall back to Opus so the step still gets done.
    if local_exec and local_llm.configured():
        try:
            outcome = await _execute_local(item, system)
            backend = "local Qwen"
        except Exception as exc:
            await bus.emit("executor", "task.note",
                           f"Local model unreachable ({str(exc)[:80]}) — using Opus",
                           level="warn", goal_id=goal_id)
    if backend != "local Qwen":
        outcome = await _execute_opus(item, system)

    await _mark_task(item["task_id"], "succeeded")
    await bus.emit("executor", "task.completed", f"Done ({backend}): {title} — {outcome[:120]}",
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
