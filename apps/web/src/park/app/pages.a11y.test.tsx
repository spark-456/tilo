// @vitest-environment jsdom
// M2-A11Y-1: DOM semantics at two viewport inputs. jsdom has no layout engine;
// contrast and target geometry require browser evidence and are not claimed here.
import axe from "axe-core";
import { Suspense, act, lazy } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { fakeApi, stubApp } from "../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { REAL_PAGES } from "../../../test-support/park/realPages";
import { worlds } from "../api/fixtures";
import { ParkProvider } from "./context";
import { PAGES } from "./pages";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
const QuizPage = lazy(() =>
  import("../pages/QuizPlayer/QuizPlayerPage").then((module) => ({
    default: module.QuizPlayerPage,
  })),
);
const AUDIT_PAGES = [...REAL_PAGES, "quiz"] as const;
for (const width of [390, 1440]) {
  for (const page of AUDIT_PAGES) {
    it(`FR_MTG_08 M2_A11Y_1 ${page} DOM semantics with ${width}px viewport input`, async () => {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
      Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
      // Page graphics remain decorative; canvas rendering has separate browser tests.
      vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
      // jsdom does not create SVG blob URLs. Keep the real image/alt DOM while
      // providing only this missing platform primitive, without fetching art.
      class PageURL extends URL {
        static createObjectURL() {
          return "blob:park-structural-audit";
        }
        static revokeObjectURL() {}
      }
      vi.stubGlobal("URL", PageURL);
      const app = stubApp(page === "quiz" ? "world" : page, {
        vw: width,
        vh: 900,
        params: page === "world" ? { id: worlds()[0]?.id ?? "k1" } : {},
      });
      const Page = page === "quiz" ? QuizPage : PAGES[page];
      const api = fakeApi();
      const view = mount(
        <ParkProvider api={api} worldClient={null}>
          <main data-park="" aria-label="Park page">
            <Suspense fallback={<p>Loading page</p>}>
              <Page app={app} />
            </Suspense>
          </main>
        </ParkProvider>,
      );
      for (let attempt = 0; attempt < 100; attempt++) {
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 20));
        });
        if (view.container.querySelector(`[data-testid="park-page-${page}"]`)) break;
      }
      expect(view.container.querySelector(`[data-testid="park-page-${page}"]`)).not.toBeNull();
      // Loading placeholders are not an audit of the ready page.
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      const result = await axe.run(view.container, {
        runOnly: {
          type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa", "best-practice"],
        },
        rules: { "color-contrast": { enabled: false }, "target-size": { enabled: false } },
      });
      const failures = result.violations.map(
        (rule) => `${rule.id}: ${rule.nodes.map((node) => node.target.join(" ")).join("; ")}`,
      );
      expect(failures, failures.join("\n")).toEqual([]);
      const incomplete = result.incomplete.map((rule) => rule.id);
      expect(incomplete, "These checks require manual review; they are not passing checks").toEqual(
        [],
      );
    });
  }
}
