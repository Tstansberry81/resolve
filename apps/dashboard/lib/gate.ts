// Tiny password gate shared by middleware and the /api/gate route.
// Override the password on Render with RESOLVE_GATE_PASSWORD; the cookie
// stores a hash of the password, never the password itself.
//
// The hash folds in GATE_SECRET (a server-only random value), so the cookie
// can't be forged from the password alone — even someone reading this source
// and knowing the password can't mint a valid cookie without the server
// secret. Set GATE_SECRET on Render to a long random string. All of these are
// server-only (process.env in a non-"use client" module never reaches the
// browser bundle), so nothing here ships to the client.

export const GATE_COOKIE = "resolve_gate";

export function gatePassword(): string {
  return process.env.RESOLVE_GATE_PASSWORD ?? "resolve1975*";
}

function gateSecret(): string {
  // Falls back to the password so the gate still works before GATE_SECRET is
  // set; setting it is what makes the cookie unforgeable.
  return process.env.GATE_SECRET ?? gatePassword();
}

export async function gateToken(): Promise<string> {
  const data = new TextEncoder().encode(
    `resolve-gate-v2:${gateSecret()}:${gatePassword()}`,
  );
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
