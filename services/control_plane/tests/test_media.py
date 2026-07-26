"""Attachments: photo-size selection, block building, and the Telegram webhook
path that used to drop every non-text message on the floor."""

from __future__ import annotations

import base64

import pytest

from resolve_control_plane import media


# --- photo size selection (the cost lever) ---------------------------------

def test_picks_largest_size_under_the_cap():
    """Not the biggest available — the biggest that Anthropic won't downsize,
    because pixels past the cap are billed and then discarded."""
    sizes = [
        {"file_id": "thumb", "width": 90, "height": 60},
        {"file_id": "mid", "width": 1280, "height": 853},
        {"file_id": "huge", "width": 4000, "height": 2667},
    ]
    assert media._best_photo(sizes)["file_id"] == "mid"


def test_picks_smallest_when_nothing_fits():
    """A panorama where every size is over the cap: they all downsize to the same
    thing, so take the cheapest one to upload."""
    sizes = [
        {"file_id": "big", "width": 3000, "height": 1000},
        {"file_id": "bigger", "width": 8000, "height": 2000},
    ]
    assert media._best_photo(sizes)["file_id"] == "big"


def test_exact_cap_still_fits():
    sizes = [{"file_id": "small", "width": 100, "height": 100},
             {"file_id": "cap", "width": media.MAX_EDGE, "height": 1000}]
    assert media._best_photo(sizes)["file_id"] == "cap"


# --- descriptor extraction --------------------------------------------------

def test_from_telegram_photo_and_caption():
    atts = media.from_telegram({
        "photo": [{"file_id": "a", "width": 90, "height": 60},
                  {"file_id": "b", "width": 800, "height": 600}],
        "caption": "what's wrong here",
    })
    assert len(atts) == 1
    assert atts[0]["kind"] == "photo"
    assert atts[0]["file_id"] == "b"


def test_from_telegram_voice_and_document():
    atts = media.from_telegram({
        "voice": {"file_id": "v1", "duration": 7, "mime_type": "audio/ogg"},
    })
    assert atts[0]["kind"] == "voice"

    atts = media.from_telegram({
        "document": {"file_id": "d1", "file_name": "lease.pdf",
                     "mime_type": "application/pdf"},
    })
    assert atts[0]["kind"] == "document"
    assert atts[0]["mime"] == "application/pdf"


def test_from_telegram_plain_text_has_no_attachments():
    assert media.from_telegram({"text": "hello"}) == []


def test_describe_reads_like_english():
    assert media.describe([{"kind": "photo"}]) == "a photo"
    assert media.describe([{"kind": "photo"}, {"kind": "photo"}]) == "2 photos"
    assert media.describe(
        [{"kind": "photo"}, {"kind": "voice"}]) == "a photo and a voice note"


# --- block building ---------------------------------------------------------

def test_image_becomes_a_base64_image_block(monkeypatch):
    monkeypatch.setattr(media, "download", lambda fid: b"\x89PNG-bytes")
    blocks, notes = media.to_blocks(
        [{"kind": "photo", "file_id": "x", "mime": "image/png", "name": "s.png"}])
    assert notes == []
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert base64.b64decode(blocks[0]["source"]["data"]) == b"\x89PNG-bytes"


def test_pdf_becomes_a_document_block(monkeypatch):
    monkeypatch.setattr(media, "download", lambda fid: b"%PDF-1.7")
    blocks, _ = media.to_blocks([{"kind": "document", "file_id": "x",
                                  "mime": "application/pdf", "name": "a.pdf"}])
    assert blocks[0]["type"] == "document"
    assert blocks[0]["source"]["media_type"] == "application/pdf"


def test_voice_is_transcribed_into_a_note_not_a_block(monkeypatch):
    """Transcribing up front is the cheap path — the assistant reads text, not audio."""
    monkeypatch.setattr(media, "download", lambda fid: b"OggS")
    monkeypatch.setattr(media, "transcribe", lambda raw, name="": "add milk to the list")
    blocks, notes = media.to_blocks(
        [{"kind": "voice", "file_id": "v", "mime": "audio/ogg", "name": "v.ogg"}])
    assert blocks == []
    assert "add milk to the list" in notes[0]


