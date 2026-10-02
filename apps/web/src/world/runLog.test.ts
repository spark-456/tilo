import { describe, expect, it } from "vitest";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { findItem } from "../screens/S_05";
import { reduce } from "./reducer";
import { creditsUsed, elapsed, waitingForYou } from "./runLog";

const events = EVENTS_VILLAGE_BASIC;

describe("PRD-18.3 AGW-08 run log: HUD figures derive only from recorded events", () => {
  it("sums the credits the events record, ending on the run's 13 (world.completed)", () => {
    expect(creditsUsed([])).toBe(0);
    expect(creditsUsed(events)).toBe(13);
  });

  it("counts an approval as waiting from its request until it is resolved", () => {
    const requested = events.findIndex((e) => e.type === "approval.requested");
    const resolved = events.findIndex((e) => e.type === "approval.resolved");
    expect(waitingForYou(events.slice(0, requested))).toBe(0);
    expect(waitingForYou(events.slice(0, requested + 1))).toBe(1);
    expect(waitingForYou(events.slice(0, resolved + 1))).toBe(0);
  });

  it("shows time as m:ss since the first recorded event", () => {
    expect(elapsed(events, events[0] as (typeof events)[number])).toBe("0:00");
    expect(elapsed(events, events[2] as (typeof events)[number])).toBe("0:22");
  });
});

describe("PRD-18.3 S-05 inspect: finds any item of the layout and its state from the events", () => {
  const layout = LAYOUT_VILLAGE_BASIC;
  const final = reduce(layout, events);

  it("finds a building, a district, a level and an agent, and nothing for an unknown id", () => {
    expect(findItem(layout, "B1")?.name).toBe("Mail Room");
    expect(findItem(layout, "D1")?.kind).toBe("District");
    expect(findItem(layout, "L1")?.kind).toBe("Level");
    expect(findItem(layout, "A_s1")?.kind).toBe("Agent");
    expect(findItem(layout, "B99")).toBeNull();
  });

  it("reports hidden before any event and finished after the run", () => {
    expect(findItem(layout, "B1")?.state(reduce(layout, []))).toBe("Not planned yet");
    expect(findItem(layout, "B1")?.state(final)).toBe("Finished");
    expect(findItem(layout, "L1")?.state(final)).toBe("Finished");
  });
});
