import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { GATE_COOKIE, gateToken } from "@/lib/gate";

export async function middleware(req: NextRequest) {
  const cookie = req.cookies.get(GATE_COOKIE)?.value;
  if (cookie && cookie === (await gateToken())) {
    return NextResponse.next();
  }
  const url = req.nextUrl.clone();
  url.pathname = "/gate";
  url.search = "";
  return NextResponse.redirect(url);
}

export const config = {
  // everything is gated except the gate itself and framework assets
  matcher: ["/((?!gate|api/gate|_next/static|_next/image|favicon.ico).*)"],
};
