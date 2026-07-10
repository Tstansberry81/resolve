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


def model_choice(role: str, config_dir: Path | None = None, fallback: bool = False) -> ModelChoice:
    routes = load_json("model_routes.json", config_dir)["routes"]
    if role not in routes:
        raise KeyError(f"unknown model role: {role}")
    raw = routes[role]["fallback" if fallback else "primary"]
    if raw is None:
        raise KeyError(f"no {'fallback' if fallback else 'primary'} configured for {role}")
    return ModelChoice(**raw)
