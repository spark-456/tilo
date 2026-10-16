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
