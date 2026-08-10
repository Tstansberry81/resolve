// Server-side proxy to the control plane. Keeps CP_TOKEN off the client and
// rides behind the password-gate middleware (this route is cookie-protected).
// Streams bodies through, so SSE from /v1/events works transparently.

import { NextRequest } from "next/server";

const CP_URL = (process.env.CONTROL_PLANE_URL ?? "").replace(/\/$/, "");
const CP_TOKEN = process.env.CP_TOKEN ?? "";

export const dynamic = "force-dynamic";

async function proxy(req: NextRequest, path: string[]): Promise<Response> {
  if (!CP_URL) {
    return Response.json({ error: "CONTROL_PLANE_URL not configured" }, { status: 503 });
  }
  const target = `${CP_URL}/${path.join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = {};
  if (CP_TOKEN) headers["Authorization"] = `Bearer ${CP_TOKEN}`;
  const contentType = req.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "POST" ? await req.text() : undefined,
      // never cache; SSE needs a live stream
      cache: "no-store",
      // client hangs up -> drop the upstream socket instead of leaking it
      signal: req.signal,
    });
  } catch (err) {
    // Cold start, redeploy, or a reset before headers. A down control plane has
    // to read as OFFLINE in the header, not take the whole dashboard with it.
    return Response.json(
      { error: "control plane unreachable", detail: String(err) },
      { status: 502 },
    );
  }

  const upstreamType = upstream.headers.get("content-type") ?? "application/json";
  const outHeaders: Record<string, string> = {
    "Content-Type": upstreamType,
    "Cache-Control": "no-cache, no-transform",
  };
  // keep intermediaries from buffering the stream and swallowing keepalives
  if (upstreamType.includes("text/event-stream")) outHeaders["X-Accel-Buffering"] = "no";

  if (!upstream.body) {
    return new Response(null, { status: upstream.status, headers: outHeaders });
  }

  // Re-pipe by hand rather than handing `upstream.body` to Response directly.
  // On a mid-stream ECONNRESET the direct handoff throws "failed to pipe
  // response", which 500s the route -- and EventSource just reconnects into the
  // same wall. Ending the stream quietly instead lets the client's own
  // reconnect (liveEngine onerror -> offline -> retry) do its job.
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      const reader = upstream.body!.getReader();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          controller.enqueue(value);
        }
      } catch {
        // upstream died mid-stream: close cleanly, never throw
      } finally {
        try {
          controller.close();
        } catch {
          // already closed or cancelled by the client
        }
        reader.releaseLock();
      }
    },
    cancel() {
      void upstream.body?.cancel();
    },
  });

  return new Response(body, { status: upstream.status, headers: outHeaders });
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, (await params).path);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  return proxy(req, (await params).path);
}
