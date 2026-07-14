from __future__ import annotations

import asyncio
import json
import os

import anyio
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__, artifacts, bus, costs, executor, local, routines, store
from .connectors import local_llm, simplefin
from .assistant import (
    CONNECTOR_AVAILABLE, decide_approval, pending_actions, queue_status, run_command,
)
from .config import load_json, model_choice

app = FastAPI(title="RESOLVE Control Plane", version=__version__)


@app.on_event("startup")
async def _start_worker() -> None:
    try:
        await anyio.to_thread.run_sync(costs.load_seed)  # restore today's cost total
        await anyio.to_thread.run_sync(artifacts.load_seed)  # restore artifact dock
    except Exception:
        pass
    asyncio.get_running_loop().create_task(executor.worker_loop())
    asyncio.get_running_loop().create_task(routines.scheduler_loop())

CP_TOKEN = os.getenv("CP_TOKEN", "")


def auth(request: Request) -> None:
    """Bearer-token gate for /v1/*. Open when CP_TOKEN is unset (local dev)."""
    if not CP_TOKEN:
        return
    header = request.headers.get("authorization", "")
    if header != f"Bearer {CP_TOKEN}":
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/")
def root() -> dict:
    return {"service": "resolve-control-plane", "version": __version__,
            "see": ["/healthz", "/docs", "/v1/snapshot"]}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/v1/model-routes")
def model_routes() -> dict:
    return load_json("model_routes.json")


@app.get("/v1/model-routes/{role}")
def model_route(role: str) -> dict[str, str]:
    try:
        choice = model_choice(role)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"role": role, "provider": choice.provider, "model": choice.model,
            "reasoning": choice.reasoning}


@app.get("/v1/connectors")
def connectors() -> dict:
    return load_json("connectors.json")


# ── live surface ──────────────────────────────────────────────────────────


def _connector_health() -> list[dict]:
    labels = {"vault": "Vault (GitHub)", "gmail": "Gmail", "calendar": "Calendar",
              "notion": "Notion", "google": "Google Docs"}
    out = []
    for cid, check in CONNECTOR_AVAILABLE.items():
        out.append({"id": cid, "label": labels.get(cid, cid),
                    "status": "healthy" if check() else "down", "latencyMs": 0})
    return out


@app.get("/v1/snapshot", dependencies=[Depends(auth)])
async def snapshot() -> dict:
    def _load():
        goals = store.select("goals", {"order": "created_at.desc", "limit": "12"})
        approvals = store.select("approvals", {"order": "created_at.desc", "limit": "8"})
        return goals, approvals

    goals_raw, approvals_raw = await anyio.to_thread.run_sync(_load)

    goals = [
        {
            "id": str(g.get("id")),
            "objective": g.get("objective", ""),
            "category": g.get("category", "personal"),
            "status": g.get("status", "active"),
            "autonomyMode": g.get("autonomy_mode", "execute"),
            "progress": 1.0 if g.get("status") == "completed" else 0.5,
            "budgetUsd": float(g.get("max_cost_usd") or 2),
            "spentUsd": 0.0,
            "deadline": None,
            "nextAction": "—" if g.get("status") == "completed" else "In flight",
            "blocker": "Needs your approval" if g.get("status") == "waiting_approval" else None,
        }
        for g in goals_raw
    ]
    approvals = [
        {
            "id": str(a.get("id")),
            "goalId": str(a.get("goal_id") or ""),
            "actionSummary": a.get("action_summary", ""),
            "risk": a.get("risk_class", "communication_send"),
            "preview": a.get("preview_json") or [],
            "recipient": None,
            "undoWindow": None,
            "status": a.get("status", "pending"),
        }
        for a in approvals_raw
    ]
    return {
        "mode": "live",
        "orb": bus.orb["state"],
        "orbCaption": bus.orb["caption"],
        "activeNodes": list(bus.active_nodes),
        "goals": goals,
        "events": bus.recent_events(),
        "approvals": approvals,
        "artifacts": artifacts.recent(),
        "connectors": _connector_health(),
        "pendingApprovals": len(pending_actions),
        "taskQueue": queue_status(),
        "costs": costs.snapshot(),
        "localExec": executor.local_exec,
        "localAvailable": local_llm.configured(),
        "localWorker": local.online(),
    }


@app.get("/v1/events", dependencies=[Depends(auth)])
async def events() -> StreamingResponse:
    q = bus.subscribe()

    async def stream():
        try:
            yield f"data: {json.dumps({'kind': 'hello'})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(msg, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class CommandBody(BaseModel):
    text: str


@app.post("/v1/command", dependencies=[Depends(auth)])
async def command(body: CommandBody) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty command")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
    goal_id = await run_command(text)
    return {"ok": True, "goalId": goal_id}


class DecisionBody(BaseModel):
    decision: str  # approved | rejected


@app.post("/v1/approvals/{approval_id}/decide", dependencies=[Depends(auth)])
async def approval_decide(approval_id: str, body: DecisionBody) -> dict:
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="decision must be approved|rejected")
    return await decide_approval(approval_id, body.decision)


@app.post("/v1/stop", dependencies=[Depends(auth)])
async def emergency_stop() -> dict:
    from .assistant import stop_current
    await executor.set_halted(True)      # stay halted until resume
    res = await stop_current()           # also cancel whatever's running RIGHT NOW
    return {"ok": True, "halted": True, **res}


