// @vitest-environment happy-dom
// WEB-QA-14OCT-1 (UI-10): when Home's reads fail, the greeting panel still sits in the column the sample strip
// is pinned above (it is placed by `.park-home-leftcol`, never by the page's top edge), so the strip cannot
// lie over "Not connected yet".
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountHome, pageText } from "../../../../test-support/park/homeHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WEB-QA-14OCT Home failed state", () => {
  it("UI-10 WEB-QA-14OCT the Not connected panel sits in the left column, below the sample strip", async () => {
    const api: Api = { ...createFixtureApi(), getUser: () => Promise.reject(new Error("down")) };
    const { el } = await mountHome({ api });
    expect(pageText(el)).toContain("Not connected yet");
    const hero = el.querySelector(".park-home-hero");
    expect(hero?.closest(".park-home-leftcol")).not.toBeNull();
  });
});
