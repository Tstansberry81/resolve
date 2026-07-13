import { NextResponse } from "next/server";

// Server-side proxy to ElevenLabs speech-to-text (Scribe). The browser records
// mic audio and POSTs it here as multipart/form-data; we forward to ElevenLabs
// with the key kept server-side (ELEVENLABS_API_KEY) and return { text }.
//
// This is what lets voice work inside the Electron desktop app: Chromium's
// Web Speech API (webkitSpeechRecognition) can't transcribe in Electron, so we
// do the transcription server-side instead.
//
// Env:
//   ELEVENLABS_API_KEY  — required
//   ELEVENLABS_STT_MODEL — default "scribe_v1"

export const runtime = "nodejs";

const DEFAULT_MODEL = "scribe_v1";

export async function POST(req: Request) {
  const key = process.env.ELEVENLABS_API_KEY;
  if (!key) {
    return NextResponse.json({ error: "ElevenLabs not configured" }, { status: 501 });
  }

  let inbound: FormData;
  try {
    inbound = await req.formData();
  } catch {
    return NextResponse.json({ error: "expected multipart/form-data" }, { status: 400 });
  }
  const audio = inbound.get("audio");
  if (!(audio instanceof Blob) || audio.size === 0) {
    return NextResponse.json({ error: "no audio" }, { status: 400 });
  }
  // guard against absurd uploads (~1 min of opus is well under this)
  if (audio.size > 8_000_000) {
    return NextResponse.json({ error: "audio too large" }, { status: 413 });
  }

  const model = process.env.ELEVENLABS_STT_MODEL || DEFAULT_MODEL;
  const form = new FormData();
  form.append("file", audio, "speech.webm");
  form.append("model_id", model);
  form.append("language_code", "en");

  let r: Response;
  try {
    r = await fetch("https://api.elevenlabs.io/v1/speech-to-text", {
      method: "POST",
      headers: { "xi-api-key": key },
      body: form,
    });
  } catch (e) {
    return NextResponse.json({ error: `ElevenLabs unreachable: ${e}` }, { status: 502 });
  }

  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    return NextResponse.json(
      { error: `ElevenLabs STT ${r.status}: ${detail.slice(0, 200)}` },
      { status: 502 },
    );
  }

  const data = (await r.json().catch(() => ({}))) as { text?: string };
  return NextResponse.json({ text: (data.text ?? "").trim() });
}
