import test from "node:test";
import assert from "node:assert/strict";
import { appendEvent, canonicalEvent, MAX_EVENTS } from "../recording.js";

for (const transition of ["stop", "start"]) {
  test(`SKILL_REPLAY ${transition} cannot be overwritten by queued old events`, async () => {
    const originalChrome = globalThis.chrome;
    try {
      let state = { active: true, id: "old-session", events: [] };
      let listener;
      let releaseWrite;
      let notifyBlocked;
      const blocked = new Promise((resolve) => { notifyBlocked = resolve; });
      const release = new Promise((resolve) => { releaseWrite = resolve; });
      let pause = true;
      globalThis.chrome = {
        storage: { local: {
          get: async () => ({ tilo_skill_recording: structuredClone(state) }),
          set: async ({ tilo_skill_recording: next }) => {
            if (pause && next.events.length) {
              pause = false;
              notifyBlocked();
              await release;
            }
            state = structuredClone(next);
          },
        } },
        runtime: { onMessage: { addListener: (handler) => { listener = handler; } } },
        tabs: { query: async () => [], sendMessage: async () => {} },
        webNavigation: { onCommitted: { addListener: () => {} } },
        downloads: { onChanged: { addListener: () => {} } },
      };
      await import(`../background.js?SKILL_REPLAY=${transition}`);
      const send = (message) => new Promise((resolve) => listener(message, {}, resolve));
      const event = { kind: "event", event: { kind: "click", url: "https://example.test" } };
      const first = send(event);
      await blocked;
      const queued = send(event);
      const changed = send({ kind: transition });
      await new Promise(setImmediate);
      releaseWrite();
      const responses = await Promise.all([first, queued, changed]);
      assert.ok(responses.every((response) => !response.error));
      if (transition === "stop") assert.equal(state.active, false);
      else {
        assert.notEqual(state.id, "old-session");
        assert.deepEqual(state.events, []);
      }
    } finally {
      globalThis.chrome = originalChrome;
    }
  });
}

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
