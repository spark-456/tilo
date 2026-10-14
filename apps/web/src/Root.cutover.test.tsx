// @vitest-environment happy-dom
// WEB-CUTOVER: the mount point after the cutover. Root shows the Park app for `isParkPath(pathname)`
// (every root Park path and the /park alias), else <App/>. The old App is mocked; the Park app is the real
// one with the real page registry, so "/" really renders the Park Home (data-testid="park-page-home").
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../test-support/park/componentsHarness";
import { navigateFlow } from "./router";

vi.mock("./App", async () => {
  const { createElement } = await import("react");
  return { App: () => createElement("div", { "data-testid": "old-app" }, "old app") };
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

describe("WEB_CUTOVER_root: the Park app owns the root paths", () => {
  it("WEB_CUTOVER_05_root_renders_the_park_home", async () => {
    const m = await visit("/");
    expect(qa(m.container, '[data-testid="park-page-home"]')).toHaveLength(1);
    expect(qa(m.container, "[data-park]")).toHaveLength(1);
    expect(qa(m.container, '[data-testid="old-app"]')).toHaveLength(0);
  });

  it("WEB_CUTOVER_05_every_root_park_path_is_the_park_app_with_its_page", async () => {
    const table = [
      ["/", "home"],
      ["/worlds", "worlds"],
      ["/world/k1", "world"],
      ["/team", "team"],
      ["/connectors", "connectors"],
      ["/skills", "skills"],
      ["/agenda", "agenda"],
      ["/ledger", "ledger"],
      ["/profile", "profile"],
      ["/settings", "settings"],
      ["/park/home", "home"],
      ["/park/worlds", "worlds"],
    ] as const;
    for (const [path, id] of table) {
      const m = await visit(path);
      expect(qa(m.container, `[data-testid="park-page-${id}"]`), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(0);
      m.unmount();
    }
  });

  it("WEB_CUTOVER_05_the_stage_and_every_kept_screen_is_the_old_app", async () => {
    for (const path of [
      "/world/w/stage",
      "/world/w/story",
      "/world/w/inspect/B1",
      "/team/console",
      "/worlds/replays",
      "/task/t1/understanding",
      "/task/t1/approaches",
      "/needs-you",
      "/library",
      "/more",
      "/start",
    ]) {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(1);
      expect(qa(m.container, "[data-park]"), path).toHaveLength(0);
      m.unmount();
    }
  });

  it("WEB_CUTOVER_05_an_unknown_park_alias_path_shows_the_park_not_found_page", async () => {
    const m = await visit("/park/nope");
    expect(qa(m.container, '[data-testid="park-not-found"]')).toHaveLength(1);
    expect(qa(m.container, '[data-testid="old-app"]')).toHaveLength(0);
  });

  it("WEB_CUTOVER_05_moving_between_the_apps_follows_the_address", async () => {
    const m = await visit("/");
    expect(m.container.querySelector('[data-testid="park-page-home"]')).not.toBeNull();
    await act(async () => navigateFlow("/world/w/stage"));
    await settle();
    expect(m.container.querySelector('[data-testid="old-app"]')).not.toBeNull();
    expect(m.container.querySelector("[data-park]")).toBeNull();
    await act(async () => navigateFlow("/worlds"));
    await settle();
    expect(m.container.querySelector('[data-testid="park-page-worlds"]')).not.toBeNull();
    expect(m.container.querySelector('[data-testid="old-app"]')).toBeNull();
    await act(async () => navigateFlow("/team/console"));
    await settle();
    expect(m.container.querySelector('[data-testid="old-app"]')).not.toBeNull();
  });
});
