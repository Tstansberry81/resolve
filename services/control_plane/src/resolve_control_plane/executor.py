"""Worker phase: the Planner plans, the executor works the queue.

Sonnet hands complex goals off via her plan_project tool. The Planner
(PLANNER_MODEL, on Anthropic) writes a short step list; steps persist to the
tasks table and an in-process executor coroutine works them one at a time with
EXECUTOR_MODEL under the same policy engine as the assistant. The executor can
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

from . import artifacts, bus, costs, store
from .connectors import local_llm, vault_github
from .msgutil import cached_system, compact_messages
from .domain import AutonomyMode
from .policy import PolicyDecision, evaluate_tool_call

log = logging.getLogger("resolve.executor")

# Planner on Opus 5 (per Trav), executor on Sonnet 5. The executor ran on Haiku
# for cost and it did not hold up: the narrate-instead-of-deliver stalls, the
# "let me compile this" tails, and the truncated-mid-tool-call turn that 400'd
# the McIntire plan all came from the cheap tier failing at plain research. A
# step that costs less but doesn't happen isn't cheaper.
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "claude-opus-5")
EXECUTOR_MODEL = os.getenv("EXECUTOR_MODEL", "claude-sonnet-5")
# kept modest to bound per-task cost (Opus + web search adds up fast)
MAX_STEP_TURNS = int(os.getenv("EXECUTOR_MAX_STEP_TURNS", "4"))
# A full research writeup does not fit in 2500 output tokens. Truncation isn't
# just a short answer: a turn cut off mid-tool_use used to poison the transcript
# and 400 the step, so the cap is real reliability surface, not only quality.
# Raised again for Sonnet 5, where adaptive thinking is on by default and shares
# this budget with the answer — the old ceiling is now thinking + text.
MAX_STEP_TOKENS = int(os.getenv("EXECUTOR_MAX_STEP_TOKENS", "8000"))

# Anthropic server-side web search — lets the executor research mid-step. Capped
# low so a research task can't quietly rack up a big bill. allowed_callers pins
# the tool to DIRECT invocation: the Haiku-tier models (planner/executor) don't
# support programmatic tool calling, and web_search now defaults to requiring it
# unless we say otherwise — without this, every research step 400s.
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search",
                   "allowed_callers": ["direct"],
                   "max_uses": int(os.getenv("EXECUTOR_WEB_MAX_USES", "3"))}

queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
halted = False
_current_step_task: "asyncio.Task | None" = None  # the step running right now

# Per-goal accumulator of completed step outputs, so a later step (e.g. a
# synthesis/'build the plan' step) can SEE what earlier steps found — steps run
# in isolated model contexts otherwise, which is why synthesis steps stalled
# with "research was gathered but I need to locate it". Capped + cleared per goal.
_step_outputs: dict[str, list[dict[str, str]]] = {}
_PRIOR_CHARS_CAP = 9000  # keep prior-step context bounded


def _prior_context(goal_id: str) -> str:
    prior = _step_outputs.get(goal_id) or []
    if not prior:
        return ""
    blocks, used = [], 0
    for p in prior:  # oldest→newest; trim if the running total gets large
        chunk = f"### {p['title']}\n{p['outcome']}".strip()
        if used + len(chunk) > _PRIOR_CHARS_CAP:
            chunk = chunk[: max(0, _PRIOR_CHARS_CAP - used)]
        blocks.append(chunk)
        used += len(chunk)
        if used >= _PRIOR_CHARS_CAP:
            break
    return ("\n\nRESULTS FROM EARLIER STEPS OF THIS SAME PLAN (use these — do NOT "
            "re-research or go looking for files; the content is right here):\n\n"
            + "\n\n".join(blocks))
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
    "WHEN TRAV SAYS 'LOCAL' / 'LOCALLY' / 'ON MY COMPUTER' / 'ON MY MACHINE' /"
    " 'on my laptop', he means his actual Mac — plan the step to use run_on_laptop"
    " and have the laptop agent WRITE THE FILE on disk (his workspace folder), then"
    " open_folder or reveal_in_finder so he can see it. Do NOT substitute"
    " save_to_vault (that's a GitHub repo, not his machine) or a Google Doc. If he"
    " wants it in both places, say so in the step explicitly.\n"
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


def model_label(model_id: str) -> str:
    """Friendly name for a model id ('claude-opus-5' → 'Opus 5'), so every caption
    reports the model that ACTUALLY runs. Captions used to be hardcoded — the UI
    said Sonnet/Opus while the code ran Haiku, which is how a whole tier swap went
    unnoticed. Derive the label, never type it."""
    m = (model_id or "").lower()
    for family in ("opus", "sonnet", "haiku", "fable"):
        if family in m:
            # trailing version: claude-opus-5 → "5", claude-sonnet-4-6 → "4.6".
            # Stop at the first long run of digits — that's a dated snapshot
            # (claude-haiku-4-5-20251001), not another version segment.
            tail = m.split(family, 1)[1].strip("-")
            parts: list[str] = []
            for p in tail.split("-"):
                if not p.isdigit() or len(p) > 2:
                    break
                parts.append(p)
            return f"{family.capitalize()} {'.'.join(parts)}".strip()
    return model_id or "model"


# Public roster of what each role actually runs — the dashboard reads this via
# /v1/snapshot instead of hardcoding model names in the frontend roster.
def model_roster() -> dict[str, str]:
    """Every constellation node's live model. Must cover all five ids in the
    dashboard roster (assistant/planner/executor/coder/reviewer) — a role missing
    here silently falls back to the hardcoded string in lib/roster.ts, which is
    how the UI once claimed Haiku while the backend ran Sonnet. Coder and reviewer
    were missing until 2026-08-10 and had been showing fallbacks the whole time.
    """
    from .assistant import ASSISTANT_MODEL
    from .coder import architect_model, reviewer_model

    return {"assistant": ASSISTANT_MODEL, "planner": PLANNER_MODEL,
            "executor": "local Qwen" if local_exec else EXECUTOR_MODEL,
            "coder": architect_model(), "reviewer": reviewer_model()}


def _cloud_label() -> str:
    """Friendly name for the current cloud executor model."""
    return model_label(EXECUTOR_MODEL)


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


async def set_local_exec(value: bool) -> None:
    global local_exec
    local_exec = bool(value)
    where = "local Qwen" if local_exec else _cloud_label()
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
    await bus.set_orb("thinking", f"Planner ({model_label(PLANNER_MODEL)}) is designing the plan",
                      ["assistant", "planner"])

    client = anthropic.AsyncAnthropic()
    resp = await client.messages.create(
        # 1500 was sized for a no-thinking model. Opus 5 thinks by default and
        # max_tokens covers thinking + the submit_plan call, so a tight cap here
        # truncates the plan mid-tool_use — the exact shape that killed a step.
        model=PLANNER_MODEL, max_tokens=4000, system=cached_system(PLANNER_SYSTEM),
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
    from .assistant import CONNECTOR_AVAILABLE, TOOL_POLICY, _connector_call

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


# Opening narration that PROMISES work instead of delivering it. The lead-in
# must be a first-person promise ("I'll research…", "let me compile…"), NOT a
# bare filler word: "Sure, the balance is $12", "Okay, your flight is at 6:40",
# and "I can confirm the meeting is set" are real concise answers, not stalls —
# a bare "sure"/"okay"/"i can" must never match, or we discard good output.
_INTENT_LEAD = (
    r"(?:i'?ll|i will|i'?m going to|i am going to|let me|"
    r"first,?\s+i(?:'?ll| will)?|here'?s what i'?ll|"
    r"i'?d be happy to|i'?m happy to|i can help|i'?m about to)"
)
_INTENT_VERB = (
    r"(?:research|find|search|look|check|compile|summar\w*|write|draft|create|"
    r"put together|gather|locate|prepare|organize|provide|give|pull|read|do|"
    r"answer|get|start|dig|explore|review)"
)
_INTENT_RE = re.compile(
    r"^\s*(?:(?:sure|okay|ok|alright|great|perfect|got it)[,!.\s]+)?"
    + _INTENT_LEAD + r"\s+" + _INTENT_VERB,
    re.IGNORECASE)
# A trailing PROMISE to still-do-the-work: the model searched, narrated, then
# ended on "let me compile/write/summarize/save…" without producing the result.
# The promise is always FIRST-PERSON ("let me", "I'll", "I'm going to") — a bare
# "going to" also matched third-person prose like "the board is going to review
# the hours", wrongly discarding a real writeup, so it's now subject-bound.
_PROMISE_TAIL_RE = re.compile(
    r"(let me|i'?ll|i will|now i'?ll|i'?m going to|we'?re going to|i need to|"
    r"i should|first i)\s+"
    r"(compile|summar|write|put together|create|draft|save|provide|give|lay out|"
    r"organize|prepare|check|look|locate|find|gather|review|search|pull|read|start)"
    r"\S*[^.!?]*[.!?:]?\s*$", re.IGNORECASE)
# Same markers, anywhere in the text — used to tell a delivered writeup that
# happens to end on a forward-looking line from wall-to-wall narration.
_PROMISE_MARKER_RE = re.compile(
    r"\b(let me|i'?ll|i will|i'?m going to|i am going to|i need to|i should)\b",
    re.IGNORECASE)
# Content ahead of a trailing promise past this length counts as a real delivery.
_DELIVERED_MIN = 600
_TAIL_WINDOW = 200


def _needs_action(text: str) -> bool:
    """True when `text` is a promise to act rather than the actual result — the
    'I'll research…' / 'let me compile this now' stall. Empty counts too."""
    t = (text or "").strip()
    if not t:
        return True
    if len(t) < 240 and _INTENT_RE.match(t):
        return True
    match = _PROMISE_TAIL_RE.search(t[-_TAIL_WINDOW:])
    if not match:
        return False
    # It ENDS on a promise — but a finished 2000-word report that signs off with
    # "I'll save this to your vault" is a real delivery, and discarding it is the
    # same bug as flagging a concise answer. Judge by what came BEFORE the promise.
    body = t[: max(0, len(t) - _TAIL_WINDOW) + match.start()].strip()
    if len(body) < _DELIVERED_MIN:
        return True  # nothing but narration ahead of the promise → a real stall
    # A long body that is itself wall-to-wall "I'll…/let me…" is still narration.
    return len(_PROMISE_MARKER_RE.findall(body)) >= 3


