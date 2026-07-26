"""Attachments — turning what Trav SENDS RESOLVE (photos, screenshots, PDFs,
voice notes) into Anthropic content blocks the assistant can actually reason over.

Before this, the Telegram webhook dropped every non-text update on the floor
(`if not text: ignored`), so a screenshot of an error, a receipt, or a voice note
got silence. RESOLVE was blind and deaf.

Cost discipline, because attachments are the one input that can get expensive fast:

- Images. Anthropic downsizes anything over ~1568px on the long edge for the
  standard tier and 2576px for the high-res tier (Opus 5 is high-res), and you're
  billed on what it *keeps*, not what you sent. So pixels past the cap are money
  for nothing. Telegram pre-generates several sizes of every photo, so we pick the
  biggest one that still fits under the cap instead of resizing — no Pillow
  dependency, no CPU, no re-encode, and no quality lost (we take the largest
  legible size, never a thumbnail).
- Voice. whisper-1 at ~$0.006/min. A 30-second note costs a third of a cent, and
  the text it produces is far cheaper for the assistant to read than audio would be.
- PDFs. Passed through as document blocks; Claude does the page rendering.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

# Long-edge pixel cap. Opus 5 is the high-res tier (2576px, up to ~4784 image
# tokens); anything larger is downsized server-side, so sending it is waste.
MAX_EDGE = 2576
# Telegram's Bot API refuses to serve downloads over 20MB. Stay under it so a
# huge file fails with our clear message instead of a confusing 400 from them.
MAX_BYTES = 15 * 1024 * 1024

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
# Telegram sends .jpg photos with no mime_type at all; assume jpeg for those.
DEFAULT_PHOTO_MIME = "image/jpeg"

_FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
_BOT_API = "https://api.telegram.org/bot{token}/{method}"


class MediaError(Exception):
    """An attachment we understood but could not use — the message explains why
    in plain language, because it gets shown to Trav rather than logged."""


def describe(atts: list[dict[str, Any]]) -> str:
    """One short phrase for the activity feed and the conversation history, e.g.
    'a photo' or '2 photos and a voice note'. History keeps the phrase instead of
    the image so follow-up turns don't re-upload (and re-bill) the same picture."""
    counts: dict[str, int] = {}
    for a in atts:
        counts[a["kind"]] = counts.get(a["kind"], 0) + 1
    words = {"photo": "photo", "document": "file", "voice": "voice note"}
    parts = []
    for kind, n in counts.items():
        word = words.get(kind, kind)
        parts.append(f"{n} {word}s" if n > 1 else f"a {word}")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def from_telegram(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull attachment descriptors out of a Telegram message. Descriptors only —
    no downloading here, so the webhook can decide whether to act before it
    spends bandwidth."""
    atts: list[dict[str, Any]] = []

    photos = msg.get("photo") or []
    if photos:
        atts.append({"kind": "photo", "file_id": _best_photo(photos)["file_id"],
                     "mime": DEFAULT_PHOTO_MIME, "name": "photo.jpg"})

    doc = msg.get("document") or {}
    if doc.get("file_id"):
        atts.append({"kind": "document", "file_id": doc["file_id"],
                     "mime": (doc.get("mime_type") or "").lower(),
                     "name": doc.get("file_name") or "file"})

    # voice = the mic-button note; audio = a music/audio file share. Both transcribe.
    for key in ("voice", "audio"):
        item = msg.get(key) or {}
        if item.get("file_id"):
            mime = (item.get("mime_type") or "audio/ogg").lower()
            atts.append({"kind": "voice", "file_id": item["file_id"], "mime": mime,
                         # Whisper infers the codec from the extension, so a shared
                         # mp3 must not be handed over named .ogg.
                         "name": item.get("file_name") or f"voice.{_audio_ext(mime)}",
                         "duration": item.get("duration")})

    return atts


def _audio_ext(mime: str) -> str:
    """File extension Whisper will recognise for a Telegram audio mime type."""
    return {
        "audio/ogg": "ogg", "audio/opus": "ogg", "audio/oga": "oga",
        "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/mp4": "m4a",
        "audio/m4a": "m4a", "audio/x-m4a": "m4a", "audio/wav": "wav",
        "audio/x-wav": "wav", "audio/webm": "webm", "audio/flac": "flac",
    }.get(mime, "ogg")


def _best_photo(sizes: list[dict[str, Any]]) -> dict[str, Any]:
    """Largest Telegram-generated size whose long edge still fits under the cap.

    Telegram ships every photo at several resolutions. Taking the biggest one
    outright would often exceed MAX_EDGE and pay for pixels Anthropic discards;
    taking the smallest would throw away detail we need to read an error message
    off a screenshot. The biggest one *under* the cap is free quality.
    """
    if not sizes:
        raise MediaError("Telegram sent a photo with no usable size.")
    ordered = sorted(sizes, key=lambda s: max(s.get("width", 0), s.get("height", 0)))
    fitting = [s for s in ordered if max(s.get("width", 0), s.get("height", 0)) <= MAX_EDGE]
    if fitting:
        return fitting[-1]
    # Nothing fits (a huge panorama): send the smallest — Anthropic downsizes it
    # to the same thing the bigger ones would become, so this is the cheap path
    # to an identical result.
    return ordered[0]


def download(file_id: str) -> bytes:
    """Fetch an attachment's bytes through the Bot API's two-step file flow."""
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise MediaError("TELEGRAM_TOKEN isn't set, so I can't download that.")
    meta = requests.get(_BOT_API.format(token=token, method="getFile"),
                        params={"file_id": file_id}, timeout=20)
    meta.raise_for_status()
    payload = meta.json()
    if not payload.get("ok"):
        raise MediaError("Telegram wouldn't hand over that file.")
    path = payload["result"].get("file_path")
    size = payload["result"].get("file_size") or 0
    if size > MAX_BYTES:
        raise MediaError(f"That file is {size // (1024 * 1024)}MB — too big for me to read "
                         f"(limit is {MAX_BYTES // (1024 * 1024)}MB).")
    blob = requests.get(_FILE_API.format(token=token, path=path), timeout=60)
    blob.raise_for_status()
    if len(blob.content) > MAX_BYTES:
        raise MediaError("That file came back bigger than I can read.")
    return blob.content


def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    """Voice note -> text via whisper-1 (~$0.006/min).

    Transcribing up front rather than handing audio to the assistant is both the
    cheap path and the accurate one: the text is a fraction of the tokens, and it
    lands in the vault log and the activity feed as something readable later.
    """
    if not os.getenv("OPENAI_API_KEY"):
        raise MediaError("Voice needs OPENAI_API_KEY set — it isn't.")
    from openai import OpenAI

    stream = io.BytesIO(audio)
    stream.name = filename  # the SDK infers the audio format from the filename
    result = OpenAI().audio.transcriptions.create(model="whisper-1", file=stream)
    text = (getattr(result, "text", "") or "").strip()
    if not text:
        raise MediaError("I couldn't make out any words in that.")
    return text


def to_blocks(atts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Descriptors -> (Anthropic content blocks, notes).

    Notes are plain-language lines for Trav: voice transcripts (so he sees what I
    heard) and per-attachment failures. One bad attachment never sinks the rest —
    a broken PDF alongside a readable photo still gets the photo through.
    """
    blocks: list[dict[str, Any]] = []
    notes: list[str] = []

    for att in atts:
        try:
            raw = download(att["file_id"])
            kind, mime = att["kind"], att.get("mime") or ""

            if kind == "voice":
                notes.append(f'Voice note, transcribed: "{transcribe(raw, att["name"])}"')
                continue

            if kind == "photo" or mime in IMAGE_TYPES:
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64",
                               "media_type": mime if mime in IMAGE_TYPES else DEFAULT_PHOTO_MIME,
                               "data": base64.b64encode(raw).decode("ascii")},
                })
                continue

            if mime == "application/pdf":
                blocks.append({
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf",
                               "data": base64.b64encode(raw).decode("ascii")},
                })
                continue

            # Plain-text-ish files are cheaper and clearer inline than as documents.
            if mime.startswith("text/") or mime in ("application/json", "application/xml"):
                body = raw.decode("utf-8", "replace")[:100_000]
                blocks.append({"type": "text",
                               "text": f"--- contents of {att['name']} ---\n{body}"})
                continue

            notes.append(f"I can't read {att['name']} ({mime or 'unknown type'}) — "
                         "send an image, PDF, or text file.")
        except MediaError as exc:
            notes.append(str(exc))
        except Exception:
            log.exception("attachment failed: %s", att.get("name"))
            notes.append(f"Something went wrong reading {att.get('name', 'that file')}.")

    return blocks, notes
