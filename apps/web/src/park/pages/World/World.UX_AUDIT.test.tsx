// @vitest-environment happy-dom
// UX-AUDIT: the World page's back arrow keeps its name when the Studio theme hides its words, and "Ask me later"
// promises no reminder that does not exist.
import { afterEach, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { TOASTS } from "../../../../test-support/park/worldCopy";
import { mountWorld } from "../../../../test-support/park/worldHarness";

afterEach(cleanup);

it("UX_AUDIT_world_back_link_is_named_all_worlds", async () => {
  const { el } = await mountWorld({ id: "k1" });
  const back = el.querySelector("a.park-world-back");
  expect(back).not.toBeNull();
  expect(back?.getAttribute("aria-label")).toBe("All worlds");
  expect(back?.getAttribute("href")).toBe("/worlds");
});

it("UX_AUDIT_world_decide_later_copy_promises_no_reminder", () => {
  expect(TOASTS.later).not.toMatch(/remind|\d{1,2}:\d{2}/i);
  expect(TOASTS.later).toContain("Nothing was sent");
});
