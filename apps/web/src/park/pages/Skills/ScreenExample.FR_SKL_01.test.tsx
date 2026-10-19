// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { ScreenExample } from "./TeachWizard";
import { recordScreen } from "./recorder";
import type { Teach } from "./useTeach";

vi.mock("./recorder", () => ({ recordScreen: vi.fn() }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("test_FR_SKL_01_S3_keeps_preview_local_until_use_this_recording", async () => {
  vi.stubGlobal("URL", { createObjectURL: () => "blob:local", revokeObjectURL: vi.fn() });
  const file = new File(["screen"], "screen-recording.webm", { type: "video/webm" });
  const captureFiles = vi.fn(() => true);
  vi.mocked(recordScreen).mockImplementation(async (_narrate, onStop) => ({
    stop: () => onStop(file),
    discard: vi.fn(),
  }));
  const m = mount(<ScreenExample t={{ busy: false, captureFiles } as unknown as Teach} />);
  const button = (label: string) =>
    [...m.container.querySelectorAll("button")].find((b) => b.textContent === label);
  await act(async () => click(button("Start recording") as HTMLButtonElement));
  expect(vi.mocked(recordScreen)).toHaveBeenCalledWith(false, expect.any(Function));
  expect(captureFiles).not.toHaveBeenCalled();
  await act(async () => click(button("Stop recording") as HTMLButtonElement));
  expect(captureFiles).not.toHaveBeenCalled();
  expect(m.container.querySelector("video")?.getAttribute("src")).toBe("blob:local");
  await act(async () => click(button("Use this recording") as HTMLButtonElement));
  expect(captureFiles).toHaveBeenCalledWith([file], "record");
});

it("test_R_SKILL_TEACH_keeps_recording_until_capture_succeeds", async () => {
  vi.stubGlobal("URL", { createObjectURL: () => "blob:local", revokeObjectURL: vi.fn() });
  const file = new File(["screen"], "recording.webm", { type: "video/webm" });
  const captureFiles = vi.fn(() => true);
  const onAccepted = vi.fn();
  vi.mocked(recordScreen).mockImplementation(async (_narrate, onStop) => ({
    stop: () => onStop(file),
    discard: vi.fn(),
  }));
  const teach = { busy: false, usedFile: false, captureFiles } as unknown as Teach;
  const m = mount(<ScreenExample t={teach} onAccepted={onAccepted} />);
  const button = (label: string) =>
    [...m.container.querySelectorAll("button")].find((b) => b.textContent === label);
  await act(async () => click(button("Start recording") as HTMLButtonElement));
  await act(async () => click(button("Stop recording") as HTMLButtonElement));
  await act(async () => click(button("Use this recording") as HTMLButtonElement));
  expect(onAccepted).not.toHaveBeenCalled();
  expect(m.container.querySelector("video")?.getAttribute("src")).toBe("blob:local");
  m.render(<ScreenExample t={{ ...teach, fileError: "Upload failed." }} onAccepted={onAccepted} />);
  expect(onAccepted).not.toHaveBeenCalled();
  expect(m.container.querySelector("video")?.getAttribute("src")).toBe("blob:local");
  m.render(<ScreenExample t={{ ...teach, usedFile: true }} onAccepted={onAccepted} />);
  expect(onAccepted).toHaveBeenCalledOnce();
});
