// DEMO-BROWSER (owner, 21 Oct: "the background bleeds through and this tilo browser is some broken component", then "the
// cursor must do real work, not pretend"): on a real run's World page the browser takes over the map area as a solid
// view (no map showing through), with the address, the step, a readable frame, the numbered steps, and only controls that
// work; the cursor is drawn only where a recorded click, typed field or scroll had a real target, on the page
// as it was before and as it is after; the window drags out of the map and docks back; "Open in new tab" opens the same
// browser as a page of its own. A finished session says so. The fake tilo-api serves the recorded run plus one browser
// session (started, type with Enter, click, scroll, scroll, extract) whose frames are a drawn test picture.
// Local only: `TILO_LIVE=1 TILO_LIVE_PORT=5417 TILO_LIVE_API_PORT=5418 pnpm exec playwright test
//   e2e/live/browser-view.spec.ts --project=live --workers=1`. Screenshots land in this test's output folder.
import { type Locator, type Page, expect, test } from "@playwright/test";

const API = `http://127.0.0.1:${process.env.TILO_LIVE_API_PORT ?? 5398}`;
const control = async (page: Page, body: Record<string, unknown>) =>
  expect((await page.request.post(`${API}/__control`, { data: body })).ok()).toBe(true);

const SIZES = [
  { name: "1440", width: 1440, height: 900 },
  { name: "1280", width: 1280, height: 800 },
  { name: "390", width: 390, height: 844 },
] as const;

// The target boxes the fake session records (support/fakeCardsApi.mjs), CSS px in a 1200x800 viewport.
const RESULT_LINK = { x: 180, y: 300, width: 260, height: 28 };
const SCROLL_POINT = { x: 600, y: 520, width: 24, height: 24 };

