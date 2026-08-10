from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _default_config_dir() -> Path:
    configured = os.getenv("RESOLVE_CONFIG_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[4] / "config"


def load_json(name: str, config_dir: Path | None = None) -> dict[str, Any]:
    path = (config_dir or _default_config_dir()) / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    reasoning: str


# Effort (output_config.effort) is how thinking depth -- and so most of the
# output-token bill -- gets controlled on current models. It is NOT universal:
# Haiku 4.5 predates the parameter and rejects it, so a blanket pass-through would
# 400 every executor and ingest call. Omitting it means the model's own default,
# which is `high` on Opus 5 -- that default is why the `reasoning` field sat in
# model_routes.json for months while every call silently ran flat out.
_EFFORT_MODELS = (
    "claude-opus-5", "claude-sonnet-5", "claude-fable-5",
    "claude-opus-4-8", "claude-opus-4-7",
)
_EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})


def effort_for(model: str, reasoning: str) -> dict[str, Any] | None:
    """The ``output_config`` for a call, or None when it must be omitted.

    None for "none"/unknown levels and for models that don't take the parameter,
    so callers can splat it unconditionally without a branch:

        **({"output_config": oc} if (oc := effort_for(m, r)) else {})
    """
    if reasoning not in _EFFORT_LEVELS:
        return None
    if not model.startswith(_EFFORT_MODELS):
        return None
    return {"effort": reasoning}


def model_choice(role: str, config_dir: Path | None = None, fallback: bool = False) -> ModelChoice:
    routes = load_json("model_routes.json", config_dir)["routes"]
    if role not in routes:
        raise KeyError(f"unknown model role: {role}")
    raw = routes[role]["fallback" if fallback else "primary"]
    if raw is None:
        raise KeyError(f"no {'fallback' if fallback else 'primary'} configured for {role}")
    return ModelChoice(**raw)
