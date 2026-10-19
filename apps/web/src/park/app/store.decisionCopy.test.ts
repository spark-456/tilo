// WEB-3b: the toast text for a decision is the Api's designed copy (Decision.toast), never text in the store.
// Without it (live mode before the endpoint exists, or before the shell has handed it over) the toast is a
// plain line built from the item's own fields, or a neutral generic one. A world with no id opens the list.
import { describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { decisions } from "../api/fixtures/decisions";
import { createParkStore } from "./store";

function setup() {
  const navigate = vi.fn();
  const sch = fakeScheduler();
  const store = createParkStore({ api: fakeApi(), navigate, schedule: sch.schedule });
  return { navigate, store };
}

describe("WEB_3b_store_copy: the decision toast comes from the data", () => {
  it("WEB_3b_store_copy_the_toast_is_the_decisions_own_toast_field", () => {
    const { store } = setup();
    store.setDecisions(decisions.map((d) => ({ ...d, toast: `Done: ${d.k}` })));
    store.decide("mail");
    expect(store.getState().toast?.message).toBe("Done: mail");
  });

  it("WEB_3b_store_copy_without_a_toast_field_it_is_built_from_the_items_title_and_done_lines", () => {
    const { store } = setup();
    store.setDecisions(decisions.map((d) => ({ ...d, toast: "" })));
    store.decide("depot");
    const d = decisions.find((x) => x.k === "depot");
    expect(store.getState().toast?.message).toBe(`${d?.title}: ${d?.done}`);
  });

  it("WEB_3b_store_copy_with_no_decisions_at_all_it_is_a_neutral_line", () => {
    const { store } = setup();
    store.decide("depot");
    expect(store.getState().toast?.message).toBe("Decision recorded");
  });
});