/** The cursor sits on the centre of the recorded box, scaled to where the picture is drawn. */
async function expectCursorAt(view: Locator, box: typeof RESULT_LINK) {
  const cursor = view.getByTestId("tilo-browser-cursor");
  await expect(cursor).toBeVisible();
  const [shot, dot] = [
    await view.locator(".tilo-bv__shot").boundingBox(),
    await cursor.boundingBox(),
  ];
  expect(shot && dot).toBeTruthy();
  if (shot && dot) {
    const [x, y] = [box.x + box.width / 2, box.y + box.height / 2];
    expect(
      Math.abs(dot.x + dot.width / 2 - (shot.x + (x / 1200) * shot.width)),
    ).toBeLessThanOrEqual(4);
    expect(
      Math.abs(dot.y + dot.height / 2 - (shot.y + (y / 800) * shot.height)),
    ).toBeLessThanOrEqual(4);
  }
}

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
      // Live, the newest picture is shown: the read (extract) has no mouse, so no cursor is drawn on it.
      await expect(view.locator(".tilo-bv__label")).toContainText(
        "Step 6 of 6 · Reading encyclopedia.example",
      );
      await expect(view.getByTestId("tilo-browser-cursor")).toHaveCount(0);

      // "Open in new tab" is a real link to the browser's own page, opened away from this page (a wider screen's: a phone
      // already shows the browser full width).
      const tab = view.getByRole("link", { name: "Open in new tab" });
      if (size.width < 600) await expect(tab).toBeHidden();
      else {
        await expect(tab).toHaveAttribute("href", "/world/w_here/browser");
        await expect(tab).toHaveAttribute("target", "_blank");
        await expect(tab).toHaveAttribute("rel", "noopener noreferrer");
      }

      // The World stays in view (owner, 21 Oct): on a desktop the browser is a solid card in the map's corner with the
      // map round it; Expand makes it take the map area over, which the rest of this test checks.
      const map = page.locator(".park-world-map");
      if (size.width > 760) {
        await expect(view).toHaveClass(/tilo-bv--card/);
        const [card, area] = [await view.boundingBox(), await map.boundingBox()];
        expect(card && area).toBeTruthy();
        if (card && area) {
          expect(card.x).toBeGreaterThanOrEqual(area.x + 8);
          expect(card.x + card.width).toBeLessThanOrEqual(area.x + area.width - 8);
          expect(card.width).toBeLessThanOrEqual(area.width - 120); // the map shows beside it
          expect(card.y + card.height).toBeLessThanOrEqual(area.y + area.height);
        }
        expect(await view.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toMatch(
          /rgba\(.*,\s*0(\.\d+)?\)$/,
        );
        await expect(view.locator(".tilo-bv__shot img")).toBeVisible();
        await page.screenshot({ path: info.outputPath(`browser-card-${time}-${size.name}.png`) });
        await view.getByRole("button", { name: "Expand" }).click();
        await expect(view).toHaveClass(/tilo-bv--takeover/);
        await expect(view.getByRole("button", { name: "Shrink" })).toBeVisible();
      } else {
        await expect(view.getByRole("button", { name: "Expand" })).toHaveCount(0);
      }
      // No bleed: expanded, the view covers the whole map area inside its 1px border, and is opaque.
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
      expect(shot?.width ?? 0).toBeGreaterThan(size.width < 761 ? 300 : 560);
      const body = view.locator(".tilo-bv__body");
      expect(await body.evaluate((el) => el.scrollHeight <= el.clientHeight + 1)).toBe(true);
      // The line says the state (the step is in the label). Every target on a phone is 44 px, Earlier and Later
      // included (a step has a before and an after picture, so the numbered strip alone cannot reach both: on a phone
      // they are arrows beside the line), and the window has no grip and no Dock there; wider, they sit inside the view.
      await expect(view.locator(".tilo-bv__line")).toHaveText("Tilo is using the browser now.");
      if (size.width < 600) {
        await expect(view.getByRole("button", { name: "Move the browser" })).toHaveCount(0);
        await expect(view.getByRole("button", { name: "Dock" })).toHaveCount(0);
        const targets = view.locator(".tilo-bv__button:visible, .tilo-bv__steps button:visible");
        // Stop, Back to map, Earlier, Later (arrows beside the line) and the six numbered steps
        expect(await targets.count()).toBeGreaterThanOrEqual(10);
        for (const target of await targets.all()) {
          const box = await target.boundingBox();
          expect(box && box.height >= 44 && box.width >= 44).toBe(true);
        }
      } else {
        for (const name of ["Earlier", "Later"]) {
          const box = await view.getByRole("button", { name, exact: true }).boundingBox();
          expect(box && viewBox && box.x + box.width <= viewBox.x + viewBox.width - 8).toBe(true);
        }
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
      await expect(view).toContainText("Finished: 6 steps");
      await expect(view.getByRole("button", { name: "Stop" })).toHaveCount(0);

      // The cursor is where Tilo acted, before and after: the clicked result's centre on both pictures of the click
      // step, the wheel point on the scroll, and none on the read.
      const label = view.locator(".tilo-bv__label");
      const clickStep = view.getByRole("button", { name: "Step 3: Clicking Example result" });
      await clickStep.click();
      await expect(label).toContainText("Step 3 of 6 · Clicking Example result · after");
      await expectCursorAt(view, RESULT_LINK);
      await view.getByRole("button", { name: "Earlier", exact: true }).click();
      await expect(label).toContainText("Step 3 of 6 · Clicking Example result · before");
      await expect(view.getByTestId("tilo-browser-cursor")).toHaveAttribute(
        "data-picture",
        "before",
      );
      await expectCursorAt(view, RESULT_LINK);
      await expect(clickStep).toHaveAttribute("aria-current", "step"); // the step stays lit on either picture
      await view.getByRole("button", { name: "Step 5: Scrolling down" }).click();
      await expect(label).toContainText("Step 5 of 6 · Scrolling down");
      await expectCursorAt(view, SCROLL_POINT);
      await view.getByRole("button", { name: "Step 6: Reading encyclopedia.example" }).click();
      await expect(label).toContainText("Step 6 of 6 · Reading encyclopedia.example");
      await expect(view.getByTestId("tilo-browser-cursor")).toHaveCount(0);
      await page.screenshot({ path: info.outputPath(`browser-cursor-${time}-${size.name}.png`) });

      await view.getByRole("button", { name: "Step 2: Typing in Search" }).click();
      await expect(label).toContainText("Step 2 of 6");
      // The strip centres the picked step, so its neighbour before it is whole, not cut at the edge.
      const [strip, first] = [
        await view.locator(".tilo-bv__steps").boundingBox(),
        await view.getByRole("button", { name: /^Step 1:/ }).boundingBox(),
      ];
      expect(strip && first && first.x >= strip.x - 1).toBe(true);
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

// The window (desktop only): drag the bar and it leaves the map as a floating card that stays inside the window; the
// arrow keys on the grip move it 16 px; the place is remembered; Dock puts it back over the map.
for (const size of SIZES.filter((s) => s.width > 760)) {
  test(`DEMO_BROWSER_e2e the window drags out of the map, stays inside the window and docks back, ${size.name}`, async ({
    page,
  }, info) => {
    await control(page, { reset: true, events: 20, browser: "live" });
    await page.setViewportSize({ width: size.width, height: size.height });
    await page.goto("/world/w_here");
    const view = page.getByTestId("tilo-browser-panel");
    await expect(view).toBeVisible({ timeout: 30_000 });
    await expect(view.locator(".tilo-bv__shot img")).toBeVisible({ timeout: 15_000 });
    const map = page.locator(".park-world-map");
    const mapBox = await map.boundingBox();

    // In the map's corner by default, with a grip and no Dock.
    await expect(view).toHaveCSS("position", "absolute");
    const grip = view.getByRole("button", { name: "Move the browser" });
    await expect(grip).toBeVisible();
    await expect(view.getByRole("button", { name: "Dock" })).toHaveCount(0);

    const inside = async () => {
      const box = await view.boundingBox();
      expect(box).toBeTruthy();
      if (!box) throw new Error("the browser window has no box");
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.y).toBeGreaterThanOrEqual(76); // below the page's fixed nav
      expect(box.x + box.width).toBeLessThanOrEqual(size.width + 1);
      expect(box.y + box.height).toBeLessThanOrEqual(size.height + 1);
      return box;
    };
    // Pointer down on the bar (the address pill is not a button), move, release.
    const drag = async (to: { x: number; y: number }) => {
      const bar = await view.locator(".tilo-bv__address").boundingBox();
      if (!bar) throw new Error("the browser bar has no box");
      await page.mouse.move(bar.x + bar.width / 2, bar.y + bar.height / 2);
      await page.mouse.down();
      await page.mouse.move(to.x, to.y, { steps: 10 });
      await page.mouse.up();
    };

    // A click on the bar that does not move leaves it docked.
    const bar = await view.locator(".tilo-bv__address").boundingBox();
    if (bar) await page.mouse.click(bar.x + 10, bar.y + bar.height / 2);
    await expect(view).toHaveCSS("position", "absolute");

    await drag({ x: size.width / 2 - 200, y: size.height / 2 + 120 });
    await expect(view).toHaveCSS("position", "fixed");
    const floated = await inside();
    expect(floated.width).toBeLessThanOrEqual(721);
    expect(floated.height).toBeGreaterThan(300);
    const background = await view.evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(background).not.toMatch(/rgba\(.*,\s*0(\.\d+)?\)$/);
    await expect(view.getByRole("button", { name: "Dock" })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`browser-floating-${size.name}.png`) });

    // Thrown past a corner, it stops inside the window.
    await drag({ x: size.width - 2, y: size.height - 2 });
    const corner = await inside();
    expect(corner.x + corner.width).toBeGreaterThan(size.width - 24);

    // Arrow keys on the grip: 16 px a press.
    await grip.focus();
    await page.keyboard.press("ArrowLeft");
    const left = await inside();
    expect(Math.abs(corner.x - left.x - 16)).toBeLessThanOrEqual(1);
    await page.keyboard.press("ArrowUp");
    const up = await inside();
    expect(Math.abs(left.y - up.y - 16)).toBeLessThanOrEqual(1);

    // Remembered for this viewer; the enlarged picture still opens above it, and Back to map and the chip still work.
    await page.reload();
    await expect(view).toBeVisible({ timeout: 30_000 });
    await expect(view).toHaveCSS("position", "fixed");
    const kept = await inside();
    expect(Math.abs(kept.x - up.x)).toBeLessThanOrEqual(1);
    await expect(view.locator(".tilo-bv__shot img")).toBeVisible({ timeout: 15_000 });
    await view.locator(".tilo-bv__shot").click();
    const zoom = page.locator("dialog.tilo-bv__zoom");
    await expect(zoom).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(zoom).toHaveCount(0);
    await view.getByRole("button", { name: "Back to map" }).click();
    await expect(view).toHaveCount(0);
    await page.getByRole("button", { name: /Show Tilo browser/ }).click();
    await expect(view).toHaveCSS("position", "fixed");

    // Dock puts it back in the map's corner, and forgets the place.
    await view.getByRole("button", { name: "Dock" }).click();
    await expect(view).toHaveCSS("position", "absolute");
    await expect(view).toHaveClass(/tilo-bv--card/);
    const docked = await view.boundingBox();
    expect(docked && mapBox).toBeTruthy();
    if (docked && mapBox) {
      expect(docked.x).toBeGreaterThanOrEqual(mapBox.x);
      expect(docked.x + docked.width).toBeLessThanOrEqual(mapBox.x + mapBox.width);
      expect(docked.width).toBeLessThan(mapBox.width - 100);
    }
    await expect(grip).toBeFocused();
    await page.reload();
    await expect(view).toBeVisible({ timeout: 30_000 });
    await expect(view).toHaveCSS("position", "absolute");
  });
}