# back-compat alias
_looks_like_intent = _needs_action


async def _execute_opus(item: dict[str, Any], context: str) -> str:
    """Anthropic tool-use loop on the executor model (default backend). The static
    preamble + tools are prompt-cached; ``context`` is the per-step detail."""
    from .assistant import TOOLS

    goal_id, title = item["goal_id"], item["title"]
    client = anthropic.AsyncAnthropic()
    system = cached_system(EXECUTOR_PREAMBLE, context)
    messages: list[dict[str, Any]] = [{"role": "user", "content": f"Execute the step now: {title}"}]
    outcome = ""
    nudges = 0
    for _ in range(MAX_STEP_TURNS + 3):  # headroom for search turns + a compile turn
        compact_messages(messages)  # trim stale tool_result blobs from the transcript
        resp = await client.messages.create(
            model=EXECUTOR_MODEL, max_tokens=MAX_STEP_TOKENS, system=system,
            tools=TOOLS + [WEB_SEARCH_TOOL], messages=messages,
        )
        costs.record("executor", EXECUTOR_MODEL, resp.usage)
        # This turn's text (server web_search interleaves several text blocks with
        # citations within ONE response, so join them all — texts[-1] alone lost
        # the body). Keep the last SUBSTANTIVE turn as the outcome.
        texts = [b.text for b in resp.content if b.type == "text" and b.text.strip()]
        turn_text = "\n".join(texts).strip()
        if turn_text:
            outcome = turn_text
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        # pause_turn: server-side web search hit its loop cap; resend to resume.
        # Only safe to bounce straight back when the turn carries no client tool
        # calls — otherwise it falls through and gets answered properly below.
        if resp.stop_reason == "pause_turn" and not tool_uses:
            messages.append({"role": "assistant", "content": resp.content})
            continue
        if tool_uses:
            # EVERY assistant turn carrying tool_use must be followed by a
            # tool_result for each id, no matter what stop_reason says. Keying
            # off stop_reason == "tool_use" alone meant a max_tokens truncation
            # mid-call fell into the nudge path, which appended a plain user
            # message after the dangling tool_use — the API rejects the next
            # request with "tool_use ids were found without tool_result blocks"
            # and the whole step dies. That 400 killed the McIntire plan.
            messages.append({"role": "assistant", "content": resp.content})
            truncated = resp.stop_reason == "max_tokens"
            results = []
            for tu in tool_uses:
                if truncated:
                    # the block was cut off, so its input JSON can't be trusted
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": "Not executed — your previous turn was cut "
                                               "off mid-call. Answer without it, or call it "
                                               "again more briefly.",
                                    "is_error": True})
                    continue
                content, is_err = await _dispatch_tool(tu.name, dict(tu.input), goal_id)
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": content, "is_error": is_err})
            messages.append({"role": "user", "content": results})
            continue
        # No tool calls — the model stopped. If what it produced is a PROMISE
        # ("I'll research…" / "let me compile this now") rather than the actual
        # result — the #1 reliability failure — force it to deliver.
        if nudges < 3 and _needs_action(outcome):
            nudges += 1
            # an empty content list is itself a 400; keep the turn well-formed
            messages.append({"role": "assistant",
                             "content": resp.content or [{"type": "text", "text": "…"}]})
            messages.append({"role": "user", "content": (
                "You have NOT delivered the result — you only said what you'd do. "
                "Write the COMPLETE answer/findings right now as your final message, "
                "in full, using what you already found. Do not describe your plan, "
                "do not say 'let me' — just output the finished content.")})
            continue
        break
    # If it never delivered (still a bare promise), return empty → honest failure.
    return "" if _needs_action(outcome) else outcome


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
    # Same honesty guard as the cloud path: if Qwen only narrated intent ("let me
    # compile…") instead of delivering, return empty so _run_step fails honestly
    # rather than saving a bare promise to the vault as if it were a real result.
    return "" if _needs_action(outcome) else outcome


