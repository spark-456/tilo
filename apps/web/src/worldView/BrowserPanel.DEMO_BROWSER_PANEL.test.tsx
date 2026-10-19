// @vitest-environment happy-dom
import type { Event } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { browserView } from "./BrowserPanel";

const recorded = (seq: number, type: string, data: object) => ({ seq, type, data }) as Event;

describe("DEMO-BROWSER-PANEL: cursor follows only recorded browser actions", () => {
  it("ignores a start frame and moves only when an action event has a target box", () => {
    const start = recorded(1, "browser.started", {
      session: "bs_01K7M000000000000000000000",
      frame: { artifact_id: "art_first", version: 1 },
    });
    const action = recorded(2, "browser.acted", {
      session: "bs_01K7M000000000000000000000",
      frame: { artifact_id: "art_second", version: 1 },
      verdict: "done",
      target_box: { x: 200, y: 300, width: 100, height: 40 },
      caption: "Clicking Search",
    });
    expect(browserView([start]).cursor).toBeNull();
    expect(browserView([start, action]).cursor?.caption).toBe("Clicking Search");
    expect(browserView([start, action]).frame).toBe("art_second");
    expect(browserView([start, action, recorded(3, "browser.stopped", {})]).cursor?.seq).toBe(2);
    const gated = recorded(3, "browser.acted", {
      session: "bs_01K7M000000000000000000000",
      verdict: "gated",
      target_box: { x: 500, y: 500, width: 20, height: 20 },
    });
    expect(browserView([start, action, gated]).cursor?.seq).toBe(2);
    expect(browserView([start, action, gated]).gated).toBe(true);
  });
});