test("DEMO_BROWSER_e2e Open in new tab is the browser as a full page of its own", async ({
  page,
}, info) => {
  await control(page, { reset: true, events: 20, browser: "finished" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/world/w_here");
  const link = page
    .getByTestId("tilo-browser-panel")
    .getByRole("link", { name: "Open in new tab" });
  await expect(link).toBeVisible({ timeout: 30_000 });
  const href = await link.getAttribute("href");
  expect(href).toBe("/world/w_here/browser");

  // The new tab loads this address; here it is opened in the same page.
  await page.goto(href ?? "/");
  const full = page.getByTestId("tilo-browser-panel");
  await expect(full).toBeVisible({ timeout: 30_000 });
  await expect(full).toHaveClass(/tilo-bv--page/);
  await expect(full.locator(".tilo-bv__badge")).toHaveText("Finished", { timeout: 15_000 });
  await expect(full.locator(".tilo-bv__shot img")).toBeVisible({ timeout: 15_000 });
  await expect(full).toContainText("Finished: 6 steps");
  // A page of its own: no map to go back to, no window to move or dock, no second new tab.
  for (const name of ["Back to map", "Dock", "Move the browser"])
    await expect(full.getByRole("button", { name })).toHaveCount(0);
  await expect(full.getByRole("link", { name: "Open in new tab" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Show Tilo browser/ })).toHaveCount(0);
  const box = await full.boundingBox();
  expect(box && box.width > 900 && box.height > 500).toBe(true);
  // The frame can still be walked step by step.
  await full.getByRole("button", { name: "Step 2: Typing in Search and pressing Enter" }).click();
  await expect(full.locator(".tilo-bv__label")).toContainText(
    "Step 2 of 6 · Typing in Search and pressing Enter · after",
  );
  await expect(full.getByTestId("tilo-browser-cursor")).toBeVisible();
  await page.screenshot({ path: info.outputPath("browser-page-1440.png") });
});

test("DEMO_BROWSER_e2e the browser page says it has not opened yet, then shows it by itself", async ({
  page,
}) => {
  await control(page, { reset: true, events: 20, browser: null });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/world/w_here/browser");
  await expect(page.getByText("Tilo's browser has not opened in this run yet")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("tilo-browser-panel")).toHaveCount(0);
  // The run's browser opens: the page follows the recorded events with no reload.
  await control(page, { browser: "live", events: 20 });
  const full = page.getByTestId("tilo-browser-panel");
  await expect(full).toBeVisible({ timeout: 15_000 });
  await expect(full.locator(".tilo-bv__badge")).toHaveText("Live");
  await expect(page.getByText("Tilo's browser has not opened in this run yet")).toHaveCount(0);
});

test("DEMO_BROWSER_e2e the browser page of a world that is not the person's is Page not found", async ({
  page,
}) => {
  await control(page, { reset: true, events: 20, browser: "live" });
  await page.goto("/world/w_nobody/browser");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("tilo-browser-panel")).toHaveCount(0);
});
