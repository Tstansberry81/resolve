import { NextResponse } from "next/server";

// Mints a short-lived single-use token for the browser to open the ElevenLabs
// realtime STT (Scribe v2) WebSocket directly — without ever seeing the API key.
// Browsers can't set custom WS headers, so the key must stay here and the client
// authenticates the socket with this token (auto-expires in ~15 min). If no key
// is configured we return 501 and the client falls back to batch STT.
//
// Env: ELEVENLABS_API_KEY — required.

export const runtime = "nodejs";

export async function POST() {
  const key = process.env.ELEVENLABS_API_KEY;
  if (!key) {
    return NextResponse.json({ error: "ElevenLabs not configured" }, { status: 501 });
  }

  let r: Response;
  try {
    r = await fetch("https://api.elevenlabs.io/v1/single-use-token/realtime_scribe", {
      method: "POST",
      headers: { "xi-api-key": key },
    });
  } catch (e) {
    return NextResponse.json({ error: `ElevenLabs unreachable: ${e}` }, { status: 502 });
  }

  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    return NextResponse.json(
      { error: `scribe-token ${r.status}: ${detail.slice(0, 200)}` },
      { status: 502 },
    );
  }

  const data = (await r.json().catch(() => ({}))) as { token?: string };
  if (!data.token) {
    return NextResponse.json({ error: "no token in response" }, { status: 502 });
  }
  return NextResponse.json({ token: data.token });
}
