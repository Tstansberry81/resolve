"""User-defined site shortcuts: turn a short name Trav says ("news", "outlook")
into the exact URL he wants, so open_website jumps straight there instead of
guessing a URL or searching.

The shortcut map lives in `_SHORTCUTS` below — this is the source of truth and
ships with the code (the deploy image only bundles `src/`, so a config file
wouldn't be present in prod). To add a shortcut, add a line here and redeploy.
A `config/site_shortcuts.json` file, if present (local/docker), overrides or
extends these.
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from . import config

# alias (lowercase) -> exact URL. Trav's frequent sites.
_SHORTCUTS: dict[str, str] = {
    "amazon": "https://amazon.com",
    "instagram": "https://instagram.com",
    "news": "https://news.google.com/",
    "github": "https://github.com/",
    "google drive": "https://drive.google.com/",
    "drive": "https://drive.google.com/",
    "gmail": "https://mail.google.com/",
    "outlook": "https://outlook.cloud.microsoft/mail/",
    # canvas: add the URL when Trav provides it
}

# leading filler we strip before matching ("open the news" -> "news")
_STRIP = re.compile(
    r"^(please\s+)?(open|go\s+to|goto|take\s+me\s+to|navigate\s+to|visit|launch|"
    r"pull\s+up|bring\s+up|show\s+me|jump\s+to)\s+",
    re.I,
)
_SCHEME = re.compile(r"^[a-z]+://", re.I)


def shortcuts() -> dict[str, str]:
    """Current alias -> URL map. Embedded defaults, optionally overridden by a
    config/site_shortcuts.json if one is present on this deployment."""
    table = dict(_SHORTCUTS)
    try:
        raw = config.load_json("site_shortcuts.json")
        table.update(
            {
                str(k).strip().lower(): str(v).strip()
                for k, v in raw.items()
                if isinstance(v, str) and v.strip()
            }
        )
    except Exception:
        pass  # no config file — embedded defaults are authoritative
    return table


def resolve(query: str) -> str:
    """Resolve what to open. Known alias -> its URL; a bare domain -> https://…;
    a real URL -> unchanged; anything else -> a Google search for it."""
    q = (query or "").strip()
    if not q:
        return q
    key = _STRIP.sub("", q).strip().lower().rstrip(" .!?,")
    key = re.sub(r"^the\s+", "", key)

    table = shortcuts()
    if key in table:
        return table[key]
    if _SCHEME.match(q):
        return q  # already a full URL
    if " " not in q and "." in q:
        return "https://" + q  # bare domain like "figma.com"
    # unknown short name — search for it rather than build a bad URL
    return "https://www.google.com/search?q=" + quote_plus(q)
