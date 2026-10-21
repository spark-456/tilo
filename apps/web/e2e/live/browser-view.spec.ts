// DEMO-BROWSER (owner, 21 Oct: "the background bleeds through and this tilo browser is some broken component"): on a
// real run's World page the browser takes over the map area as a solid view (no map showing through), with the address,
// the step, a readable frame, the numbered steps, and only controls that work; a finished session says so. The fake
// tilo-api serves the recorded run plus one browser session whose frames are a drawn test picture.
// Local only: `TILO_LIVE=1 TILO_LIVE_PORT=5417 TILO_LIVE_API_PORT=5418 pnpm exec playwright test
//   e2e/live/browser-view.spec.ts --project=live --workers=1`. Screenshots land in this test's output folder.
import { type Page, expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;
const control = async (page: Page, body: Record<string, unknown>) =>
  expect((await page.request.post(`${API}/__control`, { data: body })).ok()).toBe(true);

const SIZES = [
  { name: "1440", width: 1440, height: 900 },
  { name: "1280", width: 1280, height: 800 },
  { name: "390", width: 390, height: 844 },
] as const;

for (const time of ["day", "night"] as const) {
  for (const size of SIZES) {
    test(`DEMO_BROWSER_e2e the browser view is solid and readable, ${time} ${size.name}`, async ({
      page,
    }, info) => {
      await control(page, { reset: true, events: 20, browser: "live" });
      await page.addInitScript((t) => window.localStorage.setItem("tilo.time", t), time);
      await page.setViewportSize({ width: size.width, height: size.height });
      await page.goto("/world/w_here");

      const view = page.getByTestId("tilo-browser-panel");
      await expect(view).toBeVisible({ timeout: 30_000 });
      await expect(view.locator(".tilo-bv__address")).toHaveText("encyclopedia.example");
      await expect(view.locator(".tilo-bv__badge")).toHaveText("Live");
      await expect(view.locator(".tilo-bv__shot img")).toBeVisible({ timeout: 15_000 });
      await expect(view.getByRole("button", { name: "Stop" })).toBeEnabled();
      await expect(view.getByRole("button", { name: "Pause" })).toHaveCount(0);
      await expect(view).not.toContainText("Coming later");

      // No bleed: the view covers the whole map area inside its 1px border, and is opaque.
      const map = page.locator(".park-world-map");
      const [viewBox, mapBox] = [await view.boundingBox(), await map.boundingBox()];
      expect(viewBox && mapBox).toBeTruthy();
      if (viewBox && mapBox) {
        expect(Math.abs(viewBox.x - mapBox.x)).toBeLessThanOrEqual(2);
        expect(Math.abs(viewBox.width - mapBox.width)).toBeLessThanOrEqual(2);
        expect(Math.abs(viewBox.height - mapBox.height)).toBeLessThanOrEqual(2);
      }
      const background = await view.evaluate((el) => getComputedStyle(el).backgroundColor);
      expect(background).not.toMatch(/rgba\(.*,\s*0(\.\d+)?\)$/);
      // The frame is as large as the area allows (fit to width, capped by height), and nothing scrolls inside the view.
      const shot = await view.locator(".tilo-bv__shot").boundingBox();
      expect(shot?.width ?? 0).toBeGreaterThan(size.width < 761 ? 260 : 560);
      const body = view.locator(".tilo-bv__body");
      expect(await body.evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true);
      // The line says the state (the step is in the label), and every footer button sits inside the view.
      await expect(view.locator(".tilo-bv__line")).toHaveText("Tilo is using the browser now.");
      for (const name of ["Earlier", "Later"]) {
        const box = await view.getByRole("button", { name, exact: true }).boundingBox();
        expect(box && viewBox && box.x + box.width <= viewBox.x + viewBox.width - 8).toBe(true);
      }
      await page.screenshot({ path: info.outputPath(`browser-live-${time}-${size.name}.png`) });

      // Click to enlarge: the whole window is the scrim, the picture fits inside it; Escape closes it and focus returns.
      await view.locator(".tilo-bv__shot").click();
      const zoom = page.locator("dialog.tilo-bv__zoom");
      await expect(zoom).toBeVisible();
      const [scrim, big] = [await zoom.boundingBox(), await zoom.locator("img").boundingBox()];
      expect(scrim).toEqual({ x: 0, y: 0, width: size.width, height: size.height });
      expect(
        big && big.y >= 0 && big.y + big.height <= size.height && big.width <= size.width,
      ).toBe(true);
      await page.screenshot({ path: info.outputPath(`browser-zoom-${time}-${size.name}.png`) });
      await page.keyboard.press("Escape");
      await expect(zoom).toHaveCount(0);
      await expect(view.locator(".tilo-bv__shot")).toBeFocused();

      // Finished: a clear state with the steps to replay, and no Stop.
      await control(page, { browser: "finished", events: 20 });
      await expect(view.locator(".tilo-bv__badge")).toHaveText("Finished", { timeout: 15_000 });
      await expect(view).toContainText("Finished: 4 steps");
      await expect(view.getByRole("button", { name: "Stop" })).toHaveCount(0);
      await view.getByRole("button", { name: "Step 2: Scrolling down" }).click();
      await expect(view.locator(".tilo-bv__label")).toContainText("Step 2 of 4");
      await page.screenshot({ path: info.outputPath(`browser-finished-${time}-${size.name}.png`) });

      // Back to map shows the map again, with a way back to the browser that covers none of the map's own controls.
      await view.getByRole("button", { name: "Back to map" }).click();
      const chip = page.getByRole("button", { name: /Show Tilo browser/ });
      await expect(chip).toBeVisible();
      const chipBox = await chip.boundingBox();
      for (const other of [".park-world-tag", ".park-world-lenses"]) {
        const box = await map.locator(other).boundingBox();
        const apart =
          !chipBox ||
          !box ||
          chipBox.x + chipBox.width <= box.x ||
          box.x + box.width <= chipBox.x ||
          chipBox.y + chipBox.height <= box.y ||
          box.y + box.height <= chipBox.y;
        expect(apart, `the chip overlaps ${other}`).toBe(true);
      }
      await page.screenshot({ path: info.outputPath(`browser-map-${time}-${size.name}.png`) });
    });
  }
}
