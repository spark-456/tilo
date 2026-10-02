import { describe, expect, it, vi } from "vitest";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { findItem } from "../screens/findItem";
import { getSelection, involves, objectIds, select, subscribeSelection } from "./selection";

const events = EVENTS_VILLAGE_BASIC;
const seqsInvolving = (id: string) => events.filter((e) => involves(e, id)).map((e) => e.seq);

describe("FR-WLD-06 one selection per run, shared by World, Story, Trace and Inspect", () => {
  it("FR_WLD_06 a selection is scoped to its world and tells every lens at once", () => {
    const seen = vi.fn();
    const stop = subscribeSelection(seen);
    select("w_a", "A_s1");
    expect(getSelection("w_a")).toBe("A_s1");
    expect(getSelection("w_b")).toBeNull();
    expect(seen).toHaveBeenCalledTimes(1);
    select("w_a", "A_s1"); // the same id again changes nothing, so nothing re-renders
    expect(seen).toHaveBeenCalledTimes(1);
    select("w_a", null);
    expect(getSelection("w_a")).toBeNull();
    stop();
    select("w_a", "A_s2");
    expect(seen).toHaveBeenCalledTimes(2);
    select("w_a", null);
  });

  it("FR_WLD_06 an event involves an agent as actor or target, never by guess", () => {
    expect(seqsInvolving("A_s1")).toEqual([14, 18, 19, 20, 21, 22, 23, 24, 25, 27, 40]);
    expect(seqsInvolving("A_nobody")).toEqual([]);
  });

  it("FR_WLD_06 an event involves an artifact through its item or target", () => {
    expect(seqsInvolving("art_triage_list")).toEqual([25, 27, 41]);
  });

  it("FR_WLD_06 an event involves a level or district it was recorded in", () => {
    expect(seqsInvolving("L1")).toContain(5);
    expect(seqsInvolving("D1")).toContain(6);
    expect(seqsInvolving("D1")).not.toContain(1);
  });

  it("FR_WLD_06 every object the layout and events produce can be selected and inspected", () => {
    const ids = objectIds(LAYOUT_VILLAGE_BASIC, events);
    for (const id of [
      "A_dir",
      "A_s1",
      "L1",
      "D1",
      "B1",
      "I1",
      "art_triage_list",
      "art_reply_draft",
    ]) {
      expect(ids.has(id), id).toBe(true);
      expect(findItem(LAYOUT_VILLAGE_BASIC, id, events), id).not.toBeNull();
    }
    expect(ids.has("u_owner")).toBe(false); // a person is not an object of the world
    expect(findItem(LAYOUT_VILLAGE_BASIC, "nothing", events)).toBeNull();
    expect(findItem(LAYOUT_VILLAGE_BASIC, "art_triage_list", events)?.kind).toBe("Artifact");
    expect(findItem(LAYOUT_VILLAGE_BASIC, "art_triage_list", [])).toBeNull(); // no event, no artifact
  });
});
