// #345 (from the #342 design review): S-16 polish. The empty message card is not a tall blank box,
// the Email card does not repeat the preferences card, and a list box that holds everything it was
// given is not a keyboard stop (a box that scrolls still is: WCAG 2.1.1).
import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "../support/viewports";

const ROUTES = [
  "/channels",
  "/library",
  "/autonomy",
  "/team/console",
  "/worlds/replays",
  "/settings",
];

for (const viewport of [DESKTOP, MOBILE]) {
  const at = `${viewport.width}x${viewport.height}`;

  test(`#345 S-16 at ${at}: the empty messages card is short and Email does not repeat Notification preferences`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/channels");
    const messages = page.getByLabel("Recent channel messages list");
    await expect(messages).toContainText("No email or in-app message has been recorded yet.");
    const box = await messages.boundingBox();
    expect(box?.height ?? 999).toBeLessThanOrEqual(120);
    await expect(page.getByText("Notification preferences will be set here")).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Notification preferences" })).toBeVisible();
  });

  test(`#345 S-16 at ${at}: the one-row Connected Google accounts box fits, so it is not a tab stop`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/channels");
    const accounts = page.getByLabel("Connected Google accounts list");
    await expect(accounts).toContainText("Gmail", { timeout: 15_000 });
    const fit = await accounts.evaluate((el) => ({
      scrolls: el.scrollHeight > el.clientHeight + 1,
      tabindex: el.getAttribute("tabindex"),
    }));
    expect(fit).toEqual({ scrolls: false, tabindex: null });
  });

  test(`#345 a reserved list box is a tab stop only while it scrolls, at ${at}`, async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await page.setViewportSize(viewport);
    for (const route of ROUTES) {
      await page.goto(`${route}?speed=1000`);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(600); // rows settle
      const boxes = await page.evaluate(() =>
        [...document.querySelectorAll<HTMLElement>(".section-box.reserved")].map((el) => ({
          label: el.getAttribute("aria-label"),
          scrolls: el.scrollHeight > el.clientHeight + 1,
          tabbable: el.getAttribute("tabindex") === "0",
        })),
      );
      for (const b of boxes) {
        expect(b.tabbable, `${route}: ${b.label} (scrolls: ${b.scrolls})`).toBe(b.scrolls);
      }
    }
  });
}
