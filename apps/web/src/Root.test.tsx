// @vitest-environment happy-dom
// WEB-3a: the mount point. Pinned: apps/web/src/Root.tsx exports `Root()`; main.tsx renders <Root/>.
// Root shows the existing <App/> (unchanged) unless the pathname is a Park path (`isParkPath` from
// park/app/router), then the lazily imported park/app/ParkApp (default export) inside <Suspense>.
// NFR-01: the park chunk is a dynamic import, so a landing visit never loads it.
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
  it("WEB_3a_root_a_landing_visit_never_loads_the_park_chunk", async () => {
    await visit("/");
    await visit("/worlds");
    expect(loaded.park).toBe(0);
  });

  it("WEB_3a_root_every_non_park_path_is_the_old_app", async () => {
    for (const path of [
      "/",
      "/worlds",
      "/world/k1",
      "/task/t1/understanding",
      "/parkour",
      "/parks/home",
    ]) {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid="park-app"]'), path).toHaveLength(0);
      m.unmount();
    }
  });

  it("WEB_3a_root_every_park_path_is_the_park_app", async () => {
    for (const path of ["/park", "/park/", "/park/home", "/park/world/k1", "/park/nope"]) {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="park-app"]'), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(0);
      m.unmount();
    }
  });

  it("WEB_3a_root_moving_between_the_apps_follows_the_address", async () => {
    const m = await visit("/");
    expect(q(m.container, '[data-testid="old-app"]')).toBeTruthy();
    await act(async () => navigateFlow("/park/home"));
    await settle();
    expect(m.container.querySelector('[data-testid="park-app"]')).not.toBeNull();
    expect(m.container.querySelector('[data-testid="old-app"]')).toBeNull();
    await act(async () => navigateFlow("/worlds"));
    await settle();
    expect(m.container.querySelector('[data-testid="old-app"]')).not.toBeNull();
  });
});
