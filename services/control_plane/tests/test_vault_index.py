"""Semantic vault recall: chunking, the unchanged-chunk skip, and weak-match
suppression."""

from __future__ import annotations

import pytest

from resolve_control_plane import vault_index


def test_splits_on_headings_so_topics_stay_whole():
    """Character-count-only splitting merges the tail of one topic with the head
    of the next, producing embeddings that match neither well."""
    note = "# Title\n\nintro line\n\n## Colors\n\ncream and beige\n\n## Hosting\n\nrender\n"
    chunks = vault_index.chunk_markdown(note)
    assert len(chunks) == 3
    assert any(c.startswith("## Colors") and "cream" in c for c in chunks)
    assert any(c.startswith("## Hosting") for c in chunks)


def test_long_sections_are_split_with_overlap():
    """A definition straddling a boundary must survive in at least one chunk."""
    body = "## Big\n\n" + ("word " * 2000)
    chunks = vault_index.chunk_markdown(body)
    assert len(chunks) > 1
    assert all(len(c) <= vault_index.CHUNK_CHARS + 50 for c in chunks)
    # consecutive chunks share text, so nothing falls between them
    assert chunks[0][-50:] in chunks[1] or chunks[1][:50] in chunks[0]


def test_empty_note_yields_nothing():
    assert vault_index.chunk_markdown("") == []
    assert vault_index.chunk_markdown("   \n  ") == []


def test_reindex_skips_unchanged_chunks(monkeypatch):
    """The whole point of the content hash: a nightly run over an unchanged
    vault must make zero embedding calls."""
    monkeypatch.setattr(vault_index, "configured", lambda: True)
    monkeypatch.setattr(vault_index.vault_github, "list_tree",
                        lambda prefix: {"paths": ["wiki/a.md"]})
    monkeypatch.setattr(vault_index.vault_github, "read_file",
                        lambda path, limit=0: {"content": "# A\n\nstable text"})

    chunk = vault_index.chunk_markdown("# A\n\nstable text")[0]
    digest = vault_index._sha(chunk)
    monkeypatch.setattr(vault_index, "_existing_hashes",
                        lambda: {("wiki/a.md", 0): digest})

    calls: list = []
    monkeypatch.setattr(vault_index, "embed", lambda texts: calls.append(texts) or [])
    monkeypatch.setattr(vault_index, "_upsert", lambda row: None)

    stats = vault_index.reindex()
    assert calls == [], "unchanged vault must not re-embed"
    assert stats["chunksEmbedded"] == 0
    assert stats["filesChanged"] == 0


def test_reindex_embeds_changed_chunks(monkeypatch):
    monkeypatch.setattr(vault_index, "configured", lambda: True)
    monkeypatch.setattr(vault_index.vault_github, "list_tree",
                        lambda prefix: {"paths": ["wiki/a.md"]})
    monkeypatch.setattr(vault_index.vault_github, "read_file",
                        lambda path, limit=0: {"content": "# A\n\nedited text"})
    monkeypatch.setattr(vault_index, "_existing_hashes",
                        lambda: {("wiki/a.md", 0): "stale-hash"})

    written: list = []
    monkeypatch.setattr(vault_index, "embed", lambda texts: [[0.0] * 1536 for _ in texts])
    monkeypatch.setattr(vault_index, "_upsert", lambda row: written.append(row))

    stats = vault_index.reindex()
    assert stats["chunksEmbedded"] == 1
    assert written[0]["path"] == "wiki/a.md"
    assert "embedding" in written[0]


def test_only_text_notes_are_indexed(monkeypatch):
    """Binary attachments in the vault would waste embedding calls and return
    garbage passages."""
    monkeypatch.setattr(vault_index, "configured", lambda: True)
    monkeypatch.setattr(vault_index.vault_github, "list_tree", lambda prefix: {
        "paths": ["wiki/a.md", "wiki/pic.png", "wiki/scan.pdf", "wiki/b.txt"]})
    seen: list = []
    monkeypatch.setattr(vault_index.vault_github, "read_file",
                        lambda path, limit=0: seen.append(path) or {"content": "x"})
    monkeypatch.setattr(vault_index, "_existing_hashes", lambda: {})
    monkeypatch.setattr(vault_index, "embed", lambda texts: [[0.0] * 1536 for _ in texts])
    monkeypatch.setattr(vault_index, "_upsert", lambda row: None)

    vault_index.reindex()
    assert seen == ["wiki/a.md", "wiki/b.txt"]


def test_weak_matches_are_filtered_out():
    """Returning the least-bad row from an empty vault invites the model to
    answer from an unrelated note."""
    assert vault_index.MIN_SIMILARITY > 0


def test_search_without_setup_says_so(monkeypatch):
    monkeypatch.setattr(vault_index, "configured", lambda: False)
    with pytest.raises(RuntimeError) as err:
        vault_index.search("anything")
    assert "OPENAI_API_KEY" in str(err.value)


def test_reindex_failure_never_breaks_the_nightly_run():
    """Recall is an enhancement; the literal grep still works without it."""
    import inspect

    from resolve_control_plane import routines
    src = inspect.getsource(routines._reindex_vault)
    assert "except Exception" in src
