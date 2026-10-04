import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { gotoStage, readCamera } from "./support/camera";
import { ALL_ROUTES } from "./support/routes";
import { watchConsole } from "./support/screens";
import { DESKTOP, MOBILE } from "./support/viewports";

const W = "/world/w_village_basic";
const FAST = "speed=100";
const BRAND = "rgb(90, 63, 224)"; // design/tokens.json color.brand.primary

const focusedText = (page: Page) =>
  page.evaluate(() => document.activeElement?.textContent?.trim() ?? "");

test.describe("FR-WLD-11 accessibility", () => {
  test("FR_WLD_11 keyboard outline: arrows move focus, Enter selects with Inspect, Escape clears", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await gotoStage(page, "/?fixture=village-basic");
    const outline = page.getByRole("list", { name: "World objects" });
    const items = outline.getByRole("button");
    await expect(outline.getByRole("button", { name: /Gate G1/ })).toBeAttached();
    await expect(outline.getByRole("button", { name: /Mail Room/ })).toBeAttached();

    await items.first().focus();
    const first = await focusedText(page);
    const camera = await readCamera(page);
    await page.keyboard.press("ArrowDown");
    expect(await focusedText(page)).not.toBe(first);
    await page.keyboard.press("ArrowUp");
    expect(await focusedText(page)).toBe(first);
    await page.keyboard.press("End");
    expect(await focusedText(page)).toMatch(/^Gate /);
    await page.keyboard.press("Home");
    expect(await focusedText(page)).toBe(first);
    expect(await readCamera(page), "arrows in the list never pan the stage").toEqual(camera);

    await page.keyboard.press("Enter");
    await expect(items.first()).toHaveAttribute("aria-pressed", "true");
    await expect(outline.getByRole("link", { name: "Inspect" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(outline.locator('[aria-pressed="true"]')).toHaveCount(0);
    expect(await focusedText(page), "focus stays on a real control").toBe(first);
    await page.keyboard.press("Space");
    await expect(items.first()).toHaveAttribute("aria-pressed", "true");
  });

  test("FR_WLD_11 Escape from the Inspect link clears the selection and keeps focus on the outline item", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await gotoStage(page, "/?fixture=village-basic");
    const outline = page.getByRole("list", { name: "World objects" });
    const first = outline.getByRole("button").first();
    await first.focus();
    await page.keyboard.press("Enter");
    const inspect = outline.getByRole("link", { name: "Inspect" });
    await expect(inspect).toBeVisible();
    await page.keyboard.press("Tab"); // from the item to its Inspect link
    await expect(inspect).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(outline.locator('[aria-pressed="true"]')).toHaveCount(0);
    await expect(first).toBeFocused();
  });

  test("FR_WLD_11 the keyboard outline is on the world route too, not only in fixture mode", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await gotoStage(page, `${W}?${FAST}`);
    const outline = page.getByRole("list", { name: "World objects" });
    await expect(outline.getByRole("button", { name: /Mail Room/ })).toBeAttached();
    await expect(outline.getByRole("button", { name: /Gate G1/ })).toBeAttached();
  });

  test("FR_WLD_11 focus ring is a visible 2 px solid brand outline on an outline item", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await gotoStage(page, "/?fixture=village-basic");
    const ring = (el: Element) => {
      const s = getComputedStyle(el);
      return { width: s.outlineWidth, style: s.outlineStyle, color: s.outlineColor };
    };
    await page.getByRole("list", { name: "World objects" }).getByRole("button").first().focus();
    expect(await page.evaluate(`(${ring})(document.activeElement)`)).toEqual({
      width: "2px",
      style: "solid",
      color: BRAND,
    });
  });

  test("FR_WLD_11 Clear moves focus to the selection bar, never to the page body", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto(`${W}/story?${FAST}`);
    const bar = page.getByTestId("selection-bar");
    await expect(bar).toBeVisible();
    await page.locator("button.pick").first().focus();
    await page.keyboard.press("Enter");
    await expect(bar).toHaveAttribute("data-selected-id", /.+/);
    await bar.getByRole("button", { name: "Clear" }).focus();
    await page.keyboard.press("Enter");
    await expect(bar).toHaveAttribute("data-selected-id", "");
    await expect(bar).toBeFocused();
  });

  test("FR_WLD_11 Story rows read as sentences with severity in text, announced by one polite status", async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    // Count every non-empty text the status ever holds: a replay must make none.
    await page.addInitScript(() => {
      const said: string[] = [];
      (window as unknown as { __said: string[] }).__said = said;
      new MutationObserver(() => {
        for (const o of document.querySelectorAll("output.sr-only")) {
          if (o.textContent) said.push(o.textContent);
        }
      }).observe(document, { subtree: true, childList: true, characterData: true });
    });
    await page.goto(`${W}/story?${FAST}`);
    const list = page.getByRole("list", { name: "What happened, in order" });
    await expect(list.getByRole("listitem").first()).toBeVisible();
    await expect(list.locator("li[aria-label]")).toHaveCount(0);
    await expect(list.locator('li[data-severity="needs_you"]').first()).toContainText("Needs you");
    await expect(page.getByRole("log")).toHaveCount(0);
    const status = page.locator("output.sr-only");
    await expect(status).toHaveAttribute("aria-live", "polite");
    await expect(status).toHaveAttribute("aria-atomic", "true");
    // A replay adds rows by the dozen; none of that is announced.
    await expect(list.getByRole("listitem")).not.toHaveCount(1);
    await expect(status).toHaveText("");
    expect(
      await page.evaluate(() => (window as unknown as { __said: string[] }).__said),
      "announcements made during a replay",
    ).toEqual([]);
  });

  test("FR_WLD_11 reduced motion: keyboard pan jumps at once", async ({ page }) => {
    await page.setViewportSize(DESKTOP);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await gotoStage(page, "/?fixture=village-basic");
    const before = await readCamera(page);
    await page.getByTestId("stage-frame").focus();
    await page.keyboard.press("ArrowRight");
    const after = await readCamera(page);
    expect(after.x, "the camera is already at its target after the key press").toBeLessThan(
      before.x,
    );
  });

  for (const [name, viewport] of [
    ["1440x900", DESKTOP],
    ["390x844", MOBILE],
  ] as const) {
    test(`FR_WLD_11 axe: every routed screen is clean at ${name}`, async ({ page }) => {
      test.setTimeout(480_000);
      const problems = watchConsole(page);
      await page.setViewportSize(viewport);
      for (const route of ALL_ROUTES) {
        await page.goto(`${route}?${FAST}`);
        await expect(page.locator("h1").first(), `h1 on ${route} at ${name}`).toBeVisible({
          timeout: 20_000,
        });
        const axe = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .analyze();
        expect(axe.violations, `axe violations on ${route} at ${name}`).toEqual([]);
      }
      expect(problems).toEqual([]);
    });
  }
});
