// @vitest-environment happy-dom
// WEB-12 review fix: the shell puts focus on the page h1 after a route change, so the h1 must be the same
// DOM node while the user loads and after it arrives (and when the load fails), or React remounts it and
// the focus is lost.
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import type { Api } from "../../api";
import { createFixtureApi } from "../../api/fixtureApi";
import { cleanup, renderProfile, settle, spyApi } from "./testApp";

afterEach(cleanup);

describe("WEB_12_profile_focus: one h1 across states", () => {
  it("WEB_12_profile_h1_is_the_same_node_across_loading_and_loaded", async () => {
    const base = createFixtureApi();
    let release: () => void = () => undefined;
    const held = new Promise<void>((r) => {
      release = r;
    });
    const api: Api = {
      ...spyApi(base),
      getUser: vi.fn(async () => {
        await held;
        return base.getUser();
      }),
    };
    const { root } = await renderProfile(makeApp(), api);
    const loading = root.querySelector("h1");
    expect(loading?.textContent, "the loading heading").toBe("Profile");
    loading?.focus();
    release();
    await settle();
    const loaded = root.querySelector("h1");
    expect(loaded?.textContent).toBe("Alex Morgan");
    expect(loaded === loading, "the same element, not a remount").toBe(true);
    expect(document.activeElement).toBe(loaded);
  });

  it("WEB_12_profile_h1_is_the_same_node_when_the_load_fails", async () => {
    let fail: (e: Error) => void = () => undefined;
    const held = new Promise<never>((_, reject) => {
      fail = reject;
    });
    const api: Api = { ...spyApi(), getUser: vi.fn(() => held) };
    const { root } = await renderProfile(makeApp(), api);
    const loading = root.querySelector("h1");
    fail(new Error("boom"));
    await settle();
    expect(root.querySelector("h1") === loading).toBe(true);
    expect(root.textContent).toContain("Your profile could not be loaded");
  });
});
