// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { recordScreen } from "./recorder";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("test_FR_SKL_01_records_locally_until_use_and_stops_at_five_minutes", async () => {
  vi.useFakeTimers();
  const video = { stop: vi.fn(), addEventListener: vi.fn() };
  const audio = { stop: vi.fn() };
  const display = { getVideoTracks: () => [video], getTracks: () => [video] };
  const mic = { getAudioTracks: () => [audio], getTracks: () => [audio] };
  const getDisplayMedia = vi.fn(async () => display);
  const getUserMedia = vi.fn(async () => mic);
  vi.stubGlobal("navigator", { mediaDevices: { getDisplayMedia, getUserMedia } });
  vi.stubGlobal(
    "MediaStream",
    class {
      constructor(public tracks: unknown[]) {}
    },
  );
  vi.stubGlobal(
    "MediaRecorder",
    class {
      state = "recording";
      ondataavailable?: (e: { data: Blob }) => void;
      onstop?: () => void;
      constructor(
        _stream: unknown,
        readonly options: Record<string, unknown>,
      ) {}
      start() {}
      stop() {
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob(["local"], { type: "video/webm" }) });
        this.onstop?.();
      }
    },
  );
  const onStop = vi.fn();
  const recording = await recordScreen(false, onStop);
  expect(getDisplayMedia).toHaveBeenCalledWith({ video: { frameRate: 5 } });
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(onStop).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(300_000);
  expect(onStop).toHaveBeenCalledOnce();
  expect(onStop.mock.calls[0]?.[0]).toMatchObject({ name: "screen-recording.webm" });
  expect(video.stop).toHaveBeenCalledOnce();
  recording.discard();
});
