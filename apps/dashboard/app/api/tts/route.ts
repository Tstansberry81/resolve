import { NextResponse } from "next/server";

// Server-side proxy to ElevenLabs text-to-speech. The API key stays on the
// dashboard service (ELEVENLABS_API_KEY) and is never shipped to the browser —
// the client just POSTs text here and gets back audio/mpeg. If no key is set we
// return 501 so the client falls back to the browser voice.
//
// Env:
//   ELEVENLABS_API_KEY   — required to enable (free-tier key is fine)
//   ELEVENLABS_VOICE_ID  — default "onwK4e9ZLuTAKqWW03F9" (Daniel, British male)
//   ELEVENLABS_MODEL     — default "eleven_turbo_v2_5" (natural + low latency)
//   ELEVENLABS_SPEED     — speaking rate 0.7–1.2 (default 1.05, natural)
//
// We hit the /stream endpoint and pass the audio straight through as a chunked
// response, so the browser can start playing before the whole clip is generated
// (lower time-to-first-audio). optimize_streaming_latency trades a hair of
// quality for a faster first chunk.

export const runtime = "nodejs";

const DEFAULT_VOICE = "onwK4e9ZLuTAKqWW03F9"; // Daniel — deep British male, Jarvis-ish
// turbo v2_5: far more natural than flash, still real-time (~250ms). Same
// per-character cost. Override with ELEVENLABS_MODEL.
const DEFAULT_MODEL = "eleven_turbo_v2_5";
// ElevenLabs speaking rate (voice_settings.speed). 1.0 = normal; range 0.7–1.2.
// 1.05 = a touch brisk but still natural/human (1.14 sounded rushed). Override
// with ELEVENLABS_SPEED.
const SPEED = Math.min(1.2, Math.max(0.7, Number(process.env.ELEVENLABS_SPEED || "1.05")));
// 0..4; higher = faster first chunk, slightly less consistent prosody.
const STREAM_LATENCY = Math.min(4, Math.max(0, Number(process.env.ELEVENLABS_STREAM_LATENCY || "3")));

export async function POST(req: Request) {
  const key = process.env.ELEVENLABS_API_KEY;
  if (!key) {
    return new NextResponse("ElevenLabs not configured", { status: 501 });
  }

  let text = "";
  try {
    ({ text } = await req.json());
  } catch {
    /* bad body */
  }
  text = (text ?? "").toString().slice(0, 800).trim();
  if (!text) return new NextResponse("empty", { status: 400 });

  const voiceId = process.env.ELEVENLABS_VOICE_ID || DEFAULT_VOICE;
  const model = process.env.ELEVENLABS_MODEL || DEFAULT_MODEL;

  let r: Response;
  try {
    r = await fetch(
      `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}/stream` +
        `?output_format=mp3_44100_128&optimize_streaming_latency=${STREAM_LATENCY}`,
      {
        method: "POST",
        headers: {
          "xi-api-key": key,
          "Content-Type": "application/json",
          Accept: "audio/mpeg",
        },
        body: JSON.stringify({
          text,
          model_id: model,
          // Tuned for a natural, steady, human read: mid stability so it's
          // expressive without wavering, a little style for inflection, speaker
          // boost for presence.
          voice_settings: {
            stability: 0.5,
            similarity_boost: 0.8,
            style: 0.35,
            use_speaker_boost: true,
            speed: SPEED,
          },
        }),
      },
    );
  } catch (e) {
    return new NextResponse(`ElevenLabs unreachable: ${e}`, { status: 502 });
  }

  if (!r.ok || !r.body) {
    const detail = await r.text().catch(() => "");
    return new NextResponse(`ElevenLabs error ${r.status}: ${detail.slice(0, 200)}`, {
      status: 502,
    });
  }

  // Pass the chunked audio straight through so the client plays as it arrives.
  return new NextResponse(r.body, {
    status: 200,
    headers: {
      "Content-Type": "audio/mpeg",
      "Cache-Control": "no-store",
      "Transfer-Encoding": "chunked",
    },
  });
}
