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
    ctx.fillStyle = "#f5f5f5";
    ctx.fillRect(0, 0, 320, 240);
    ctx.strokeStyle = "#262626";
    ctx.fillStyle = "#262626";
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.ellipse(160, 120, 90, 82, 0, 0, Math.PI * 2);
    ctx.stroke();
    for (const x of [128, 192]) {
      ctx.beginPath();
      ctx.ellipse(
        x,
        102,
        s === "listening" ? 12 : 8,
        blink ? 1 : s === "happy" ? 4 : 10,
        0,
        0,
        Math.PI * 2,
      );
      ctx.fill();
    }
    ctx.beginPath();
    if (s === "speaking") {
      ctx.ellipse(160, 153, 18, 6 + 18 * level, 0, 0, Math.PI * 2);
      ctx.fill();
    } else {
      ctx.moveTo(135, 155);
      ctx.quadraticCurveTo(160, s === "sad" ? 130 : s === "happy" ? 180 : 157, 185, 155);
      ctx.stroke();
    }
    if (s === "thinking")
      for (const x of [142, 160, 178]) {
        ctx.beginPath();
        ctx.arc(x, 205, 4, 0, Math.PI * 2);
        ctx.fill();
      }
    if (s === "listening") {
      ctx.beginPath();
      ctx.arc(160, 120, 99, -0.4, 0.4);
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
