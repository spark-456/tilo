import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const evidence = resolve(
  process.env.TILO_EVIDENCE_DIR ?? resolve(process.cwd(), "../../agy-bridge/evidence"),
  "UX-POLISH-CHAT",
);

for (const width of [1440, 390] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`UX-POLISH-CHAT ${width} ${theme} shows labelled bubbles without overlap`, async ({
      page,
    }) => {
      mkdirSync(evidence, { recursive: true });
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
      await page.goto("/chat");
      await expect(page.getByRole("heading", { name: "Chat with your Tilo" })).toBeVisible({
        timeout: 20_000,
      });
      if (theme === "dark")
        await page
          .locator("[data-park]")
          .evaluate((node) => node.setAttribute("data-time", "night"));
      await page.getByLabel("Ask a question").fill("What should I focus on today?");
      await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.locator(".park-chat-you")).toContainText("What should I focus on today?");
      await expect(page.getByText("Personal helper", { exact: false }).last()).toBeVisible();
      await expect(page.getByRole("button", { name: "Send", exact: true })).toContainText("Send");
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: resolve(evidence, `${width}-${theme}-Chat.png`),
        fullPage: true,
        animations: "disabled",
      });
    });
  }
}
