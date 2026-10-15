const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
// FR-MTG-14: with no model call every 20 s to reset it (FR-MTG-09 silence guard), "listening" and "thinking" must
// fall back to idle by themselves. The decay only ever returns to idle: it never invents activity.
function face() {
  const clock = { now: 0 };
  const ctx = new Proxy({}, { get: () => () => undefined, set: () => true });
  const canvas = { width: 0, height: 0, getContext: () => ctx, captureStream: () => ({}) };
  const sandbox = {
    __TILO_FACE_TEST__: true,
    document: { createElement: () => canvas },
    performance: { now: () => clock.now },
    navigator: {},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../bot/face.js"), "utf8"), sandbox);
  return { face: sandbox.__tiloFace, clock };
}
test("FR_MTG_14_listening_returns_to_idle_after_a_quiet_period", () => {
  const { face: f, clock } = face();
  clock.now = 10_000;
  f.event("heard");
  assert.equal(f.state, "listening");
  clock.now = 12_000;
  assert.equal(f.state, "listening");
  clock.now = 15_000;
  assert.equal(f.state, "idle");
});
test("FR_MTG_14_each_heard_event_restarts_the_listening_period", () => {
  const { face: f, clock } = face();
  clock.now = 1_000;
  f.event("heard");
  clock.now = 4_000;
  f.event("heard");
  clock.now = 7_000;
  assert.equal(f.state, "listening");
  clock.now = 9_000;
  assert.equal(f.state, "idle");
});
test("FR_MTG_14_happy_and_sad_also_settle_to_idle", () => {
  const { face: f, clock } = face();
  for (const kind of ["success", "failure"]) {
    clock.now += 1_000;
    f.event(kind);
    assert.notEqual(f.state, "idle");
    clock.now += 6_000;
    assert.equal(f.state, "idle");
  }
});
test("FR_MTG_14_thinking_never_outlives_a_lost_model_end", () => {
  const { face: f, clock } = face();
  clock.now = 1_000;
  f.event("model_start");
  clock.now = 10_000;
  assert.equal(f.state, "thinking"); // a real call can take a while
  clock.now = 60_000;
  assert.equal(f.state, "idle");
  f.event("model_end"); // a late end does not push the count below zero
  f.event("model_start");
  assert.equal(f.state, "thinking");
});
test("FR_MTG_14_decay_does_not_touch_speaking_and_invents_nothing", () => {
  const { face: f, clock } = face();
  f.event("audio_start");
  clock.now = 120_000;
  assert.equal(f.state, "speaking"); // audio_end is the only thing that ends speech
  f.event("audio_end");
  assert.equal(f.state, "idle");
  clock.now = 500_000;
  assert.equal(f.state, "idle"); // idle stays idle
});
