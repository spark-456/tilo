// FR-SKL-01: screen capture stays in browser memory until the person chooses Use this recording.
export interface ScreenRecording {
  stop(): void;
  discard(): void;
}

export async function recordScreen(
  narrate: boolean,
  onStop: (file: File | null) => void,
): Promise<ScreenRecording> {
  if (!navigator.mediaDevices?.getDisplayMedia || typeof MediaRecorder === "undefined") {
    throw new Error("Screen recording is unavailable in this browser.");
  }
  const display = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 } });
  let mic: MediaStream | null = null;
  try {
    if (narrate) mic = await navigator.mediaDevices.getUserMedia({ audio: true });
    const tracks = [...display.getVideoTracks(), ...(mic?.getAudioTracks() ?? [])];
    const stream = new MediaStream(tracks);
    const recorder = new MediaRecorder(stream, {
      mimeType: "video/webm",
      videoBitsPerSecond: 200_000,
      audioBitsPerSecond: 24_000,
    });
    const chunks: Blob[] = [];
    let discarded = false;
    let settled = false;
    const stop = () => {
      if (recorder.state !== "inactive") recorder.stop();
    };
    const timer = window.setTimeout(stop, 300_000);
    const release = () => {
      window.clearTimeout(timer);
      for (const track of [...display.getTracks(), ...(mic?.getTracks() ?? [])]) track.stop();
    };
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    recorder.onstop = () => {
      if (settled) return;
      settled = true;
      release();
      const blob = new Blob(chunks, { type: "video/webm" });
      onStop(
        discarded || blob.size === 0
          ? null
          : new File([blob], "screen-recording.webm", { type: "video/webm" }),
      );
    };
    display.getVideoTracks()[0]?.addEventListener("ended", stop, { once: true });
    recorder.start();
    return {
      stop,
      discard() {
        discarded = true;
        stop();
      },
    };
  } catch (error) {
    for (const track of [...display.getTracks(), ...(mic?.getTracks() ?? [])]) track.stop();
    throw error;
  }
}
