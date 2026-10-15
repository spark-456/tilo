// FR-MTG-14: local canvas camera. State comes only from explicit runtime events.
(() => {
  const canvas = document.createElement("canvas");
  canvas.width = 320;
  canvas.height = 240;
  const ctx = canvas.getContext("2d");
  let models = 0;
  let audio = false;
  let feeling = "idle";
  let level = 0;
  let last = Number.NEGATIVE_INFINITY;
  const state = () => (audio ? "speaking" : models > 0 ? "thinking" : feeling);
  function event(kind, value = 0) {
    if (kind === "model_start") {
      models++;
      feeling = "idle";
    }
    if (kind === "model_end") {
      models = Math.max(0, models - 1);
      feeling = "idle";
    }
    if (kind === "audio_start") {
      audio = true;
      feeling = "idle";
    }
    if (kind === "audio_end") {
      audio = false;
      level = 0;
      feeling = "idle";
    }
    if (kind === "audio_level" && audio) level = Math.max(0, Math.min(1, Number(value) || 0));
    if (kind === "heard") feeling = "listening";
    if (kind === "success") feeling = "happy";
    if (kind === "failure") feeling = "sad";
    if (kind === "idle") feeling = "idle";
  }
  function tick(now) {
    if (now - last < 1000 / 15) return;
    last = now;
    const s = state();
    const blink = s === "idle" && now % 7200 >= 7000;
    draw(s, blink);
  }
  // Canvas port of tilo-world.js: box planes, Director crown, face plate
  // and billboard arms (ADR-0003). No design runtime.
  const ink = "#1F1D2B";
  const director = "#E8643F";
  const project = (x, y, z) => [160 + (x - y) * 0.866 * 3.3, 158 + ((x + y) * 0.5 - z) * 3.3];
  function polygon(points, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(...points[0]);
    for (const point of points.slice(1)) ctx.lineTo(...point);
    ctx.closePath();
    ctx.fill();
  }
  function box(x, y, z, w, d, h, left, right, top) {
    polygon([project(x, y + d, z), project(x + w, y + d, z), project(x + w, y + d, z + h), project(x, y + d, z + h)], left);
    polygon([project(x + w, y + d, z), project(x + w, y, z), project(x + w, y, z + h), project(x + w, y + d, z + h)], right);
    polygon([project(x, y, z + h), project(x + w, y, z + h), project(x + w, y + d, z + h), project(x, y + d, z + h)], top);
  }
  function ellipse(x, y, rx, ry, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2);
    ctx.fill();
  }
  function draw(s, blink) {
    ctx.fillStyle = "#F1EEE6";
    ctx.fillRect(0, 0, 320, 240);
    ctx.strokeStyle = ink;
    ctx.lineWidth = 0.8;
    ctx.lineCap = "round";
    ellipse(160, 176, 48, 11, "rgba(31,29,43,.13)");
    ctx.save();
    if (s === "listening") {
      ctx.translate(160, 125);
      ctx.rotate(-0.08);
      ctx.translate(-160, -125);
    }
    box(-7.5, -7.5, 4, 15, 15, 19, director, "#B54E31", "#ED835D");
    for (const [x, h] of [[-6, 3.5], [-2, 5], [2, 3.5]])
      box(x, -2, 23, 4, 4, h, director, "#B54E31", "#ED835D");
    for (const [x, angle] of [[116, s === "happy" ? 2.1 : -0.2], [204, s === "happy" ? -2.1 : 0.2]]) {
      ctx.save();
      ctx.translate(x, 132);
      ctx.rotate(angle);
      ctx.fillStyle = "#A2462C";
      ctx.beginPath();
      ctx.roundRect(-5, -4, 10, 28, 5);
      ctx.fill();
      ctx.restore();
    }
    ctx.save();
    const [fx, fy] = project(-7.5, 7.5, 23);
    ctx.transform(0.866 * 3.3, 0.5 * 3.3, 0, 3.3, fx, fy);
    ctx.fillStyle = "#FFFFFF";
    ctx.beginPath();
    ctx.roundRect(1.6, 2.3, 11.8, 9.3, 3.2);
    ctx.fill();
    for (const x of [4.95, 10.05]) ellipse(x, 5.5, 1.05, blink ? 0.3 : s === "happy" ? 0.45 : 1.05, ink);
    ctx.strokeStyle = ink;
    if (s === "speaking") ellipse(7.5, 8.7, 1.3, 0.5 + 1.4 * level, ink);
    else {
      ctx.beginPath();
      ctx.moveTo(5.6, 8.5);
      ctx.quadraticCurveTo(7.5, s === "sad" ? 6.8 : s === "happy" ? 11 : 8.5, 9.4, 8.5);
      ctx.stroke();
    }
    ctx.restore();
    ctx.restore();
    // Entire bust and desk stay inside Meet's centre 16:9 crop.
    box(-15, -7, -4, 30, 14, 2, "#D6D0C0", "#C2BBA8", "#EEEBE2");
    if (s === "thinking")
      for (const x of [146, 160, 174]) ellipse(x, 182, 3, 3, ink);
    if (s === "listening") {
      ctx.strokeStyle = ink;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(203, 103, 17, -0.7, 0.7);
      ctx.stroke();
    }
  }
  const face = {
    canvas,
    event,
    tick,
    get state() {
      return state();
    },
  };
  Object.defineProperty(globalThis, "__tiloFace", { value: face, configurable: false });
  const media = navigator.mediaDevices;
  if (media) {
    if (media.enumerateDevices) {
      const enumerate = media.enumerateDevices.bind(media);
      const info = { deviceId: "tilo-canvas-camera", groupId: "tilo-canvas", kind: "videoinput", label: "Tilo Director" };
      const camera = { ...info, toJSON: () => ({ ...info }) };
      media.enumerateDevices = async () => {
        const devices = await enumerate();
        return [...devices.filter((device) => device.kind !== "videoinput" || device.deviceId !== info.deviceId), camera];
      };
    }
    const original = media.getUserMedia.bind(media);
    media.getUserMedia = async (constraints) => {
      if (!constraints.video) return original(constraints);
      const stream = canvas.captureStream(15);
      if (constraints.audio) {
        const microphone = await original({ audio: constraints.audio, video: false });
        for (const track of microphone.getAudioTracks()) stream.addTrack(track);
      }
      return stream;
    };
  }
  if (!globalThis.__TILO_FACE_TEST__) {
    const frame = (now) => {
      tick(now);
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }
})();
