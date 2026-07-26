# Operator brief — starter template

Copy this into your vault as **`wiki/RESOLVE.md`**. RESOLVE loads it into its system
prompt on every turn, so it starts each conversation already knowing what your
shorthand means. Edit it in Obsidian whenever you like — changes show up within
about five minutes, no redeploy.

**RESOLVE cannot write to this file.** It's loaded with operator authority, so a
writable brief would let a prompt-injected email rewrite RESOLVE's own instructions.
Only you edit it.

Keep it under ~8000 characters. Past that it gets truncated, and it's riding in
every single request — so write the things that stop it guessing, not everything
you know.

The rule of thumb: **if you've ever had to explain it twice, it belongs here.**

---

```markdown
# RESOLVE operator brief

## Who I am
- Trav Stansberry. Student at UVA.
- Timezone America/New_York. Assume it unless I say otherwise.

## My projects — what I mean when I name one
<!-- The highest-value section. One line each: the name I say, then where it lives. -->
- **RESOLVE** — this system. Repo `~/claude/resolve`, GitHub `Tstansberry81/resolve`,
  deployed on Render. Dashboard at resolve-1-889i.onrender.com.
- **the foundation site / mom's website / Meet You There** — the nonprofit site.
  Folder `~/Desktop/moms website`. Flask. White + beige, login-gated portal.
- **the vault / my second brain** — Obsidian, GitHub repo `Tstansberry81/vault`.
  Notes under `wiki/`, sources under `raw/` (never edit raw/).
- **kalshi bot** — `~/Desktop/kalshi-bot`.
- **polymarket / copytrade** — `~/Desktop/polymarket-copytrade`.
- **HWBUDDY** — `~/Desktop/HWBUDDY`.
- **the calculator** — `~/Desktop/college acceptance calculator`.
<!-- Delete what's dead, add what's missing. If I say a name that isn't here, ask. -->

## Files and docs I refer to often
<!-- Name -> exact Google Doc/Sheet, or the vault path. Saves a Drive search and a wrong guess. -->
- **my budget / the budget sheet** —
- **the tracker** —
- **class notes** —

## People
<!-- First names I use, and who they actually are. Include email if you'd ever have me draft to them. -->
- **Mom** —
- **Dad** —

## School
- University of Virginia. Canvas due dates come from the calendar feed.
- Current courses:
- For grades or whether something was submitted, open Canvas in my browser —
  the feed only has due dates.

## How I want things handled
<!-- Preferences that have annoyed you before. Be blunt. -->
- Default to drafting emails, not sending them.
- Save substantial writeups to the vault unless I name a Google Doc.
- Don't ask permission for small reversible things — just do it and tell me.
- When you're unsure which project I mean, ask instead of guessing.
- Money: my accounts are read-only. Never suggest a transfer or a trade.

## Recurring context
<!-- Standing facts that change how you answer. -->
- I'm usually at:
- I drive to:
- My laptop worker is only online when my Mac is awake — if it's offline, say so
  rather than silently failing.
```

---

## What makes this work

The section that pays for itself immediately is **projects**. "Fix the login on the
foundation site" currently sends RESOLVE hunting; with one line it goes straight to
`~/Desktop/moms website`.

Second most valuable is **files** — a named Google Doc or Sheet turns a fuzzy Drive
search into a direct edit.

Leave a section empty rather than inventing content. An empty heading costs a few
tokens; a wrong path sends RESOLVE confidently to the wrong place, which is worse
than it having no idea.