async def _run_step(item: dict[str, Any]) -> bool:
    """Run one step. Returns True when it produced real output, False on an honest
    failure (empty/narration-only) so the worker loop can flag the plan as having
    a failed step even though this path returns normally rather than raising."""
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
        + _prior_context(goal_id)  # feed earlier steps' findings into this one
    )

    outcome = ""
    backend = _cloud_label()
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

    # HONESTY: if the step produced nothing real (model narrated intent then
    # stalled, or errored out empty), don't report a cheerful "Done" — say it
    # plainly so Trav knows to retry, and mark the task failed.
    if not (outcome or "").strip():
        await _mark_task(item["task_id"], "failed")
        await bus.emit("executor", "task.failed",
                       f"{title} — the executor didn't produce a result (no research/output). "
                       "Try asking again.", level="error", goal_id=goal_id)
        # and put it in the dock, so "nothing there" is never ambiguous
        try:
            await anyio.to_thread.run_sync(
                lambda: artifacts.record_failure(
                    title, "no output produced", goal_id=goal_id))
        except Exception:
            pass
        return False

    # Make this step's output available to later steps of the same plan.
    _step_outputs.setdefault(goal_id, []).append({"title": title, "outcome": outcome})
    while len(_step_outputs) > 6:  # bound memory: keep only recent goals' contexts
        # evict oldest-inserted, but never the goal we're mid-plan on — its key was
        # inserted at step 1, so plain insertion order can drop it under its own feet
        stale = next((k for k in _step_outputs if k != goal_id), None)
        if stale is None:
            break
        _step_outputs.pop(stale, None)

    # GUARANTEE the output lands in the vault — deterministic, not up to the LLM.
    saved_url, save_err = await anyio.to_thread.run_sync(
        lambda: _autosave_output(title, outcome, goal_id, item.get('objective', '')))
    if save_err:  # surface a real save failure instead of silently "succeeding"
        await bus.emit("executor", "task.note", f"⚠ Couldn't save the output: {save_err}",
                       level="error", goal_id=goal_id)
        # the dock must not stay silent about a file that doesn't exist
        try:
            await anyio.to_thread.run_sync(
                lambda: artifacts.record_failure(title, f"not saved: {save_err}",
                                                 goal_id=goal_id))
        except Exception:
            pass

    await _mark_task(item["task_id"], "succeeded")
    detail = outcome or None
    if saved_url:
        where = "your Mac" if saved_url.startswith("~") else "vault"
        detail = f"{outcome}\n\nSaved to {where}: {saved_url}"
    await bus.emit("executor", "task.completed", f"Done ({backend}): {title} — {outcome[:120]}",
                   detail=detail, level="success", goal_id=goal_id)
    return True


