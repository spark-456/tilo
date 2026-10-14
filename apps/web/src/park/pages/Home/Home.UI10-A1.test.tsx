// @vitest-environment happy-dom
// UI-10 / A1 (14 Oct QA, home): the panels above the composer stop where the composer really starts.
// The page publishes the composer's measured height as --park-home-composer-h (and --park-home-panel-h, the
// same without the chips row) on its root; Home.css reads both. The boxes themselves are checked in a real
// browser by e2e/park-home-a1-fit.spec.ts.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { mountHome } from "../../../../test-support/park/homeHarness";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("UI_10_A1_composer_clearance: the composer's height reaches the stylesheet", () => {
  const watched: Element[] = [];
  beforeEach(() => {
    watched.length = 0;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe(el: Element) {
          watched.push(el);
        }
        disconnect() {}
        unobserve() {}
      },
    );
  });

  it("UI_10_A1_the_home_root_carries_both_clearance_properties_and_the_composer_is_watched", async () => {
    const { el } = await mountHome({});
    const root = el.querySelector<HTMLElement>('[data-testid="park-page-home"]');
    expect(root).not.toBeNull();
    expect(root?.style.getPropertyValue("--park-home-composer-h")).toMatch(/^\d+px$/);
    expect(root?.style.getPropertyValue("--park-home-panel-h")).toMatch(/^\d+px$/);
    expect(watched.map((n) => n.className)).toContain("park-home-composer");
  });
});

describe("UI_10_A1_stylesheet: the offsets are the measured height, not a constant", () => {
  const css = readFileSync(join(__dirname, "Home.css"), "utf8");

  it("UI_10_A1_the_greeting_column_bottom_follows_the_composer_height", () => {
    expect(css).toMatch(/bottom:\s*calc\(var\(--park-home-composer-h,\s*182px\)\s*\+\s*36px\)/);
    expect(css).not.toMatch(/bottom:\s*218px/);
  });

  it("UI_10_A1_the_today_panel_ends_above_the_composer_and_keeps_the_reference_cap", () => {
    expect(css).toContain("calc(100% - 330px)");
    expect(css).toMatch(/--park-home-composer-h,\s*198px\)\s*-\s*132px/);
    expect(css).toMatch(/--park-home-panel-h,\s*184px\)\s*-\s*132px/);
  });
});
