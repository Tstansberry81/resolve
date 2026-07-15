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

import re

from . import bus, costs, store
from .connectors import local_llm, vault_github
from .msgutil import cached_system, compact_messages
from .domain import AutonomyMode
from .policy import PolicyDecision, evaluate_tool_call

log = logging.getLogger("resolve.executor")

# Planner stays on Sonnet so multi-step plans don't fall apart; the executor
# runs on Haiku for cost. All overridable via env — flip back if quality dips.
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "claude-sonnet-4-6")
EXECUTOR_MODEL = os.getenv("EXECUTOR_MODEL", "claude-haiku-4-5-20251001")
# kept modest to bound per-task cost (Opus + web search adds up fast)
MAX_STEP_TURNS = int(os.getenv("EXECUTOR_MAX_STEP_TURNS", "4"))

# Anthropic server-side web search — lets the executor research mid-step. Capped
# low so a research task can't quietly rack up a big bill.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search",
                   "max_uses": int(os.getenv("EXECUTOR_WEB_MAX_USES", "3"))}

queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
halted = False
_current_step_task: "asyncio.Task | None" = None  # the step running right now
# When True (and a local model is configured + reachable), executor steps run on
# Trav's local Qwen instead of Opus. The planner always stays on Opus. Toggled
# live from the dashboard; falls back to Opus if the local box is unreachable.
local_exec = False

PLANNER_SYSTEM = (
    "You are the RESOLVE Planner. Break the user's goal into the FEWEST sequential"
    " steps that actually get it done — prefer 1-3, never pad to look thorough, and"
    " use a SINGLE step whenever one executor turn can finish it. Every extra step"
    " costs a full model run, so merge anything that can be done together. The"
    " executor has ALL of these tools — use whichever fit:\n"
    "- Research/reading: web_search, search_products (shopping/product prices), get_calendar,"
    " get_tasks, get_unread_email, get_finance, vault_read, find_google_file\n"
    "- Saving output: save_to_vault (DEFAULT home for research/writeups — prefer this),"
    " create_google_doc / create_google_sheet / create_google_slides (use when the goal"
    " names a project or wants a Google file), vault_log (brief notes)\n"
    "- Editing: edit_google_doc / edit_google_sheet / add_google_slides\n"
    "- The laptop: run_on_laptop (files/shell/real web browsing), open_folder / open_app /"
    " open_website\n"
    "- Calendar/tasks: create_calendar_event, create_task\n"
    "Give each step a `say`: a 2-4 word present-tense spoken cue RESOLVE says aloud"
    " as it starts that step (e.g. 'researching resources', 'writing the doc',"
    " 'checking your calendar', 'wrapping up'). Natural and friendly, no jargon.\n"
    "Keep each step's instructions TERSE — one or two sentences of what to do, no"
    " preamble, no restating the goal. Web research is capped at a few searches total,"
    " so don't plan a step per query; one 'research X' step covers it. Do NOT plan"
    " steps that send email or delete things — those need Trav's approval and can't run"
    " inside an autonomous plan; leave them for him. Steps must be self-contained with no"
    " placeholders. When the goal produces real output, fold saving it into the final"
    " step (save_to_vault by default) rather than adding a separate save step. Call"
    " submit_plan exactly once."
)

