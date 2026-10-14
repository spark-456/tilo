// OLD-UI-OUT waves 1-4: only development galleries remain in the old shell.
// @vitest-environment happy-dom
// OLD-UI-OUT Final: the mount point. Pinned: apps/web/src/Root.tsx exports `Root()`; main.tsx renders <Root/>.
// The old app is deleted, so every address is the lazily imported park/app/ParkApp (default export) inside
// <Suspense>: a Park page, its own "Page not found", or a routed world view (worldView/). A retired bookmark is
// replaced by its Park home before anything renders.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../test-support/park/componentsHarness";
import { navigateFlow } from "./router";

vi.mock("./park/app/ParkApp", async () => {
  const { createElement } = await import("react");
  const ParkApp = (props: { routed?: { title: string } }) =>
    createElement(
      "div",
      { "data-testid": "park-app", "data-routed": props.routed?.title ?? "" },
      "park app",
    );
  return { default: ParkApp, ParkApp };
});

import { Root } from "./Root";

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};
const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<Root />);
  await settle();
  return m;
};

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

describe("WEB_3a_root: the Park app serves every address", () => {
  it("OLD_UI_OUT_final_root_every_address_is_the_park_app", async () => {
    for (const path of [
      "/",
      "/settings",
      "/worlds",
      "/world/k1",
      "/team",
      "/library",
      "/settings",
      "/more",
      "/park",
      "/park/home",
      "/park/nope",
      "/xyz",
    ]) {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="park-app"]'), path).toHaveLength(1);
      m.unmount();
    }
  });

  it("OLD_UI_OUT_final_root_a_lens_or_needs_you_address_is_the_park_app_with_a_routed_view", async () => {
    const titles: Array<[string, string]> = [
      ["/world/w/stage", "World"],
      ["/world/w/story", "Story"],
      ["/world/w/trace", "Trace"],
      ["/world/w/delivery", "Delivery"],
      ["/world/w/inspect/B1", "Inspect"],
      ["/needs-you", "Needs you"],
      ["/needs-you/gate", "Approval gate"],
      ["/needs-you/consent", "Connection consent"],
    ];
    for (const [path, title] of titles) {
      const m = await visit(path);
      const park = qa(m.container, '[data-testid="park-app"]');
      expect(park, path).toHaveLength(1);
      expect(park[0]?.getAttribute("data-routed"), path).toBe(title);
      m.unmount();
    }
    // A plain Park page carries no routed view.
    const home = await visit("/worlds");
    expect(q(home.container, '[data-testid="park-app"]')?.getAttribute("data-routed")).toBe("");
    home.unmount();
  });

  it("OLD_UI_OUT_final_root_a_retired_intake_address_is_replaced_by_home", async () => {
    for (const path of ["/start", "/task/t1/understanding", "/task/t1/approaches"]) {
      const m = await visit(path);
      expect(window.location.pathname, path).toBe("/");
      expect(qa(m.container, '[data-testid="park-app"]'), path).toHaveLength(1);
      m.unmount();
    }
  });

  it("OLD_UI_OUT_final_root_navigation_stays_in_the_park_app", async () => {
    const m = await visit("/worlds");
    await act(async () => navigateFlow("/library"));
    await settle();
    expect(qa(m.container, '[data-testid="park-app"]')).toHaveLength(1);
  });
});
