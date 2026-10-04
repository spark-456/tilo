// PRD 18.6 / issue #227 (audit auto-FAIL): the world screen has no layout shift while the replay
// fills the rail, and the Trace list is a keyboard-reachable scroll region with a name.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP } from "./support/viewports";

test.use({ viewport: DESKTOP });

for (const query of ["?fixture=village-basic&seq=44", "?fixture=village-basic"]) {
  test(`PRD-18.6 world ${query}: zero layout shift while the rail fills`, async ({ page }) => {
    await watchShifts(page);
    await page.goto(`/world/w_village_basic${query}`);
    await expect(page.getByTestId("trace-list")).toBeVisible();
    await expect(page.getByTestId("hud-meter")).toContainText(/credits/);
    expect(await readShifts(page)).toEqual([]);
  });
}

test("PRD-18.6 the Trace list is focusable with a name, and axe finds no violation", async ({
  page,
}) => {
  await page.goto("/world/w_village_basic?fixture=village-basic&seq=44");
  const list = page.getByTestId("trace-list");
  await expect(list).toHaveAttribute("tabindex", "0");
  await expect(list).toHaveAttribute("aria-label", "Trace");
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(axe.violations).toEqual([]);
});
