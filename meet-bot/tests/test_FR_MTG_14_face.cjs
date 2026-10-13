const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
function face() {
  const operations = [];
  const ctx = new Proxy(
    {},
    {
      get:
        (_, key) =>
        (...args) =>
          operations.push([key, ...args]),
      set: (_, key, value) => {
        operations.push([key, value]);
        return true;
      },
    },
  );
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ctx,
    captureStream: (fps) => ({ fps, getVideoTracks: () => ["canvas-camera"] }),
  };
  const sandbox = {
    __TILO_FACE_TEST__: true,
    document: { createElement: () => canvas },
    performance: { now: () => 0 },
    navigator: {
      mediaDevices: {
        getUserMedia: async () => {
          throw Error("real camera called");
        },
      },
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../bot/face.js"), "utf8"), sandbox);
  return { face: sandbox.__tiloFace, operations, canvas, sandbox };
}
test("FR_MTG_14_six_distinct_drawings_and_no_thinking_without_model", () => {
  const rig = face();
  const hashes = [];
  let now = 1000;
  for (const event of ["idle", "heard", "model_start", "audio_start", "success", "failure"]) {
    rig.face.event("model_end");
    rig.face.event("audio_end");
    rig.operations.length = 0;
    rig.face.event(event);
    rig.face.tick(now);
    now += 100;
    hashes.push(JSON.stringify(rig.operations));
  }
  assert.equal(new Set(hashes).size, 6);
  rig.face.event("thinking");
  assert.notEqual(rig.face.state, "thinking");
  assert.equal(rig.canvas.width, 320);
  assert.equal(rig.canvas.height, 240);
});
test("FR_MTG_14_audio_events_change_state_immediately_and_idle_blinks_within_eight_seconds", () => {
  const rig = face();
  rig.face.event("audio_start");
  assert.equal(rig.face.state, "speaking");
  rig.face.event("audio_end");
  assert.equal(rig.face.state, "idle");
  rig.operations.length = 0;
  rig.face.tick(6990);
  const before = JSON.stringify(rig.operations);
  rig.operations.length = 0;
  rig.face.tick(7070);
  assert.ok(rig.operations.some((op) => op[0] === "ellipse" && op[4] === 1));
  assert.notEqual(JSON.stringify(rig.operations), before);
  rig.face.event("model_start");
  rig.face.event("audio_start");
  rig.face.event("model_end");
  assert.equal(rig.face.state, "speaking");
  rig.face.event("audio_end");
  assert.equal(rig.face.state, "idle");
});
test("FR_MTG_14_video_uses_canvas_track_and_never_requests_the_real_camera", async () => {
  const rig = face();
  const stream = await rig.sandbox.navigator.mediaDevices.getUserMedia({ video: true });
  assert.equal(stream.fps, 15);
  assert.deepEqual(stream.getVideoTracks(), ["canvas-camera"]);
});