# Any output past this saves as a full note. Was 300 (dropped concise but real
# answers to a log line only); a couple of sentences is worth a page.
SAVE_NOTE_MIN = int(os.getenv("EXECUTOR_SAVE_NOTE_MIN", "80"))


# "local" as a DESTINATION, not as a topic. "research local coffee shops" must
# not route the save to the laptop, so a bare "local" only counts next to a
# save/file word; "on my computer" and friends are unambiguous on their own.
_LOCAL_DEST_RE = re.compile(
    r"\b(?:(?:on|to|onto|in) my (?:computer|laptop|mac|machine|desktop)"
    r"|local(?:ly)?[ -]?(?:based|hosted|file|copy|folder|disk|drive)"
    r"|(?:save|store|put|write|keep|download|page|doc|note|file)\w*\s+"
    r"(?:\w+\s+){0,3}?local(?:ly)?\b"
    r"|local(?:ly)?\s+(?:\w+\s+){0,3}?(?:save|store|file|folder|disk|drive))\b",
    re.IGNORECASE)


def _wants_local(objective: str) -> bool:
    """True when Trav asked for the output ON HIS MACHINE. He said 'locally
    based' and got a GitHub vault page — the guaranteed save ignored the goal
    text entirely, so fixing only the planner left this half broken."""
    return bool(_LOCAL_DEST_RE.search(objective or ""))


