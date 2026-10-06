// PRD 18.6 / issue #227 (audit auto-FAIL): the world screen has no layout shift while the replay
// loads and finishes, at 1440x900, 390x844 and 320x640, in normal and stage mode (the replay
// region's banner and position line wrap to more lines when narrow or scaled), and the Trace list
// is a keyboard-reachable scroll region with a name. Professional density in stage mode at 1920x1080
// is covered too: its team slot once shifted when the team arrived (#312).
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";

const SMALL = { width: 320, height: 640 } as const;
const VIEWPORTS = [DESKTOP, MOBILE, SMALL] as const;
const QUERIES = ["?fixture=village-basic&seq=44", "?fixture=village-basic&speed=100"];

for (const viewport of VIEWPORTS) {
  for (const display of ["", "&display=stage"]) {
    for (const query of QUERIES) {
      test(`PRD-18.6 world ${query}${display} at ${viewport.width}x${viewport.height}: zero layout shift while the replay loads`, async ({
        page,
      }) => {
        test.setTimeout(60_000);
        await page.setViewportSize(viewport);
        await watchShifts(page);
        await page.goto(`/world/w_village_basic${query}${display}`);
        await expect(page.getByTestId("replay-banner")).toContainText("Replay of run", {
          timeout: 20_000,
        });
        if (viewport === DESKTOP) {
          await expect(page.getByTestId("trace-list")).toBeVisible();
          await expect(page.getByTestId("hud-meter")).toContainText(/credits/);
        }
        expect(await readShifts(page)).toEqual([]);
      });
    }
  }
}

test("FR-WLD-14 Professional stage mode at 1920x1080: zero layout shift while the team arrives", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.addInitScript(() => window.localStorage.setItem("tilo.density", "professional"));
  await watchShifts(page);
  await page.goto("/world/w_village_basic?fixture=village-basic&seq=44&display=stage");
  await expect(page.getByTestId("replay-banner")).toContainText("Replay of run", {
    timeout: 20_000,
  });
  await expect(page.locator(".hud-slot").getByRole("heading", { name: "Team" })).toBeVisible();
  await expect(page.locator(".hud-slot .rows").first()).toBeVisible();
  expect(await readShifts(page)).toEqual([]);
});

test("PRD-18.6 the Trace list is focusable with a name, and axe finds no violation", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto("/world/w_village_basic?fixture=village-basic&seq=44");
  const list = page.getByTestId("trace-list");
  await expect(list).toHaveAttribute("tabindex", "0");
  await expect(list).toHaveAttribute("aria-label", "Trace");
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(axe.violations).toEqual([]);
});