# Static across every step + command → prompt-cached (tools + this preamble bill
# at 0.1x after the first turn). The per-step Goal/Step/Instructions ride in a
# separate uncached block so they don't bust the cache.
EXECUTOR_PREAMBLE = (
    "You are the RESOLVE executor. Complete exactly the one step you're given."
    " Give your FULL result as your final message — for research, that means the"
    " actual findings written out (not just a one-line summary). RESOLVE saves"
    " your output to Trav's vault automatically, so do NOT claim you saved it"
    " yourself and don't skip writing the real content. Be efficient: don't"
    " re-run searches or reads you've already done — use what's in the transcript."
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
                        "say": {"type": "string",
                                "description": "2-4 word spoken cue said aloud when this step starts"},
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
        model=PLANNER_MODEL, max_tokens=1500, system=cached_system(PLANNER_SYSTEM),
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
                         "say": str(step.get("say", "")).strip(),
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
        # The executor runs autonomously with no human in the loop mid-plan, so an
        # approval-gated action (send/delete) can't complete here. Return an ERROR
        # so the model doesn't fake success and downstream steps don't assume it
        # happened. These belong to the assistant (with Trav present), not a plan.
        return (f"'{name}' needs Trav's approval and CANNOT run inside an autonomous "
                "plan. Do not mark this done — skip it and note that Trav must do it "
                "himself.", True)
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


async def _execute_opus(item: dict[str, Any], context: str) -> str:
    """Anthropic tool-use loop on the executor model (default backend). The static
    preamble + tools are prompt-cached; ``context`` is the per-step detail."""
    from .assistant import TOOLS

    goal_id, title = item["goal_id"], item["title"]
    client = anthropic.AsyncAnthropic()
    system = cached_system(EXECUTOR_PREAMBLE, context)
    messages: list[dict[str, Any]] = [{"role": "user", "content": f"Execute the step now: {title}"}]
    outcome = ""
    for _ in range(MAX_STEP_TURNS):
        compact_messages(messages)  # trim stale tool_result blobs from the transcript
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
    # Spoken progress cue for the big steps — the dashboard narrates these aloud
    # while the plan runs in the background. Falls back to a short title phrase.
    cue = item.get("say") or " ".join(title.split()[:4])
    if cue:
        await bus.emit("assistant", "speak.progress", cue, goal_id=goal_id)

    context = (
        f"Goal: {item['objective']}\nStep: {title}\nInstructions: {item['instructions']}"
    )

    outcome = ""
    backend = "Opus"
    # Route to the local model when the toggle is on and it's configured; if the
    # box is unreachable, fall back to the executor model so the step still runs.
    if local_exec and local_llm.configured():
        try:
            outcome = await _execute_local(item, f"{EXECUTOR_PREAMBLE}\n{context}")
            backend = "local Qwen"
        except Exception as exc:
            await bus.emit("executor", "task.note",
                           f"Local model unreachable ({str(exc)[:80]}) — using cloud model",
                           level="warn", goal_id=goal_id)
    if backend != "local Qwen":
        outcome = await _execute_opus(item, context)

    # GUARANTEE the output lands in the vault — deterministic, not up to the LLM.
    saved_url = await anyio.to_thread.run_sync(lambda: _autosave_output(title, outcome))

    await _mark_task(item["task_id"], "succeeded")
    detail = outcome or None
    if saved_url:
        detail = f"{outcome}\n\nSaved to vault: {saved_url}"
    await bus.emit("executor", "task.completed", f"Done ({backend}): {title} — {outcome[:120]}",
                   detail=detail, level="success", goal_id=goal_id)


def _autosave_output(title: str, outcome: str) -> str | None:
    """Persist a step's output to the vault: a brief log line always, plus a full
    note when there's substantial content. Best-effort; never breaks the step."""
    if not vault_github.configured() or not (outcome or "").strip():
        return None
    brief = " ".join(outcome.split())[:200]
    try:
        vault_github.append_log(f"executor · {title[:60]}", [f"- {brief}"])
    except Exception:
        pass
    if len(outcome.strip()) <= 300:
        return None
    slug = (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]) or "research"
    path = f"wiki/output/{slug}.md"
    try:
        vault_github.write_file(path, f"# {title}\n\n{outcome.strip()}\n",
                                message=f"agent: save {title[:50]}")
        return f"https://github.com/{vault_github.VAULT_REPO}/blob/main/{path}"
    except Exception:
        return None


def is_working() -> bool:
    """A step is running now or steps are waiting — used so 'stop' knows the
    executor is busy even after the assistant handed off and returned."""
    return _current_step_task is not None or not queue.empty()


async def drain_queue() -> int:
    """Drop every pending step so they never run (used by stop)."""
    dropped = 0
    while not queue.empty():
        try:
            item = queue.get_nowait()
            queue.task_done()
            dropped += 1
            await _mark_task(item.get("task_id", ""), "cancelled")
        except asyncio.QueueEmpty:
            break
    return dropped


async def stop_current() -> dict[str, Any]:
    """Hard-stop the executor: cancel the running step AND drop the rest. This is
    what makes 'stop' actually stop mid-research instead of finishing the step."""
    global _current_step_task
    cancelled_running = False
    t = _current_step_task
    if t and not t.done():
        t.cancel()
        cancelled_running = True
    dropped = await drain_queue()
    await bus.set_orb("idle", "Stopped", [])
    return {"cancelledRunning": cancelled_running, "droppedSteps": dropped}


async def worker_loop() -> None:
    """Single in-process worker: one step at a time, halt flag between steps."""
    global _current_step_task
    log.info("executor worker loop started")
    any_failed = False  # did any step in the current drain fail? resets when empty
    while True:
        item = await queue.get()
        if halted:
            await _mark_task(item["task_id"], "cancelled")
            await bus.emit("executor", "task.cancelled",
                           f"Halted — dropped: {item['title']}", level="warn",
                           goal_id=item["goal_id"])
            continue
        completed_ok = False
        try:
            # run the step as a cancellable task so 'stop' can kill it mid-flight
            _current_step_task = asyncio.create_task(_run_step(item))
            await _current_step_task
            completed_ok = True
        except asyncio.CancelledError:
            await _mark_task(item["task_id"], "cancelled")
            await bus.emit("executor", "task.cancelled",
                           f"Stopped: {item['title']}", level="warn",
                           goal_id=item["goal_id"])
        except Exception as exc:
            any_failed = True
            log.exception("executor step failed")
            await _mark_task(item["task_id"], "failed")
            await bus.emit("executor", "task.failed", f"{item['title']} failed: {exc}",
                           level="error", goal_id=item["goal_id"])
        finally:
            _current_step_task = None
        if queue.empty():
            await bus.set_orb("idle", "Sonnet standing by", [])
            # spoken sign-off once the whole plan is done — honest about failures
            if completed_ok:
                msg = "Done — though a step ran into trouble." if any_failed else "All wrapped up."
                await bus.emit("assistant", "speak.progress", msg,
                               goal_id=item.get("goal_id"))
            any_failed = False  # reset for the next batch
