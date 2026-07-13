"""Autonomous daily vault ingest.

At midnight ET, gather the prior day's RESOLVE activity (goals/commands + replies
+ outcomes from Supabase) and run a CLAUDE.md-guided ingest into the vault: the
day's source page, propagation into entities/concepts, index + log updates —
following the vault's own operating manual, which is loaded as the agent's
instructions. Writes are git-versioned (reversible) and `raw/`/CLAUDE.md are
hard-guarded in vault_github.write_file.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any
from zoneinfo import ZoneInfo

import anthropic
import anyio

from . import bus, costs, store
from .connectors import vault_github

log = logging.getLogger("resolve.ingest")

INGEST_MODEL = os.getenv("INGEST_MODEL", "claude-opus-4-8")
MAX_TURNS = 44

# event types that represent real activity worth ingesting (skip bookkeeping rows)
_ACTIVITY = {"goal.accepted", "assistant.reply", "task.completed", "goal.completed",
             "route.classified", "plan.ready"}

TOOLS = [
    {"name": "vault_read", "description": "Read a vault file's contents.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "vault_search", "description": "List vault file paths whose name matches a query.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                      "required": ["query"]}},
    {"name": "vault_list", "description": "List existing vault files under a prefix (e.g. wiki/, wiki/concepts/).",
     "input_schema": {"type": "object", "properties": {"prefix": {"type": "string"}}}},
    {"name": "vault_write", "description": "Create or overwrite a wiki/ or output/ file. Never raw/ or CLAUDE.md.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}, "message": {"type": "string"}},
         "required": ["path", "content"]}},
    {"name": "vault_append_log", "description": "Append a dated entry to wiki/log.md.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "lines": {"type": "array", "items": {"type": "string"}}},
         "required": ["title", "lines"]}},
    {"name": "finish", "description": "Call when the ingest is complete, with a one-paragraph summary of what you filed.",
     "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}},
                      "required": ["summary"]}},
]


def _dispatch(name: str, args: dict[str, Any]) -> Any:
    if name == "vault_read":
        return vault_github.read_file(str(args["path"]), int(args.get("limit", 6000)))
    if name == "vault_search":
        return vault_github.search_files(str(args["query"]))
    if name == "vault_list":
        return vault_github.list_tree(str(args.get("prefix", "wiki/")))
    if name == "vault_write":
        return vault_github.write_file(str(args["path"]), str(args["content"]), str(args.get("message", "")))
    if name == "vault_append_log":
        return vault_github.append_log(str(args["title"]), list(args.get("lines", [])))
    raise ValueError(f"unknown tool {name}")


def gather_materials(day_iso: str) -> str:
    """Compile the day's RESOLVE activity (goals + notable events) from Supabase."""
    nxt = (datetime.date.fromisoformat(day_iso) + datetime.timedelta(days=1)).isoformat()
    rng = f"(created_at.gte.{day_iso}T00:00:00,created_at.lt.{nxt}T00:00:00)"
    lines: list[str] = []
    try:
        goals = store.select("goals", {"and": rng, "order": "created_at.asc", "limit": "100"})
        for g in goals:
            obj = (g.get("objective") or "").strip()
            if obj:
                lines.append(f"- COMMAND: {obj}  (status: {g.get('status', '?')})")
    except Exception:
        pass
    try:
        events = store.select("agent_events", {"and": rng, "order": "created_at.asc", "limit": "300"})
        for e in events:
            if e.get("event_type") not in _ACTIVITY:
                continue
            p = e.get("payload") or {}
            if isinstance(p, str):
                try:
                    p = json.loads(p)
                except Exception:
                    p = {}
            text = (p.get("detail") or p.get("summary") or "").strip()
            if text:
                lines.append(f"- {e.get('event_type')}: {text[:400]}")
    except Exception:
        pass
    return "\n".join(lines)