def _save_local(title: str, outcome: str, goal_id: str | None) -> tuple[str | None, str | None]:
    """Hand the write to the laptop worker. Returns (path, error)."""
    from . import local

    if not local.online():
        return None, "laptop worker offline — nothing written to your Mac"
    slug = (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]) or "research"
    rel = f"{slug}.md"
    try:
        local.enqueue_file_save(rel, f"# {title}\n\n{outcome.strip()}\n",
                                f"Save {rel} to the workspace")
    except Exception as exc:
        return None, str(exc)[:160]
    # The worker records the artifact once the bytes are on disk — that row, not
    # this return, is the proof it landed.
    return rel, None


def _autosave_output(title: str, outcome: str, goal_id: str | None = None,
                     objective: str = "") -> tuple[str | None, str | None]:
    """Persist a step's output. When the goal asked for it locally, the file goes
    to the Mac (via the laptop worker) and the vault becomes a best-effort
    archive; otherwise the vault is the target. Returns (url_or_path, error) —
    error only when NOTHING was written, so the caller never reports a save that
    didn't happen."""
    if not (outcome or "").strip():
        return None, None

    if _wants_local(objective) and len(outcome.strip()) >= SAVE_NOTE_MIN:
        rel, local_err = _save_local(title, outcome, goal_id)
        if rel:
            # also archive to the vault, but never let its failure (e.g. an
            # expired GITHUB_TOKEN) mask a successful local save
            try:
                _vault_save(title, outcome, goal_id)
            except Exception:
                pass
            return f"~/resolve-workspace/{rel}", None
        # laptop unreachable — fall through to the vault so the work survives
        vault_url, vault_err = _vault_save(title, outcome, goal_id)
        if vault_url:
            return vault_url, None
        return None, f"{local_err}; vault fallback also failed: {vault_err}"

    return _vault_save(title, outcome, goal_id)


