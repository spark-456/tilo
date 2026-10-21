const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
function face({ reducedMotion = false } = {}) {
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
    matchMedia: () => ({ matches: reducedMotion }),
    navigator: {
      mediaDevices: {
        enumerateDevices: async () => [{ kind: "audioinput", deviceId: "mic" }],
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
  // Owner 21 Oct: "very blurry". A 16:9 frame (960 x 540), the vector scene drawn 2.25x, never upscaled.
  assert.equal(rig.canvas.width, 960);
  assert.equal(rig.canvas.height, 540);
});
test("FR_MTG_14_sharp_frame_and_every_label_inside_the_safe_area_of_every_tile", () => {
  for (const event of ["idle", "heard", "model_start", "audio_start", "success", "failure"]) {
    const rig = face();
    rig.face.event(event);
    rig.operations.length = 0;
    rig.face.tick(1000);
    const scale = rig.operations.find((op) => op[0] === "setTransform" && op[1] === 2.25);
    assert.deepEqual(scale, ["setTransform", 2.25, 0, 0, 2.25, 120, 0]); // the 320 x 240 scene, centred in 960 x 540
    const label = rig.operations.find((op) => op[0] === "fillText");
    const pill = rig.operations.filter((op) => op[0] === "roundRect").at(-1);
    // A square (720 x 720) or 9:16 tile keeps only the middle of the frame: scene x 93..227 holds the label.
    for (const x of [pill[1], pill[1] + pill[3], label[2]]) assert.ok(x >= 93 && x <= 227, `${event}: ${x}`);
    assert.ok(pill[2] >= 4 && pill[2] + pill[4] <= 236, `${event}: label inside the frame vertically`);
  }
});
test("FR_MTG_14_the_camera_stays_at_15_fps", async () => {
  const rig = face();
  const stream = await rig.sandbox.navigator.mediaDevices.getUserMedia({ video: true });
  assert.equal(stream.fps, 15); // the bot's CPU is shared with Chrome and the voice: a mostly still scene needs no more
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
test("FR_MTG_14_T_MEET_draws_director_bust_on_desk_inside_the_tile", () => {
  const rig = face();
  rig.face.tick(1000);
  assert.ok(rig.operations.some((op) => op[0] === "fillStyle" && op[1] === "#ECFBC2"));
  assert.ok(rig.operations.some((op) => op[0] === "fillStyle" && op[1] === "#E8643F"));
  assert.ok(rig.operations.some((op) => op[0] === "fillStyle" && op[1] === "#D5D5D0"));
  assert.ok(rig.operations.some((op) => op[0] === "fillStyle" && op[1] === "#1F1D2B"));
  assert.ok(rig.operations.some((op) => op[0] === "moveTo" && op[1] === 30 && op[2] === 166));
});
test("FR_MTG_14_T_MEET_reduced_motion_keeps_an_idle_pose_static", () => {
  const rig = face({ reducedMotion: true });
  rig.face.tick(6990);
  const first = JSON.stringify(rig.operations);
  rig.operations.length = 0;
  rig.face.tick(7070);
  assert.equal(JSON.stringify(rig.operations), first);
});
test("FR_MTG_14_T_MEET_lists_the_canvas_camera_for_Meet", async () => {
  const rig = face();
  const devices = await rig.sandbox.navigator.mediaDevices.enumerateDevices();
  assert.equal(devices.filter((device) => device.kind === "videoinput").length, 1);
  assert.equal(devices[0].deviceId, "mic");
  assert.match(devices[1].label, /Tilo/);
});
test("FR_MTG_14_T_MEET_speaking_mouth_uses_only_recorded_audio_level", () => {
  const rig = face();
  rig.face.event("audio_start");
  rig.face.tick(1000);
  const closed = rig.operations.find((op) => op[0] === "ellipse" && op[1] === 100);
  rig.operations.length = 0;
  rig.face.event("audio_level", 0.8);
  rig.face.tick(1100);
  const open = rig.operations.find((op) => op[0] === "ellipse" && op[1] === 100);
  assert.equal(closed[4], 3);
  assert.equal(open[4], 11);
});
