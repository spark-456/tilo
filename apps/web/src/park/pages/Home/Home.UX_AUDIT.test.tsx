// @vitest-environment happy-dom
// UX-AUDIT: "See all" on Home's Needs you card opens the Needs you page (it opened Worlds).
import { afterEach, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { clickEl, lastGo, mountHome } from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

it("UX_AUDIT_home_needs_you_see_all_opens_the_needs_you_page", async () => {
  const rig = await mountHome();
  const card = rig.el.querySelector(".park-home-card--needs");
  expect(card, "the Needs you card").not.toBeNull();
  const seeAll = [...(card?.querySelectorAll("a") ?? [])].find(
    (a) => a.textContent?.trim() === "See all",
  );
  expect(seeAll?.getAttribute("href")).toBe("/needs");
  expect(clickEl(seeAll as Element), "a plain click is routed in the app").toBe(false);
  expect(lastGo(rig.app)?.[0]).toBe("needs");
});
