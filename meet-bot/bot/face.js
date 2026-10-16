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
  // Decay: "listening", "happy" and "sad" last FEELING_MS after the event that set them; "thinking" ends with
  // model_end, and THINKING_MS only guards against a lost model_end. Decay only ever returns to idle.
  const FEELING_MS = 4000;
  const THINKING_MS = 30000;
  const clock = () => (globalThis.performance ? performance.now() : Date.now());
  let feelingAt = 0;
  let modelAt = 0;
  const state = () => {
    const now = clock();
    if (feeling !== "idle" && now - feelingAt > FEELING_MS) feeling = "idle";
    if (models > 0 && now - modelAt > THINKING_MS) models = 0;
    return audio ? "speaking" : models > 0 ? "thinking" : feeling;
  };
  function feel(value) {
    feeling = value;
    feelingAt = clock();
  }
  function event(kind, value = 0) {
    if (kind === "model_start") {
      models++;
      modelAt = clock();
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
    if (kind === "heard") feel("listening");
    if (kind === "success") feel("happy");
    if (kind === "failure") feel("sad");
    if (kind === "idle") feeling = "idle";
  }
  function tick(now) {
    if (now - last < 1000 / 15) return;
    last = now;
    const s = state();
    const reduced = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    // FR-MTG-14 / T Meet: only a live heard/model/audio/success/failure event changes pose.
    // Idle blinking is ambient; reduced motion keeps every pose static.
    const blink = !reduced && s === "idle" && now % 7200 >= 7000;
    const box = (x, y, width, height, radius, color) => {
      ctx.beginPath();
      ctx.roundRect(x, y, width, height, radius);
      ctx.fillStyle = color;
      ctx.fill();
    };
    const polygon = (points, color) => {
      ctx.beginPath();
      ctx.moveTo(...points[0]);
      for (const point of points.slice(1)) ctx.lineTo(...point);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
    };
    ctx.fillStyle = "#ECFBC2";
    ctx.fillRect(0, 0, 320, 240);
    ctx.fillStyle = "rgba(11,11,12,.16)";
    ctx.beginPath();
    ctx.ellipse(160, 174, 38, 5, 0, 0, Math.PI * 2);
    ctx.fill();

    // The Director rig follows the 200 × 236 Buddy geometry, scaled to a 150 px Meet bust.
    ctx.save();
    ctx.translate(96, 38);
    ctx.scale(150 / 236, 150 / 236);
    ctx.translate(100, 200);
    ctx.rotate(s === "listening" ? -0.12 : s === "sad" ? 0.04 : 0);
    ctx.translate(-100, -200);
    box(68, 188, 24, 26, 5, "#A2462E");
    box(112, 188, 24, 26, 5, "#A2462E");
    ctx.save();
    ctx.translate(36, 101);
    ctx.rotate(s === "happy" ? 0.25 : s === "sad" ? -0.1 : 0.08);
    box(-10, 0, 20, 58, 6, "#A2462E");
    box(-11, 43, 22, 16, 5, "#843A2A");
    ctx.restore();
    box(70, 44, 20, 26, 4, "#B64E32");
    box(94, 30, 22, 40, 4, "#E8643F");
    box(94, 30, 22, 7, 3, "#ED896B");
    box(120, 44, 20, 26, 4, "#B64E32");
    polygon([[44, 72], [54, 62], [168, 62], [156, 72]], "#ED896B");
    polygon([[156, 72], [168, 62], [168, 186], [156, 196]], "#B64E32");
    box(44, 72, 112, 124, 10, "#E8643F");
    box(44, 188, 112, 8, 3, "#D75C3B");
    ctx.save();
    ctx.translate(178, 101);
    ctx.rotate(s === "happy" ? -2.5 : s === "thinking" || s === "listening" ? -2.3 : s === "sad" ? 0.1 : -0.08);
    box(-10, 0, 20, 58, 6, "#A2462E");
    box(-11, 43, 22, 16, 5, "#843A2A");
    ctx.restore();
    box(58, 88, 84, 54, 14, "#FFFFFF");
    for (const x of [83, 116]) {
      ctx.beginPath();
      if (s === "happy") {
        ctx.strokeStyle = "#1F1D2B";
        ctx.lineWidth = 3.5;
        ctx.arc(x, 113, 7, Math.PI, 0);
        ctx.stroke();
      } else {
        ctx.ellipse(x, s === "thinking" ? 110 : s === "sad" ? 117 : 113, 5.5, blink ? 1 : 7, 0, 0, Math.PI * 2);
        ctx.fillStyle = "#1F1D2B";
        ctx.fill();
        if (!blink) {
          ctx.fillStyle = "#FFFFFF";
          ctx.fillRect(x - 3, 108, 2, 2);
        }
      }
    }
    ctx.fillStyle = "#1F1D2B";
    ctx.beginPath();
    if (s === "speaking") {
      ctx.ellipse(100, 126, 6, 3 + 10 * level, 0, 0, Math.PI * 2);
      ctx.fill();
    } else if (s === "happy") {
      box(91, 122, 18, 10, [2, 2, 10, 10], "#1F1D2B");
    } else if (s === "sad") {
      box(93, 126, 14, 6, [8, 8, 2, 2], "#1F1D2B");
    } else {
      box(94, 126, s === "thinking" ? 7 : 12, s === "listening" ? 4 : 3, 3, "#1F1D2B");
    }
    ctx.restore();
    if (s === "thinking")
      for (const x of [202, 213, 224]) {
        ctx.beginPath();
        ctx.arc(x, 52, 3, 0, Math.PI * 2);
        ctx.fillStyle = "#E8643F";
        ctx.fill();
      }
    if (s === "listening") {
      for (const radius of [15, 23]) {
        ctx.beginPath();
        ctx.strokeStyle = "#0B0B0C";
        ctx.lineWidth = 2;
        ctx.arc(86, 104, radius, -2.5, -0.8);
        ctx.stroke();
      }
    }
    polygon([[30, 166], [290, 166], [302, 194], [18, 194]], "#FFFFFF");
    ctx.fillStyle = "#D5D5D0";
    ctx.fillRect(30, 194, 260, 16);
    polygon([[208, 161], [244, 161], [238, 176], [200, 176]], "#F4F4F1");
    box(84, 156, 16, 18, 4, "#C8F23A");
    box(12, 38, 116, 20, 10, "rgba(11,11,12,.72)");
    ctx.fillStyle = "#C8F23A";
    ctx.beginPath();
    ctx.arc(24, 48, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#FFFFFF";
    ctx.font = "600 10px sans-serif";
    ctx.fillText(({ idle: "Tilo · notetaker", listening: "Listening", thinking: "Thinking", speaking: "Speaking", happy: "All noted", sad: "Lost the audio" })[s], 33, 51);
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
    const enumerate = media.enumerateDevices?.bind(media);
    if (enumerate) media.enumerateDevices = async () => {
      const devices = await enumerate();
      return [...devices, { deviceId: "tilo-canvas-camera", groupId: "", kind: "videoinput", label: "Tilo camera" }];
    };
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