@app.post("/v1/resume", dependencies=[Depends(auth)])
async def resume() -> dict:
    await executor.set_halted(False)
    return {"ok": True, "halted": False}


class ToggleBody(BaseModel):
    on: bool


@app.post("/v1/settings/local_exec", dependencies=[Depends(auth)])
async def set_local_exec(body: ToggleBody) -> dict:
    await executor.set_local_exec(body.on)
    return {"ok": True, "localExec": executor.local_exec}


# ── finance (SimpleFIN) ─────────────────────────────────────────────────────


class ConnectBody(BaseModel):
    setup_token: str


@app.get("/v1/finance/status", dependencies=[Depends(auth)])
def finance_status() -> dict:
    return {"connected": simplefin.configured()}


@app.post("/v1/finance/connect", dependencies=[Depends(auth)])
async def finance_connect(body: ConnectBody) -> dict:
    token = (body.setup_token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="setup_token required")
    try:
        await anyio.to_thread.run_sync(lambda: simplefin.claim(token))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SimpleFIN claim failed: {exc}")
    return {"ok": True, "connected": simplefin.configured()}


# ── local worker (laptop hands) ─────────────────────────────────────────────


class ResultBody(BaseModel):
    taskId: str
    summary: str = ""


class EventBody(BaseModel):
    taskId: str = ""
    summary: str
    detail: str | None = None


class LocalApprovalBody(BaseModel):
    taskId: str = ""
    summary: str
    detail: str = ""
    risk: str = "local_shell"


@app.get("/v1/local/next", dependencies=[Depends(auth)])
def local_next() -> dict:
    return local.next_task() or {}


@app.post("/v1/local/result", dependencies=[Depends(auth)])
def local_result(body: ResultBody) -> dict:
    local.set_result(body.taskId, body.summary)
    return {"ok": True}


@app.post("/v1/local/event", dependencies=[Depends(auth)])
async def local_event(body: EventBody) -> dict:
    await bus.emit("executor", "local.event", body.summary, detail=body.detail,
                   edge={"from": "executor", "to": "web"}, goal_id=body.taskId or None)
    return {"ok": True}


class LocalArtifactBody(BaseModel):
    name: str
    path: str
    location: str = "local"  # local | vault
    href: str = ""           # worker supplies file:// so links resolve on-disk
    action: str = "created"  # created | updated
    taskId: str = ""


@app.post("/v1/local/artifact", dependencies=[Depends(auth)])
async def local_artifact(body: LocalArtifactBody) -> dict:
    """The laptop worker reports a file it created/changed so it lands in the
    Artifacts dock with a clickable link that resolves on Trav's Mac."""
    def _rec():
        return artifacts.record(body.name, body.path, location=body.location,
                                href=body.href or None, action=body.action,
                                goal_id=body.taskId or None)
    await anyio.to_thread.run_sync(_rec)
    return {"ok": True}


@app.post("/v1/local/approval", dependencies=[Depends(auth)])
def local_approval(body: LocalApprovalBody) -> dict:
    return {"id": local.request_approval(body.taskId, body.summary, body.detail, body.risk)}


@app.get("/v1/local/approval/{approval_id}", dependencies=[Depends(auth)])
def local_approval_status(approval_id: str) -> dict:
    return {"status": local.approval_status(approval_id)}


@app.get("/v1/finance/summary", dependencies=[Depends(auth)])
async def finance_summary(days: int = 90, refresh: bool = False) -> dict:
    if not simplefin.configured():
        raise HTTPException(status_code=409, detail="not connected")
    days = max(1, min(days, 365))
    try:
        return await anyio.to_thread.run_sync(lambda: simplefin.summary(days, refresh))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SimpleFIN fetch failed: {exc}")


@app.get("/v1/integrations/google/status", dependencies=[Depends(auth)])
def google_status() -> dict:
    from .connectors import composio
    return {"configured": composio.configured()}


@app.post("/v1/integrations/google/test", dependencies=[Depends(auth)])
async def google_test() -> dict:
    """Create a throwaway Google Doc to verify the Composio wiring end-to-end
    without going through the assistant. Returns the doc link."""
    from .connectors import composio
    if not composio.configured():
        raise HTTPException(status_code=409, detail="Composio not configured (COMPOSIO_API_KEY unset)")
    try:
        res = await anyio.to_thread.run_sync(
            lambda: composio.create_doc(
                "RESOLVE wiring test",
                "# It works ✅\nRESOLVE's control plane created this via Composio.",
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google Docs create failed: {exc}")
    try:
        from . import artifacts
        artifacts.record("RESOLVE wiring test", res.get("url", ""), location="gdrive",
                         href=res.get("url"), action="created")
    except Exception:
        pass
    return {"ok": True, **res}


@app.post("/v1/routines/morning_brief", dependencies=[Depends(auth)])
async def morning_brief() -> dict:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
    goal_id = await routines.run_morning_brief()
    return {"ok": True, "goalId": goal_id}


@app.post("/v1/routines/daily_ingest", dependencies=[Depends(auth)])
async def daily_ingest(date: str | None = None) -> dict:
    """Manually trigger the vault ingest (defaults to yesterday) — use this to
    validate the first run before trusting the midnight schedule."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
    from . import ingest
    return await ingest.run_daily_ingest(date)
