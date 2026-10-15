const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const { createHash } = require("node:crypto");
function face(devices = []) {
  const operations = [];
  const mediaCalls = [];
  const tracks = ["canvas-camera"];
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
    captureStream: (fps) => ({ fps, getVideoTracks: () => tracks, addTrack: (t) => tracks.push(t) }),
  };
  const sandbox = {
    __TILO_FACE_TEST__: true,
    document: { createElement: () => canvas },
    performance: { now: () => 0 },
    navigator: {
      mediaDevices: {
        enumerateDevices: async () => devices,
        getUserMedia: async (constraints) => {
          mediaCalls.push(constraints);
          if (constraints.video) throw Error("real camera called");
          return { getAudioTracks: () => ["real-microphone"] };
        },
      },
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../bot/face.js"), "utf8"), sandbox);
  return { face: sandbox.__tiloFace, operations, canvas, sandbox, mediaCalls, tracks };
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
    hashes.push(createHash("sha256").update(JSON.stringify(rig.operations)).digest("hex"));
  }
  assert.equal(new Set(hashes).size, 6);
  // SHA-256 of recorded canvas operations, not pixel hashes.
  assert.deepEqual(hashes, [
    "a1e1a0fc0b8d6c3b601cb2809047dfa7e7ecdbf29a4112887697b30d82f5ec0a",
    "81008cb0e6b94c7f49afcc594725c7dabc73ccc87c92f320897f374c422c481d",
    "cf4b54a6fb1cbc681037d986a021ef38a653056c8768b31924c413fe7959aefc",
    "354555f1b0eebfd73fcb4087db56d880bd7ac7a76c497d5cecdf01c3708c9fdf",
    "49b2400dcd0e67fd24e86769503b1db27cfc28609fa147e2b6d25bdffe92f344",
    "02a6f8e57343d7ffeb520668d6cc8346496adad0aeb196a0ddd0702dd5e1e205",
  ]);
  rig.face.event("thinking");
  assert.notEqual(rig.face.state, "thinking");
  assert.equal(rig.canvas.width, 320);
  assert.equal(rig.canvas.height, 240);
});
test("FR_MTG_14_director_palette_desk_and_listening_tilt", () => {
  const rig = face();
  rig.face.tick(1000);
  assert.ok(rig.operations.some((op) => op[0] === "fillStyle" && op[1] === "#E8643F"));
  assert.ok(rig.operations.some((op) => op[0] === "fillStyle" && op[1] === "#1F1D2B"));
  assert.ok(rig.operations.filter((op) => op[0] === "closePath").length >= 12);
  assert.ok(rig.operations.filter((op) => ["moveTo", "lineTo"].includes(op[0])).every((op) => op[2] < 210));
  rig.operations.length = 0;
  rig.face.event("heard");
  rig.face.tick(1100);
  assert.ok(rig.operations.some((op) => op[0] === "rotate" && op[1] === -0.08));
  assert.ok(rig.operations.some((op) => op[0] === "arc" && op[3] === 17));
});
test("FR_MTG_14_enumeration_preserves_devices_adds_one_stable_camera_and_deduplicates", async () => {
  const physical = { deviceId: "physical", kind: "videoinput", label: "Webcam" };
  const mic = { deviceId: "mic", kind: "audioinput", label: "Microphone" };
  const devices = [physical, mic];
  const rig = face(devices);
  const media = rig.sandbox.navigator.mediaDevices;
  const first = await media.enumerateDevices();
  const synthetic = first.filter((device) => device.kind === "videoinput" && device !== physical);
  assert.equal(first.length, 3);
  assert.equal(first[0], physical);
  assert.equal(first[1], mic);
  assert.equal(devices.length, 2);
  assert.equal(synthetic.length, 1);
  assert.equal(synthetic[0].label, "Tilo Director");
  assert.equal(synthetic[0].deviceId, "tilo-canvas-camera");
  assert.equal(synthetic[0].toJSON().groupId, "tilo-canvas");
  devices.push(synthetic[0], synthetic[0]);
  const second = await media.enumerateDevices();
  assert.equal(second.length, 3);
  assert.equal(second[2].deviceId, synthetic[0].deviceId);
});
test("FR_MTG_14_frame_limit_model_counters_and_pcm_level_are_preserved", () => {
  const rig = face();
  rig.face.tick(0);
  rig.operations.length = 0;
  rig.face.tick(60);
  assert.equal(rig.operations.length, 0);
  rig.face.event("model_start");
  rig.face.event("model_start");
  rig.face.event("model_end");
  assert.equal(rig.face.state, "thinking");
  rig.face.event("audio_start");
  rig.face.event("audio_level", 0);
  rig.face.tick(100);
  const low = JSON.stringify(rig.operations);
  rig.operations.length = 0;
  rig.face.event("audio_level", 1);
  rig.face.tick(200);
  assert.notEqual(JSON.stringify(rig.operations), low);
  rig.face.event("audio_end");
  assert.equal(rig.face.state, "thinking");
  rig.face.event("model_end");
  assert.equal(rig.face.state, "idle");
});
test("FR_MTG_14_canvas_video_keeps_real_microphone_and_audio_only_path", async () => {
  const rig = face();
  const media = rig.sandbox.navigator.mediaDevices;
  await media.getUserMedia({ video: true, audio: { deviceId: "pulse" } });
  assert.deepEqual(rig.tracks, ["canvas-camera", "real-microphone"]);
  assert.deepEqual(JSON.parse(JSON.stringify(rig.mediaCalls)), [{ audio: { deviceId: "pulse" }, video: false }]);
  const audioOnly = { audio: true };
  await media.getUserMedia(audioOnly);
  assert.equal(rig.mediaCalls[1], audioOnly);
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
  assert.equal(rig.operations.filter((op) => op[0] === "ellipse" && op[4] === 0.3).length, 2);
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
