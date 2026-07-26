"""Semantic recall over the Obsidian vault.

The vault already has two search paths and both are LITERAL: the laptop worker
greps the on-disk clone for an exact substring, and GitHub code search matches
tokens. Both fail the question Trav actually asks — "what did I decide about the
foundation site's colors?" doesn't contain the word the note used ("cream and
beige palette"), so grep returns nothing and RESOLVE answers from thin air.

This adds meaning-based lookup on top, deliberately as a COMPLEMENT rather than
a replacement: `vault_read`'s grep stays the first stop because it's exact, free,
and instant. Semantic recall is for when you don't know the words.

Cost: text-embedding-3-small at $0.02/1M tokens. A whole personal vault is a
fraction of a cent to index. The content-hash check below therefore isn't about
money — it's so a daily re-index is a handful of API calls instead of hundreds,
and so it finishes fast enough to run inside the nightly routine.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any

import requests

from . import store
from .connectors import vault_github

log = logging.getLogger("resolve.vault_index")

EMBED_MODEL = os.getenv("VAULT_EMBED_MODEL", "text-embedding-3-small")
# ~1200 chars keeps a chunk inside one idea while staying well under the model's
# input limit. The overlap stops a definition that straddles a boundary from
# being unfindable in both halves.
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 200
# Below this cosine similarity the "match" is noise. Returning weak hits is worse
# than returning nothing: it invites the model to answer from an unrelated note.
MIN_SIMILARITY = 0.25


def configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") and store.configured())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_markdown(text: str) -> list[str]:
    """Split a note on headings first, then by size.

    Heading-first matters: a vault note is a set of topics under `##` headers,
    and splitting purely by character count merges the tail of one topic with the
    head of the next, which produces embeddings that match neither well.
    """
    text = (text or "").strip()
    if not text:
        return []

    sections = [s.strip() for s in re.split(r"\n(?=#{1,6}\s)", text) if s.strip()]
    chunks: list[str] = []
    for section in sections:
        if len(section) <= CHUNK_CHARS:
            chunks.append(section)
            continue
        start = 0
        while start < len(section):
            piece = section[start:start + CHUNK_CHARS]
            chunks.append(piece.strip())
            if start + CHUNK_CHARS >= len(section):
                break
            start += CHUNK_CHARS - CHUNK_OVERLAP
    return [c for c in chunks if c]


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch. One request per batch, not per chunk — the per-call
    overhead dominates otherwise."""
    if not texts:
        return []
    from openai import OpenAI

    resp = OpenAI().embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in resp.data]


def _existing_hashes() -> dict[tuple[str, int], str]:
    rows = store.select("vault_chunks", {"select": "path,chunk_index,content_hash"})
    return {(r["path"], r["chunk_index"]): r.get("content_hash", "") for r in rows}


def reindex(prefix: str = "wiki/", limit_files: int = 400) -> dict[str, Any]:
    """Walk the vault, embed what changed, and upsert it.

    Skips anything whose chunk text hashes to what's already stored, so a daily
    run over an unchanged vault makes zero embedding calls.
    """
    if not configured():
        raise RuntimeError("Vault recall needs OPENAI_API_KEY and Supabase configured.")

    paths = [p for p in vault_github.list_tree(prefix)["paths"]
             if p.lower().endswith((".md", ".markdown", ".txt"))][:limit_files]
    known = _existing_hashes()

    pending: list[dict[str, Any]] = []
    scanned = files_changed = 0

    for path in paths:
        try:
            body = vault_github.read_file(path, limit=200_000)["content"]
        except Exception:
            log.warning("vault_index: couldn't read %s", path)
            continue
        touched = False
        for idx, chunk in enumerate(chunk_markdown(body)):
            scanned += 1
            digest = _sha(chunk)
            if known.get((path, idx)) == digest:
                continue  # unchanged since the last run
            touched = True
            pending.append({"path": path, "chunk_index": idx,
                            "content": chunk, "content_hash": digest})
        files_changed += 1 if touched else 0

    written = 0
    for batch_start in range(0, len(pending), 64):
        batch = pending[batch_start:batch_start + 64]
        vectors = embed([row["content"] for row in batch])
        # strict: a short embedding batch would silently drop chunks, leaving
        # notes permanently unsearchable with no error anywhere.
        for row, vector in zip(batch, vectors, strict=True):
            payload = {**row, "embedding": vector}
            try:
                # PostgREST upsert: the (path, chunk_index) unique constraint turns
                # a re-index of an edited note into an update, not a duplicate row.
                _upsert(payload)
                written += 1
            except Exception:
                log.exception("vault_index: upsert failed for %s#%s",
                              row["path"], row["chunk_index"])

    return {"files": len(paths), "chunksScanned": scanned,
            "filesChanged": files_changed, "chunksEmbedded": written}


def _upsert(row: dict[str, Any]) -> None:
    """Insert-or-update one chunk. store.insert() can't express the conflict
    target, so this posts directly with the merge-duplicates preference."""
    resp = requests.post(
        f"{store.SUPABASE_URL}/rest/v1/vault_chunks",
        headers={**_store_headers(), "Prefer": "resolution=merge-duplicates"},
        params={"on_conflict": "path,chunk_index"},
        json=row, timeout=30,
    )
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"upsert failed {resp.status_code}: {resp.text[:180]}")


def _store_headers() -> dict[str, str]:
    return {
        "apikey": store.SUPABASE_KEY,
        "Authorization": f"Bearer {store.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def search(query: str, limit: int = 6) -> dict[str, Any]:
    """Meaning-based lookup. Returns matching passages with their source path."""
    if not configured():
        raise RuntimeError("Vault recall isn't set up (needs OPENAI_API_KEY and Supabase).")
    vector = embed([query])[0]
    resp = requests.post(
        f"{store.SUPABASE_URL}/rest/v1/rpc/match_vault_chunks",
        headers=_store_headers(),
        json={"query_embedding": vector, "match_count": max(1, min(limit, 12)),
              "min_similarity": MIN_SIMILARITY},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"vault search failed {resp.status_code}: {resp.text[:180]}")
    rows = resp.json() or []
    return {
        "query": query,
        "matches": [{"path": r["path"], "excerpt": r["content"][:900],
                     "similarity": round(float(r.get("similarity", 0)), 3)}
                    for r in rows],
        "note": ("Nothing in the vault is close to that." if not rows else
                 "Passages ranked by meaning, not exact wording."),
    }
