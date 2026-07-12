"""Local model lane — Trav's own hardware (Qwen 32B etc.) over a Cloudflare
tunnel. Any OpenAI-compatible server works (Ollama /v1, LM Studio, vLLM).

Activates when LOCAL_MODEL_URL is set, e.g. https://<tunnel>.trycloudflare.com/v1
LOCAL_MODEL_NAME picks the model (default qwen2.5:32b); LOCAL_MODEL_KEY is
optional — Ollama ignores it, some servers want one.
"""

from __future__ import annotations

import os

import requests


def configured() -> bool:
    return bool(os.getenv("LOCAL_MODEL_URL"))


def chat(prompt: str, system: str | None = None) -> dict:
    base = os.environ["LOCAL_MODEL_URL"].rstrip("/")
    model = os.getenv("LOCAL_MODEL_NAME", "qwen2.5:32b")
    headers = {"Content-Type": "application/json"}
    key = os.getenv("LOCAL_MODEL_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    r = requests.post(
        f"{base}/chat/completions",
        headers=headers,
        json={"model": model, "messages": messages, "max_tokens": 1000},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    return {"model": model,
            "reply": (data.get("choices") or [{}])[0].get("message", {}).get("content", "")}
