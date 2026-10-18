import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(process.cwd(), "../../agy-bridge/evidence/P0-CHAT-LAYOUT");

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`P0-CHAT-LAYOUT ${width} ${theme} keeps the thread and composer in their pane`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/chat");
      await expect(page.getByRole("heading", { name: "Chat with your Tilo" })).toBeVisible();
      if (theme === "dark")
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));

      const rail = page.locator(".park-chat-rail");
      const main = page.locator(".park-chat-main");
      const thread = page.locator(".park-chat-thread");
      const log = page.locator(".park-chat-log");
      const composer = page.locator(".park-chat-compose");
      if (width === 390) {
        await expect(rail).toBeHidden();
        await page.getByRole("button", { name: "Open chat history" }).click();
        await expect(rail).toBeVisible();
        await rail.getByRole("button", { name: "Close chat history" }).click();
        await expect(rail).toBeHidden();
      }

      await page.getByLabel("Ask a question").fill("X".repeat(400));
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.locator(".park-chat-you")).toBeVisible();
      const bounds = await Promise.all(
        [rail, main, thread, log, composer, page.locator(".park-chat-you")].map((item) =>
          item.boundingBox(),
        ),
      );
      const [historyBox, mainBox, threadBox, logBox, composeBox, bubbleBox] = bounds;
      expect(mainBox && threadBox && logBox && composeBox && bubbleBox).toBeTruthy();
      if (!mainBox || !threadBox || !logBox || !composeBox || !bubbleBox) return;
      if (width === 1440 && historyBox)
        expect(historyBox.x + historyBox.width).toBeLessThanOrEqual(mainBox.x + 1);
      expect(composeBox.x).toBeGreaterThanOrEqual(threadBox.x - 1);
      expect(composeBox.x + composeBox.width).toBeLessThanOrEqual(
        threadBox.x + threadBox.width + 1,
      );
      expect(logBox.y + logBox.height).toBeLessThanOrEqual(composeBox.y + 1);
      expect(composeBox.y + composeBox.height).toBeLessThanOrEqual(
        threadBox.y + threadBox.height + 1,
      );
      expect(bubbleBox.x + bubbleBox.width).toBeLessThanOrEqual(logBox.x + logBox.width + 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}-chat.png`),
        animations: "disabled",
      });
    });
  }
}
