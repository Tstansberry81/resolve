from __future__ import annotations

from fastapi import FastAPI, HTTPException

from . import __version__
from .config import load_json, model_choice


app = FastAPI(title="RESOLVE Control Plane", version=__version__)


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
    return {
        "role": role,
        "provider": choice.provider,
        "model": choice.model,
        "reasoning": choice.reasoning,
    }


@app.get("/v1/connectors")
def connectors() -> dict:
    return load_json("connectors.json")