async def run_daily_ingest(day_iso: str | None = None) -> dict:
    """Run the autonomous CLAUDE.md ingest for `day_iso` (defaults to yesterday ET)."""
    if not vault_github.configured():
        return {"skipped": "vault not configured"}
    if day_iso is None:
        y = (datetime.datetime.now(ZoneInfo("America/New_York")).date() - datetime.timedelta(days=1))
        day_iso = y.isoformat()

    materials = await anyio.to_thread.run_sync(lambda: gather_materials(day_iso))
    if not materials.strip():
        await bus.emit("core", "vault.ingest", f"Daily ingest {day_iso}: no activity to ingest",
                       level="info")
        return {"day": day_iso, "skipped": "no activity"}

    await bus.emit("assistant", "vault.ingest", f"Autonomous daily ingest started for {day_iso}",
                   edge={"from": "assistant", "to": "vault"})
    await bus.set_orb("executing", f"Ingesting {day_iso} into the vault", ["assistant", "vault"])

    manual = (await anyio.to_thread.run_sync(lambda: vault_github.read_file("CLAUDE.md", 14000)))["content"]
    try:
        index = (await anyio.to_thread.run_sync(lambda: vault_github.read_file("wiki/index.md", 8000)))["content"]
    except Exception:
        index = "(index.md not found)"

    system = (
        manual
        + "\n\n---\n\n# YOUR TASK RIGHT NOW: autonomous daily ingest\n"
        f"You are RESOLVE running the unattended daily ingest for {day_iso}. Treat the day's "
        "RESOLVE activity below as the source to ingest. Follow the manual's **Ingest** operation "
        "exactly: write a wiki/sources/ summary page for the day, PROPAGATE into the relevant "
        "entities/ and concepts/ pages (read them first with vault_read; update or create as "
        "needed), update wiki/overview.md if the picture shifts, refresh wiki/index.md, and append "
        "to wiki/log.md. Obey honest calibration — do not flatter, name gaps, flag contradictions "
        "with a warning callout instead of overwriting, keep frontmatter + [[wikilinks]] + sources "
        "provenance on every page. NEVER write to raw/ or CLAUDE.md (the tools will refuse). Read "
        "before you write. When fully done, call finish with a summary."
    )
    user = (
        f"=== wiki/index.md ===\n{index}\n\n"
        f"=== yesterday's RESOLVE activity ({day_iso}) — the source to ingest ===\n{materials}"
    )

    client = anthropic.AsyncAnthropic()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    result_summary = ""
    written: list[str] = []
    nudges = 0

    for _ in range(MAX_TURNS):
        resp = await client.messages.create(
            model=INGEST_MODEL, max_tokens=2500, system=system, tools=TOOLS, messages=messages,
        )
        costs.record("ingest", INGEST_MODEL, resp.usage)
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not tool_uses:
            texts = [b.text for b in resp.content if b.type == "text"]
            if texts:
                result_summary = texts[-1]
            # The model narrated instead of calling a tool — it's not actually
            # done until it calls finish(). Nudge it to complete the manual's
            # remaining steps (index/overview/propagation), a few times.
            if nudges < 4:
                nudges += 1
                if texts:
                    messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": (
                    "You haven't called finish yet. Keep going and COMPLETE the ingest per the "
                    "manual: refresh wiki/index.md (add the new pages), update wiki/overview.md if "
                    "the picture shifted, and propagate the day's facts into the relevant "
                    "entities/ and concepts/ pages (read each with vault_read first, then "
                    "vault_write). Only call finish once those steps are actually done."
                )})
                continue
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        done = False
        for tu in tool_uses:
            if tu.name == "finish":
                result_summary = str(dict(tu.input).get("summary", ""))
                done = True
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "ok"})
                continue
            try:
                out = await anyio.to_thread.run_sync(lambda: _dispatch(tu.name, dict(tu.input)))
                if tu.name == "vault_write" and isinstance(out, dict) and out.get("path"):
                    written.append(out["path"])
                    await bus.emit("assistant", "vault.write", f"Wrote {out['path']}",
                                   edge={"from": "assistant", "to": "vault"})
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": json.dumps(out, default=str)[:2000]})
            except Exception as exc:
                results.append({"type": "tool_result", "tool_use_id": tu.id,
                                "content": f"Error: {exc}", "is_error": True})
        messages.append({"role": "user", "content": results})
        if done:
            break

    try:
        await anyio.to_thread.run_sync(lambda: store.insert("agent_events", {
            "event_type": "vault.ingest", "actor": "assistant",
            "payload": {"date": day_iso, "summary": result_summary[:1500], "pages": written},
        }))
    except Exception:
        pass
    await bus.emit("assistant", "vault.ingest",
                   f"Daily ingest {day_iso} complete — {len(written)} page(s) written",
                   detail=result_summary[:600] or None, level="success")
    await bus.set_orb("idle", "Sonnet standing by", [])
    return {"day": day_iso, "pages": written, "summary": result_summary}
