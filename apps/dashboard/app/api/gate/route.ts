import { NextResponse } from "next/server";
import { GATE_COOKIE, gatePassword, gateToken } from "@/lib/gate";

export async function POST(req: Request) {
  const { password } = await req
    .json()
    .catch(() => ({ password: "" }) as { password: string });

  if (password !== gatePassword()) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set(GATE_COOKIE, await gateToken(), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: 60 * 60 * 24 * 30, // 30 days
    path: "/",
  });
  return res;
}
