import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { gotoStage } from "./support/camera";
import { DESKTOP } from "./support/viewports";

const W = "/world/w_village_basic";
const FAST = "?speed=100";

test.describe("WLD-11 Accessibility", () => {
  test("keyboard world outline lists agents, buildings and gates and selects on Enter/Space with 2px focus ring", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await gotoStage(page, "/?fixture=village-basic");
    const outline = page.getByRole("list", { name: "World objects" });
    const buttons = outline.getByRole("button");
    await expect(buttons.first()).toBeAttached();

    // Contains agent, building, and gate items
    await expect(outline.getByRole("button", { name: /Specialist 1/ })).toBeAttached();
    await expect(outline.getByRole("button", { name: /Mail Room/ })).toBeAttached();
    await expect(outline.getByRole("button", { name: /Gate G1/ })).toBeAttached();

    // Focus shows a visible 2px focus ring and Enter / Space toggles selection
    const first = buttons.first();
    await first.focus();
    const outlineStyle = await first.evaluate((el) => {
      const s = getComputedStyle(el);
      return { width: s.outlineWidth, style: s.outlineStyle };
    });
    expect(outlineStyle.width).toBe("2px");
    expect(outlineStyle.style).toBe("solid");

    await page.keyboard.press("Enter");
    await expect(first).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("Space");
    await expect(first).toHaveAttribute("aria-pressed", "false");
  });

  test("story lens is polite and rows have accessible names", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto(`${W}/story${FAST}`);
    const log = page.getByRole("log", { name: "What happened, in order" });
    await expect(log).toHaveAttribute("aria-live", "polite");
    await expect(log.getByRole("listitem").first()).toHaveAttribute("aria-label", /Step \d+:/);
  });

  for (const mode of ["no-preference", "reduce"] as const) {
    test(`axe passes zero critical/serious issues on S-04, S-05, S-10, S-11, S-12, S-13 (${mode} motion)`, async ({
      page,
    }) => {
      test.setTimeout(90_000);
      await page.setViewportSize(DESKTOP);
      await page.emulateMedia({ reducedMotion: mode });

      const routes = [
        `${W}${FAST}`,
        `${W}/inspect/B1${FAST}`,
        `${W}/story${FAST}`,
        `${W}/trace${FAST}`,
        `${W}/delivery${FAST}`,
        `/library${FAST}`,
      ];

      for (const route of routes) {
        await page.goto(route);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
          .analyze();
        const severe = results.violations.filter(
          (v) => v.impact === "critical" || v.impact === "serious",
        );
        expect(severe, `axe violations on ${route} (${mode})`).toEqual([]);
      }
    });
  }
});