def _vault_save(title: str, outcome: str,
                goal_id: str | None = None) -> tuple[str | None, str | None]:
    """Write a full wiki/output note for anything substantial. Returns
    (url, error): url when a note was written, error when the GitHub write
    actually FAILED (so the caller can surface it instead of a silent success).
    There is no longer a per-step log line — Supabase is the ledger."""
    if not (outcome or "").strip():
        return None, None
    if not vault_github.configured():
        return None, "vault not configured (GITHUB_TOKEN missing)"
    # No per-step log line: it was a commit per step on a shared file, and the
    # full note written below is the actual record.
    if len(outcome.strip()) < SAVE_NOTE_MIN:
        # genuinely tiny (a number, a yes/no): not worth a vault page. It is
        # still in the Supabase event ledger and the daily summary.
        return None, None
    slug = (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]) or "research"
    path = f"wiki/output/{slug}.md"
    try:
        vault_github.write_file(path, f"# {title}\n\n{outcome.strip()}\n",
                                message=f"agent: save {title[:50]}")
        try:
            # goal_id so the dock row ties back to the mission that produced it
            artifacts.record_vault(path, action="created", goal_id=goal_id)
        except Exception:
            pass
        return f"https://github.com/{vault_github.VAULT_REPO}/blob/main/{path}", None
    except Exception as exc:
        return None, str(exc)[:160]  # surfaced by the caller, not swallowed


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


async def _settle_goal(goal_id: str, failed: bool) -> None:
    """Write the plan's real verdict onto the goal row once the queue drains."""
    if not goal_id or len(goal_id) != 36:  # non-uuid ids never made it to the store
        return
    status = "failed" if failed else "completed"
    try:
        await anyio.to_thread.run_sync(
            lambda: store.update("goals", {"id": f"eq.{goal_id}"},
                                 {"status": status,
                                  "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                time.gmtime())})
        )
    except Exception:
        pass
    if failed:
        await bus.emit("core", "goal.failed",
                       "The plan finished with a failed step — nothing reliable was saved.",
                       level="error", goal_id=goal_id)


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
            step_ok = await _current_step_task
            completed_ok = True
            # an honest failure (empty/narration-only output) returns False rather
            # than raising, so capture it here or the sign-off says "All wrapped up"
            if step_ok is False:
                any_failed = True
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
            await bus.set_orb("idle", "Standing by", [])
            # The plan is what finishes the goal, not the assistant's "queued"
            # reply — settle the row here so a failed plan can't sit in the
            # dashboard reading "completed".
            await _settle_goal(item.get("goal_id", ""), failed=any_failed)
            # spoken sign-off once the whole plan is done — honest about failures
            if completed_ok:
                msg = "Done — though a step ran into trouble." if any_failed else "All wrapped up."
                await bus.emit("assistant", "speak.progress", msg,
                               goal_id=item.get("goal_id"))
            any_failed = False  # reset for the next batch
