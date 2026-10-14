// @vitest-environment happy-dom
// WEB-3a: the mount point. Pinned: apps/web/src/Root.tsx exports `Root()`; main.tsx renders <Root/>.
// Root shows the existing <App/> (unchanged) unless the pathname is a Park path (`isParkPath` from
// park/app/router: the root pages and the /park alias, WEB-CUTOVER), then the lazily imported
// park/app/ParkApp (default export) inside <Suspense>.
// NFR-01: the park chunk is a dynamic import, so a visit to a kept (old-app) screen never loads it. The
// landing page `/` is the Park Home since WEB-CUTOVER, so it is no longer the case to pin here.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../test-support/park/componentsHarness";
import { navigateFlow } from "./router";

const loaded = vi.hoisted(() => ({ park: 0 }));

vi.mock("./App", async () => {
  const { createElement } = await import("react");
  return { App: () => createElement("div", { "data-testid": "old-app" }, "old app") };
});
vi.mock("./park/app/ParkApp", async () => {
  const { createElement } = await import("react");
  loaded.park += 1;
  const ParkApp = () => createElement("div", { "data-testid": "park-app" }, "park app");
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

describe("WEB_3a_root: old app or park app by path", () => {
  // Must stay the first test that renders: the lazy import is cached for the rest of the file.
  it("WEB_3a_root_a_visit_to_a_kept_screen_never_loads_the_park_chunk", async () => {
    await visit("/more");
    await visit("/world/w/stage");
    await visit("/team/console");
    expect(loaded.park).toBe(0);
  });

  // `/world`, `/parkour` and `/parks/home` own no screen: they are the Park "Page not found" now
  // (Root.kept.test.tsx), so the old app's list is the addresses it keeps.
  it("WEB_3a_root_every_non_park_path_is_the_old_app", async () => {
    for (const path of [
      "/more",
      "/world/w/stage",
      "/world/w/story",
      "/team/console",
    ]) {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid="park-app"]'), path).toHaveLength(0);
      m.unmount();
    }
  });

  it("WEB_3a_root_every_park_path_and_root_page_is_the_park_app", async () => {
    for (const path of [
      "/",
      "/settings",
      "/worlds",
      "/world/k1",
      "/team",
      "/park",
      "/park/",
      "/park/home",
      "/park/world/k1",
      "/park/nope",
    ]) {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="park-app"]'), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(0);
      m.unmount();
    }
  });

  it("WEB_3a_root_moving_between_the_apps_follows_the_address", async () => {
    const m = await visit("/more");
    expect(q(m.container, '[data-testid="old-app"]')).toBeTruthy();
    await act(async () => navigateFlow("/park/home"));
    await settle();
    expect(m.container.querySelector('[data-testid="park-app"]')).not.toBeNull();
    expect(m.container.querySelector('[data-testid="old-app"]')).toBeNull();
    await act(async () => navigateFlow("/world/w/stage"));
    await settle();
    expect(m.container.querySelector('[data-testid="old-app"]')).not.toBeNull();
  });
});
