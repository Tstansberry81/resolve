"""Token-cost helpers for the model message transcript.

Two levers live here:
- ``cached_system`` builds a ``system`` payload whose static prefix is marked
  with ``cache_control`` so Anthropic prompt-caching bills the big, unchanging
  SYSTEM/preamble + tool schema at 0.1x on every turn after the first, instead of
  full price every turn.
- ``compact_messages`` shrinks OLD tool_result blocks in place so a long
  multi-turn loop stops re-sending fat search/read results in full each turn.

Note: we deliberately cache only the STATIC prefix (tools + system) and TRIM the
conversation rather than caching it — mutating old messages would bust a
message-level cache, so the two strategies are kept on separate regions.
"""

from __future__ import annotations

from typing import Any

_EPHEMERAL = {"type": "ephemeral"}


def cached_system(static_text: str, *extra: str) -> list[dict[str, Any]]:
    """Return a ``system`` list: one cached static block (caches tools+system as a
    prefix) followed by any small dynamic blocks (uncached — e.g. the current
    datetime, which would otherwise bust the cache every minute)."""
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": static_text, "cache_control": _EPHEMERAL}
    ]
    for e in extra:
        if e:
            blocks.append({"type": "text", "text": e})
    return blocks


def compact_messages(messages: list[dict[str, Any]], keep_last: int = 2,
                     stub_at: int = 700) -> None:
    """Shrink old tool_result blocks IN PLACE so the growing transcript isn't
    re-sent in full every turn. The last ``keep_last`` tool-result turns stay
    intact (the model still needs recent context); older tool_result contents
    longer than ``stub_at`` chars are truncated with a marker."""
    tr_idx = [
        i for i, m in enumerate(messages)
        if m.get("role") == "user" and isinstance(m.get("content"), list)
        and any(isinstance(b, dict) and b.get("type") == "tool_result"
                for b in m["content"])
    ]
    stale = tr_idx[:-keep_last] if keep_last else tr_idx
    for i in stale:
        for b in messages[i]["content"]:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                c = b.get("content")
                if isinstance(c, str) and len(c) > stub_at:
                    b["content"] = c[:stub_at] + " …[trimmed to save tokens]"
