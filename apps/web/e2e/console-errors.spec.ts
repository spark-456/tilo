import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`${name} console`, () => {
    test.use({ viewport });

    test(`zero console errors or warnings on load at ${name} size`, async ({ page }) => {
      const messages: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error" || msg.type() === "warning") {
          messages.push(`[${msg.type()}] ${msg.text()}`);
        }
      });
      page.on("pageerror", (err) => messages.push(`[pageerror] ${err.message}`));

      await page.goto("/");
      await page.waitForTimeout(500);

      expect(messages, messages.join("\n")).toEqual([]);
    });
  });
}

// PRD-9.7/18.2: wheel-zoom, drag-pan and keyboard-pan over the stage must not
// log console errors or warnings — in particular React's passive `onWheel`
// producing Chromium/Edge's "Unable to preventDefault inside passive event
// listener invocation" once per wheel tick (30 ticks, 30 errors) went
// unnoticed because the load-only check above never interacts with the page.
test.describe("desktop console: stage interaction", () => {
  test.use({ viewport: DESKTOP });

  test("PRD-9.7 console: wheel zoom, pointer drag and keyboard pan over the stage log nothing", async ({
    page,
  }) => {
    const messages: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" || msg.type() === "warning") {
        messages.push(`[${msg.type()}] ${msg.text()}`);
      }
    });
    page.on("pageerror", (err) => messages.push(`[pageerror] ${err.message}`));

    await page.goto("/");
    const stage = page.getByTestId("stage-frame");
    await expect(stage.locator("canvas")).toBeVisible();

    await page.mouse.move(700, 450);
    for (let i = 0; i < 30; i++) {
      await page.mouse.wheel(0, -100);
    }

    await page.mouse.move(600, 400);
    await page.mouse.down();
    await page.mouse.move(500, 350, { steps: 5 });
    await page.mouse.up();

    await stage.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("+");
    await page.keyboard.press("-");

    await page.waitForTimeout(400); // let the camera transition settle

    expect(messages, messages.join("\n")).toEqual([]);
  });
});
