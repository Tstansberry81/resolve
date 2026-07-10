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

  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body: req.method === "POST" ? await req.text() : undefined,
    // never cache; SSE needs a live stream
    cache: "no-store",
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-cache",
    },
  });
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
