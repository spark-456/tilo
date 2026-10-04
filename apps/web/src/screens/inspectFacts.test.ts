import type { Layout } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { createInitialState } from "../world/reducer";
import { factsOf, stateTone } from "./inspectFacts";

const layout = LAYOUT_VILLAGE_BASIC as unknown as Layout;
const state = createInitialState(layout);
const building = layout.semantic.levels[0]?.districts[0]?.buildings[0];
const agent = layout.semantic.agents[0];

describe("UX-1 #227 E3: Inspect facts come from the layout and the reducer (HR-1)", () => {
  it("a building says what kind it is and that nobody is there before an event sends someone", () => {
    const facts = new Map(factsOf(layout, building?.id ?? "", state));
    expect(facts.get("Kind")).toBeTruthy();
    expect(facts.get("People here")).toBe("Nobody has been sent here yet");
  });

  it("an agent has a role, who it reports to and says it is not placed before it is sent", () => {
    const facts = new Map(factsOf(layout, agent?.id ?? "", state));
    expect(facts.get("Role")).toBeTruthy();
    expect(facts.get("Reports to")).toBeTruthy();
    expect(facts.get("Now at")).toBe("Not placed yet");
  });

  it("anything else has no extra facts, and an unknown id has none", () => {
    expect(factsOf(layout, layout.semantic.levels[0]?.id ?? "", state)).toEqual([]);
    expect(factsOf(layout, "nope", state)).toEqual([]);
  });

  it("a state's tone says finished, not started, lost or in progress", () => {
    expect(stateTone("Finished")).toBe("done");
    expect(stateTone("Not planned yet")).toBe("soon");
    expect(stateTone("Planned")).toBe("soon");
    expect(stateTone("Connection lost")).toBe("blocked");
    expect(stateTone("At work")).toBe("fyi");
  });
});
