import type { Event } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { agentNames, budgetCap, runEnded, worldStatus } from "./runSummary";

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
