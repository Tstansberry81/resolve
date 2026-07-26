"""The Coder + Reviewer pair from docs/DIRECTION.md.

Three model routes — `coding_architect`, `coding_implementer`, `code_reviewer` —
have sat in config/model_routes.json since the beginning with nothing reading
them. The roster promised a Coder and a Reviewer; neither existed. This is them.

The split matters. The laptop worker can already edit files and run shell
commands, so "make RESOLVE write code" was never blocked on hands — it was
blocked on *judgment*. Handing a bare objective to the worker gets an agent that
starts editing before it understands the codebase. So:

  architect (Opus 4.8) -> a concrete, file-level plan, written after reading
  implementer (the laptop worker)  -> does it, on Trav's machine, with his repo
  reviewer  (Opus 4.8, separate context) -> reads the diff adversarially

The reviewer runs in a FRESH context on purpose. A model reviewing its own work
in the same conversation rationalises it; the system plan's independent-review
principle is the whole reason `code_reviewer` is its own route.

Cost: the architect pass is one bounded call before any work starts. That is
cheap next to what it prevents — an agent flailing through a dozen tool calls on
a laptop because it guessed at the layout.
"""

from __future__ import annotations

import logging
import os

import anthropic

from . import costs
from .config import model_choice

log = logging.getLogger("resolve.coder")

MAX_PLAN_TOKENS = 2000
MAX_REVIEW_TOKENS = 3000


def _model(role: str, default: str) -> str:
    """Resolve a route from config, falling back if the role is missing or the
    config is unreadable — a coding request must not die on a config typo."""
    try:
        return model_choice(role).model
    except Exception:
        log.warning("coder: no model route for %s, using %s", role, default)
        return default


def architect_model() -> str:
    return os.getenv("CODER_ARCHITECT_MODEL") or _model("coding_architect", "claude-opus-4-8")


def reviewer_model() -> str:
    return os.getenv("CODER_REVIEWER_MODEL") or _model("code_reviewer", "claude-opus-4-8")


ARCHITECT_SYSTEM = """You are RESOLVE's coding architect. You do NOT write the final code —
you write the brief that a capable coding agent will execute on Trav's laptop, where it has
file read/write, search, and shell access to the real repository.

Produce a plan that is specific enough to execute and honest about what you don't know:
- State what to inspect FIRST. The executing agent has not seen the codebase; assume nothing
  about structure, framework, or naming, and tell it to read before it edits.
- List concrete steps in order. Name likely files, but say they must be verified, not assumed.
- Say explicitly how the change gets VERIFIED (which tests, which command, what output proves
  it worked). A change nobody verified is not done.
- Call out the risky part — the thing most likely to break something else.
- Keep it tight. This is a brief, not an essay. No boilerplate, no restating the request.

If the objective is ambiguous in a way that would lead to materially different work, say so
in one line at the top and pick the most reasonable reading rather than stalling."""

REVIEWER_SYSTEM = """You are RESOLVE's code reviewer, reading a change you did not write.
Be adversarial and concrete: your job is to find what's actually wrong, not to be agreeable.

For each finding give: the file, what breaks, and the specific input or state that triggers it.
Rank by severity. Prefer correctness bugs, security issues, and silent failures over style.
If the change looks correct, say so plainly and briefly — do not invent findings to seem useful.
If you can't tell whether something is a bug without seeing more code, say which file you'd
need rather than guessing."""


def plan(objective: str, context: str = "") -> str:
    """Architect pass: turn a request into an executable brief.

    Synchronous on purpose: tool dispatch already runs off the event loop in a
    worker thread, so an async client here would mean nesting a loop inside a
    thread for no benefit.
    """
    model = architect_model()
    client = anthropic.Anthropic()
    prompt = f"Objective:\n{objective}"
    if context.strip():
        prompt += f"\n\nWhat Trav already told us about the project:\n{context.strip()}"
    resp = client.messages.create(
        model=model, max_tokens=MAX_PLAN_TOKENS, system=ARCHITECT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    costs.record("coder.architect", model, resp.usage)
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()


def review(diff: str, objective: str = "") -> str:
    """Reviewer pass over a diff, in a context that never saw it being written."""
    model = reviewer_model()
    client = anthropic.Anthropic()
    intent = f"The change was supposed to: {objective}\n\n" if objective.strip() else ""
    resp = client.messages.create(
        model=model, max_tokens=MAX_REVIEW_TOKENS, system=REVIEWER_SYSTEM,
        messages=[{"role": "user",
                   "content": f"{intent}Review this diff.\n\n```diff\n{diff[:60_000]}\n```"}],
    )
    costs.record("coder.reviewer", model, resp.usage)
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()


def build_brief(objective: str, plan_text: str, path: str = "") -> str:
    """The task text handed to the laptop worker.

    The closing rules exist because of failures this repo already hit once: an
    agent that narrates instead of acting, and one that reports success without
    running anything.
    """
    where = f"\nWork in: {path}\n" if path.strip() else ""
    return (
        f"CODING TASK.\n{where}\nObjective:\n{objective}\n\n"
        f"Architect's brief (follow it, but correct it if the real code disagrees):\n"
        f"{plan_text}\n\n"
        "Rules:\n"
        "- READ the relevant files before editing anything. The brief guessed at "
        "structure; the repo is the truth.\n"
        "- Make the change, then RUN the verification named above and paste the real "
        "output. Do not claim it passes without running it.\n"
        "- If tests fail, fix and re-run. If you can't get them passing, say exactly "
        "what still fails and why — a partial change reported honestly is fine, a "
        "broken change reported as done is not.\n"
        "- Do not commit or push unless Trav asked you to.\n"
        "- Keep the change scoped to the objective. No opportunistic refactors."
    )
