// @vitest-environment happy-dom
// WEB-CUTOVER: an address that is neither a Park page nor a screen the old app owns is the Park "Page not
// found" (with a link Home), never the old StartScreen. `/start` is the old app's explicit intake address.
// The old App is mocked; the Park app is the real one.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../test-support/park/componentsHarness";

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

describe("WEB_CUTOVER_root_kept: unknown addresses are the Park not-found", () => {
  it.each(["/xyz", "/world/x/unknown", "/world", "/start/x", "/team/x", "/parkour", "/parks/home"])(
    "WEB_CUTOVER_root_kept_%s_is_the_park_not_found_with_a_link_home",
    async (path) => {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(0);
      expect(qa(m.container, '[data-testid="park-not-found"]'), path).toHaveLength(1);
      const home = qa<HTMLAnchorElement>(m.container, '[data-testid="park-not-found"] a').find(
        (a) => a.textContent?.trim() === "Go to Home",
      );
      expect(home?.getAttribute("href"), path).toBe("/");
      m.unmount();
    },
  );

  it("WEB_CUTOVER_root_kept_start_is_the_old_app", async () => {
    const m = await visit("/start");
    expect(q(m.container, '[data-testid="old-app"]')).toBeTruthy();
    expect(qa(m.container, '[data-testid="park-not-found"]')).toHaveLength(0);
    expect(qa(m.container, "[data-park]")).toHaveLength(0);
  });

  it.each(["/more", "/settings", "/world/w/stage", "/team/console"])(
    "WEB_CUTOVER_root_kept_%s_stays_the_old_app",
    async (path) => {
      const m = await visit(path);
      expect(qa(m.container, '[data-testid="old-app"]'), path).toHaveLength(1);
      expect(qa(m.container, '[data-testid="park-not-found"]'), path).toHaveLength(0);
      m.unmount();
    },
  );
});
