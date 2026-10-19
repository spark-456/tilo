import { describe, expect, it } from "vitest";
import { stageRunLabel } from "./StageView";

describe("FR_WLD_12 S-25 honest stage source", () => {
  it("calls every fixture a recorded replay even while events are arriving", () => {
    expect(stageRunLabel(true, "started")).toBe("Recorded replay");
    expect(stageRunLabel(true, "completed")).toBe("Recorded replay");
  });
  it("calls only an active connected run live", () => {
    expect(stageRunLabel(false, "started")).toBe("Live run");
    expect(stageRunLabel(false, "paused")).toBe("Live run · paused");
    expect(stageRunLabel(false, "idle")).toBe("No run yet");
    expect(stageRunLabel(false, "completed")).toBe("Completed run");
    expect(stageRunLabel(false, "failed")).toBe("Failed run");
  });
});
