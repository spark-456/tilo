import test from "node:test";
import assert from "node:assert/strict";
import { appendEvent, canonicalEvent, MAX_EVENTS } from "../recording.js";

test("SKILL_REPLAY extension strips URL credentials, query, and fragment", () => {
  const event = canonicalEvent({ kind: "navigate", url: "https://person:pw@example.test/path?token=hidden#private" }, 1);
  assert.equal(event.url, "https://example.test/path");
});

test("SKILL_REPLAY extension drops credential fields and masks sensitive text", () => {
  const blocked = canonicalEvent({ kind: "type", url: "https://example.test", safe_text: false, value: "secret" }, 1);
  const accepted = canonicalEvent({ kind: "type", url: "https://example.test", safe_text: true,
    value: "user@example.test", target: "Search" }, 1);
  assert.equal(blocked.value, null);
  assert.equal(accepted.value, "[masked]");
});

test("SKILL_REPLAY extension rejects unsupported schemes and caps recordings", () => {
  assert.equal(canonicalEvent({ kind: "navigate", url: "file:///private" }, 1), null);
  let events = [];
  for (let i = 0; i < MAX_EVENTS + 1; i++) events = appendEvent(events, { kind: "click", url: "https://example.test" });
  assert.equal(events.length, MAX_EVENTS);
  assert.deepEqual(events.map((event) => event.sequence), Array.from({ length: MAX_EVENTS }, (_, i) => i + 1));
});