def test_one_bad_attachment_does_not_sink_the_others(monkeypatch):
    def flaky(fid):
        if fid == "bad":
            raise media.MediaError("That file is 40MB — too big for me to read.")
        return b"img"

    monkeypatch.setattr(media, "download", flaky)
    blocks, notes = media.to_blocks([
        {"kind": "photo", "file_id": "bad", "mime": "image/jpeg", "name": "big.jpg"},
        {"kind": "photo", "file_id": "ok", "mime": "image/jpeg", "name": "fine.jpg"},
    ])
    assert len(blocks) == 1          # the readable one still got through
    assert "too big" in notes[0]     # and Trav is told why the other didn't


def test_unsupported_type_explains_itself(monkeypatch):
    monkeypatch.setattr(media, "download", lambda fid: b"\x00\x01")
    blocks, notes = media.to_blocks([{"kind": "document", "file_id": "x",
                                      "mime": "application/zip", "name": "a.zip"}])
    assert blocks == []
    assert "a.zip" in notes[0]


def test_text_file_is_inlined_rather_than_uploaded(monkeypatch):
    monkeypatch.setattr(media, "download", lambda fid: b"line one\nline two")
    blocks, _ = media.to_blocks([{"kind": "document", "file_id": "x",
                                  "mime": "text/plain", "name": "notes.txt"}])
    assert blocks[0]["type"] == "text"
    assert "line two" in blocks[0]["text"]


# --- the webhook path that was dropping these entirely ----------------------

@pytest.fixture
def webhook(monkeypatch):
    """Webhook wired to a stub run_and_reply, so we can assert what got queued."""
    from resolve_control_plane import api

    monkeypatch.setattr(api, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    captured: dict = {}

    async def fake_run(chat_id, text, atts=None):
        captured.update(chat_id=chat_id, text=text, atts=atts)

    monkeypatch.setattr(api, "_run_and_reply", fake_run)
    return api, captured


def _msg(**kw):
    return {"message": {"chat": {"id": 42}, **kw}}


async def _post(api, update):
    """Call the webhook and let the detached task actually start. The handler
    dispatches with create_task so Telegram isn't held on the line, so the work
    hasn't begun by the time the response returns."""
    import asyncio

    result = await api.telegram_webhook(update)
    await asyncio.sleep(0)
    return result


@pytest.mark.anyio
async def test_photo_with_no_caption_is_acted_on(webhook):
    """The regression this whole feature exists for: a bare screenshot used to
    return `ignored: no text`."""
    api, captured = webhook
    result = await _post(api,
        _msg(photo=[{"file_id": "p1", "width": 800, "height": 600}]))
    assert result["ok"] and result["queued"]
    assert result["attachments"] == 1
    assert captured["atts"][0]["file_id"] == "p1"
    assert captured["text"]  # a synthesized instruction, not an empty prompt


@pytest.mark.anyio
async def test_photo_caption_needs_no_resolve_prefix(webhook):
    api, captured = webhook
    await _post(api,
        _msg(photo=[{"file_id": "p1", "width": 800, "height": 600}],
             caption="what does this error mean"))
    assert captured["text"] == "what does this error mean"


@pytest.mark.anyio
async def test_voice_note_is_queued(webhook):
    api, captured = webhook
    result = await _post(api,
        _msg(voice={"file_id": "v1", "duration": 4, "mime_type": "audio/ogg"}))
    assert result["queued"]
    assert captured["atts"][0]["kind"] == "voice"


@pytest.mark.anyio
async def test_bare_text_still_requires_the_command_prefix(webhook):
    """Attachments imply intent; idle chatter must not fire a paid model run."""
    api, captured = webhook
    result = await _post(api, _msg(text="hey"))
    assert result["ignored"] == "not a command"
    assert not captured


@pytest.mark.anyio
async def test_resolve_prefix_still_works(webhook):
    api, captured = webhook
    await _post(api, _msg(text="/resolve what's on my calendar"))
    assert captured["text"] == "what's on my calendar"
    assert captured["atts"] == []


@pytest.mark.anyio
async def test_attachment_from_a_stranger_is_refused_before_any_download(webhook):
    """The allowlist has to come first — downloads and transcription cost money."""
    api, captured = webhook
    result = await _post(api,
        {"message": {"chat": {"id": 999}, "photo": [{"file_id": "p", "width": 9, "height": 9}]}})
    assert result["ignored"] == "chat not allowed"
    assert not captured
