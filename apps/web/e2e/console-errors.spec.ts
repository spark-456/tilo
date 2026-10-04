import { expect, test } from "@playwright/test";
import { gotoStage } from "./support/camera";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = { desktop: DESKTOP, mobile: MOBILE } as const;

for (const [name, viewport] of Object.entries(SIZES)) {
  test.describe(`${name} console`, () => {
    test.use({ viewport });

    test(`zero console errors or warnings on load at ${name} size`, async ({ page }) => {
      const messages = collectConsoleProblems(page);

      await gotoStage(page);
      await page.waitForTimeout(500);

      expect(messages, messages.join("\n")).toEqual([]);
    });
  });
}
