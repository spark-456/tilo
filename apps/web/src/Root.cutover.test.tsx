// OLD-UI-OUT waves 1-4: only development galleries remain in the old shell.
// @vitest-environment happy-dom
// WEB-CUTOVER, after OLD-UI-OUT Final: the mount point renders the real Park app with the real page registry, so
// "/" really is the Park Home (data-testid="park-page-home"), an address no page owns is the Park "Page not
// found" with a link Home, and a retired intake address goes to Home. No old app exists to fall back to.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../test-support/park/componentsHarness";
import { Root } from "./Root";
import { navigateFlow } from "./router";

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

describe("WEB_CUTOVER_root: the Park app owns every address", () => {
  it("WEB_CUTOVER_05_root_renders_the_park_home", async () => {
    const m = await visit("/");
    expect(qa(m.container, '[data-testid="park-page-home"]')).toHaveLength(1);
    expect(qa(m.container, "[data-park]")).toHaveLength(1);
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
      m.unmount();
    }
  });

  it.each(["/xyz", "/world/x/unknown", "/world", "/start/x", "/team/x", "/parkour", "/park/nope"])(
    "WEB_CUTOVER_root_%s_is_the_park_not_found_with_a_link_home",
    async (path) => {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="park-not-found"]'), path).toHaveLength(1);
      const home = qa<HTMLAnchorElement>(m.container, '[data-testid="park-not-found"] a').find(
        (a) => a.textContent?.trim() === "Go to Home",
      );
      expect(home?.getAttribute("href"), path).toBe("/");
      m.unmount();
    },
  );

  it("OLD_UI_OUT_final_root_start_goes_to_the_park_home", async () => {
    const m = await visit("/start");
    expect(qa(m.container, '[data-testid="park-page-home"]')).toHaveLength(1);
    expect(window.location.pathname).toBe("/");
  });

  it("WEB_CUTOVER_05_navigation_moves_between_park_pages", async () => {
    const m = await visit("/");
    expect(m.container.querySelector('[data-testid="park-page-home"]')).not.toBeNull();
    await act(async () => navigateFlow("/worlds"));
    await settle();
    expect(m.container.querySelector('[data-testid="park-page-worlds"]')).not.toBeNull();
  });
});
