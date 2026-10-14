// E2E-ONESTEP (HR-1): a real world's meta line and run card say only what the list and the events served. The list
// has no owner name and no agent count, and a real run records no building events, so none of those is printed as a
// number or a blank ("Owned by · started 2026-10-14T13:56:06.775Z · 0 agents", "Buildings 0 of 0 finished").
import { describe, expect, it } from "vitest";
import { runProgress } from "./runProgress";
import { metaLine, startedWord } from "./worldModel";

describe("E2E_ONESTEP the meta line", () => {
  it("E2E_ONESTEP_an_unserved_owner_and_agent_count_are_left_out_and_the_day_is_words", () => {
    expect(metaLine("", "2026-10-14T13:56:06.775Z", 0)).toBe("started 14 Oct");
  });
  it("E2E_ONESTEP_the_run_s_own_agent_count_is_named", () => {
    expect(metaLine("Alex Morgan", "2026-10-14T13:56:06.775Z", 6)).toBe(
      "Owned by Alex Morgan · started 14 Oct · 6 agents",
    );
  });
  it("E2E_ONESTEP_a_sample_s_own_words_are_kept", () => {
    expect(startedWord("16 Sep")).toBe("16 Sep");
  });
  it("E2E_ONESTEP_a_run_with_no_building_event_has_no_building_count", () => {
    const events = [
      { seq: 1, type: "world.started", ts: "2026-10-14T13:56:06.775Z", credits: 0, summary: "s" },
    ];
    expect(runProgress(events).buildings).toEqual({ planned: 0, done: 0 });
  });
});
