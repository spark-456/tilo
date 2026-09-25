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
