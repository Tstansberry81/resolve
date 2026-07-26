// Delivery guard for the laptop agent loop.
//
// The case that motivated this is verbatim from a real run: the agent browsed
// UVA's library site, then ended its turn with "Let me compile ... Let me
// create the writeup now:" and never called write_file. The loop broke on the
// no-tool-call turn, that promise became the summary, and the cloud logged
// "Local task complete". Nothing was written and the dock stayed silent.
//
// Run: node --test apps/local-worker/guard.test.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
import { needsAction, PROMISED_FILE_RE } from "./worker.mjs";

// the actual text from the failed run
const REAL_STALL = `Perfect! Now I have enough research. Let me compile all the information I've gathered and write a comprehensive markdown file about the best study spots at UVA for finals week. Based on my research, I've found:

1. **Clemons Library** - Central location, extended hours, quiet floors, food access
2. **Brown Science & Engineering Library (Clark Hall)** - Popular for STEM students, extended finals hours, quiet study spaces
3. **Shannon Library** - Extended hours during finals, large humanities/social sciences collection, comfortable seating, food available nearby
4. **Off-campus options**: Grit Coffee (highly praised by students), Camellias Coffee & Tea (newer, great atmosphere), Shenandoah Joe

Let me create the writeup now:`;

test("the real stall is caught as a promised-file-never-written", () => {
  // It carries genuine findings, so the body-length rule alone (correctly) lets
  // it through — the file promise is what makes it a failure, and that only
  // holds because it can be checked against filesWritten === 0.
  assert.equal(PROMISED_FILE_RE.test(REAL_STALL), true);
});

test("bare promises are caught with no file check needed", () => {
  for (const t of [
    "Let me compile this into a summary and save it.",
    "I'll research that and write it up for you.",
    "Now I'll put together the final answer.",
    "",
  ]) {
    assert.equal(needsAction(t), true, JSON.stringify(t));
  }
});

test("real delivered output is not flagged", () => {
  for (const t of [
    "Clemons Library is open 24h during finals; Brown closes at 2am. Shannon has the quietest fourth floor.",
    "1819. UVA was founded by Thomas Jefferson.",
    "Okay, the file is at ~/resolve-workspace/notes.md and contains all three spots.",
  ]) {
    assert.equal(needsAction(t), false, JSON.stringify(t));
  }
});

test("a finished writeup signing off with a promise is not flagged", () => {
  const body = (
    "Clemons Library offers 24-hour access during finals with quiet floors and food nearby. " +
    "Brown Science and Engineering Library is the STEM favourite and extends its hours. " +
    "Shannon Library has the largest humanities collection and comfortable seating. "
  ).repeat(4); // parenthesised: .repeat binds to the whole body, not just the last line
  assert.ok(body.length > 600, "the fixture must exceed DELIVERED_MIN to test the rule");
  assert.equal(needsAction(body + "\nI'll save this to your vault."), false);
});

test("wall-to-wall narration is still flagged however long", () => {
  const t =
    "I'll start by searching the library site. ".repeat(6) +
    "Now I'm going to check the hours page. ".repeat(4) +
    "I need to look at one more source. Let me compile the summary now.";
  assert.equal(needsAction(t), true);
});

test("PROMISED_FILE_RE does not fire on ordinary prose", () => {
  for (const t of [
    "The library has a quiet reading room on the fourth floor.",
    "I read the Cavalier Daily article about study spots.",
  ]) {
    assert.equal(PROMISED_FILE_RE.test(t), false, JSON.stringify(t));
  }
});
