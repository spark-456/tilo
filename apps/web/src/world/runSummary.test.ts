import type { Event } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { agentNames, budgetCap, hudGlance, memorySaved, runEnded, worldStatus } from "./runSummary";

const events = EVENTS_VILLAGE_BASIC;
const withType = (type: string): Event => ({ ...(events[0] as Event), type }) as Event;

describe("PRD-18.3 S-04/S-10/S-12 run summary: status and budget come from the events alone", () => {
  it("is idle until a registered world event says otherwise", () => {
    expect(worldStatus([])).toBe("idle");
    expect(worldStatus(events.slice(0, 3))).toBe("idle");
    expect(worldStatus(events)).toBe("completed");
  });

  it("treats world.failed as the end of the run, and ignores an unregistered type (HR-5)", () => {
    const failed = [...events.slice(0, 12), withType("world.failed")];
    expect(worldStatus(failed)).toBe("failed");
    expect(runEnded("failed")).toBe(true);
    expect(runEnded(worldStatus(events.slice(0, 12)))).toBe(false);
    expect(worldStatus([...events.slice(0, 12), withType("world.exploded")])).toBe("started");
  });

  it("reads the approved budget from budget.granted, null before it", () => {
    expect(budgetCap(events.slice(0, 2))).toBeNull();
    expect(budgetCap(events)).toBe(40);
  });

  it("names agents by rank, numbering a rank that repeats", () => {
    const names = agentNames(LAYOUT_VILLAGE_BASIC);
    expect(names.get("A_dir")).toBe("Director");
    expect(names.get("A_s1")).toBe("Specialist 1");
    expect(names.get("A_s2")).toBe("Specialist 2");
  });
});

const hit = (saved: unknown): Event =>
  ({ ...(events[0] as Event), type: "memory.hit", data: { saved } }) as Event;

describe("FR-MTR-06 / PRD 14.3 S-04 HUD: credits saved by memory are the sum of memory.hit saved", () => {
  it("is 0 when the run reused nothing, and sums every hit (to one decimal)", () => {
    expect(memorySaved(events)).toBe(0);
    expect(memorySaved([hit(5.5), hit(2.25), withType("budget.granted")])).toBe(7.8);
  });

  it("ignores a hit that carries no number", () => {
    expect(memorySaved([hit(undefined), hit("5"), hit(Number.NaN)])).toBe(0);
  });
});

describe("PRD 18.3 S-04 HUD on a phone: one line of status, credits and approvals waiting", () => {
  it("says nothing yet, then only the status while the run is getting ready", () => {
    expect(hudGlance("idle", [], 0, 0)).toBe("Nothing yet");
    expect(hudGlance("idle", events.slice(0, 3), 0, 0)).toBe("Getting ready");
  });

  it("words the status, the credits and what waits for the person", () => {
    expect(hudGlance("started", events, 13, 0)).toBe("Working · 13 credits · nothing waiting");
    expect(hudGlance("started", events, 4, 2)).toBe("Working · 4 credits · 2 waiting for you");
    expect(hudGlance("completed", events, 13, 0)).toContain("Done");
  });
});
