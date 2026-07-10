// Tiny password gate shared by middleware and the /api/gate route.
// Override the password on Render with RESOLVE_GATE_PASSWORD; the cookie
// stores a hash of the password, never the password itself.

export const GATE_COOKIE = "resolve_gate";

export function gatePassword(): string {
  return process.env.RESOLVE_GATE_PASSWORD ?? "resolve1975*";
}

export async function gateToken(): Promise<string> {
  const data = new TextEncoder().encode(`resolve-gate-v1:${gatePassword()}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
