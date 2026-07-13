import { NextResponse } from "next/server";

// Server-side proxy to ElevenLabs text-to-speech. The API key stays on the
// dashboard service (ELEVENLABS_API_KEY) and is never shipped to the browser —
// the client just POSTs text here and gets back audio/mpeg. If no key is set we
// return 501 so the client falls back to the browser voice.
//
// Env:
//   ELEVENLABS_API_KEY   — required to enable (free-tier key is fine)
//   ELEVENLABS_VOICE_ID  — default "onwK4e9ZLuTAKqWW03F9" (Daniel, British male)
//   ELEVENLABS_MODEL     — default "eleven_turbo_v2_5" (low latency)

export const runtime = "nodejs";

const DEFAULT_VOICE = "onwK4e9ZLuTAKqWW03F9"; // Daniel — deep British male, Jarvis-ish
const DEFAULT_MODEL = "eleven_turbo_v2_5";
// ElevenLabs speaking rate (voice_settings.speed). 1.0 = normal; range 0.7–1.2.
// Bumped a touch so RESOLVE talks faster. Override with ELEVENLABS_SPEED.
const SPEED = Math.min(1.2, Math.max(0.7, Number(process.env.ELEVENLABS_SPEED || "1.14")));

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
      `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}?output_format=mp3_44100_128`,
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
          voice_settings: {
            stability: 0.45,
            similarity_boost: 0.8,
            style: 0.0,
            use_speaker_boost: true,
            speed: SPEED,
          },
        }),
      },
    );
  } catch (e) {
    return new NextResponse(`ElevenLabs unreachable: ${e}`, { status: 502 });
  }

  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    return new NextResponse(`ElevenLabs error ${r.status}: ${detail.slice(0, 200)}`, {
      status: 502,
    });
  }

  const audio = await r.arrayBuffer();
  return new NextResponse(audio, {
    status: 200,
    headers: { "Content-Type": "audio/mpeg", "Cache-Control": "no-store" },
  });
}
