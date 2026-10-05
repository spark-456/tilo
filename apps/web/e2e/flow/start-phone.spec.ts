// #289 (Bundle D follow-ups): the phone fit of S-01 and S-03 at 390x844, and the drop zone's
// controls. Measured in the page, never by a timer: each test waits on what it measures.
import { expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "../support/viewports";

test("#289 S-01 at 390: the drop zone is whole on first load and nothing needs a scroll cue", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/");
  const drop = page.locator(".file-drop");
  await expect(drop).toBeVisible();
  const fit = await page.evaluate(() => {
    const body = document.querySelector(".flow-body") as HTMLElement;
    const drop = document.querySelector(".file-drop") as HTMLElement;
    return {
      overflow: body.scrollHeight - body.clientHeight,
      dropBottom: drop.getBoundingClientRect().bottom,
      bodyBottom: body.getBoundingClientRect().bottom,
    };
  });
  expect(fit.dropBottom).toBeLessThanOrEqual(fit.bodyBottom);
  expect(fit.overflow, "the panel body scrolls").toBeLessThanOrEqual(0);
});

test("#289 S-03 at 390: the panel ends above the bottom tabs, and the cap field is a 44 px target", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE);
  await page.goto("/task/t/approaches");
  const cap = page.getByTestId("budget-cap-input");
  await expect(cap).toBeVisible();
  const box = await cap.boundingBox();
  expect(box?.height ?? 0, "budget cap input height").toBeGreaterThanOrEqual(44);
  const gap = await page.evaluate(() => {
    const shell = document.querySelector(".flow-shell") as HTMLElement;
    const tabs = document.querySelector(".bottom-tabs") as HTMLElement;
    return tabs.getBoundingClientRect().top - shell.getBoundingClientRect().bottom;
  });
  expect(gap, "space between the panel's bottom and the tabs' top").toBeGreaterThanOrEqual(0);
  // The one action is reachable without leaving the panel: it sits inside it, above the tabs.
  const primary = await page.locator(".flow-shell .primary").boundingBox();
  const tabsTop = (await page.locator(".bottom-tabs").boundingBox())?.y ?? 0;
  expect((primary?.y ?? 0) + (primary?.height ?? 0)).toBeLessThanOrEqual(tabsTop);
});

for (const viewport of [DESKTOP, MOBILE]) {
  test(`#289 S-01 "Choose files" stays on one line, and the drop zone's border is 3:1 at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    const choose = page.locator(".file-drop .secondary");
    await expect(choose).toHaveText("Choose files");
    const lines = await choose.evaluate((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      return new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size;
    });
    expect(lines, "lines of text in the button").toBe(1);
    // Non-text contrast (WCAG 1.4.11): the border against the page behind the drop zone.
    const ratio = await page.evaluate(() => {
      const lum = (rgb: string) => {
        const [r, g, b] = (rgb.match(/\d+(\.\d+)?/g) ?? []).slice(0, 3).map((v) => {
          const c = Number(v) / 255;
          return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
        }) as [number, number, number];
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const zone = document.querySelector(".file-drop") as HTMLElement;
      const button = document.querySelector(".file-drop .secondary") as HTMLElement;
      const bg = getComputedStyle(zone).backgroundColor;
      const contrast = (fg: string, back: string) => {
        const [a, b] = [lum(fg), lum(back)];
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      };
      return {
        zone: contrast(getComputedStyle(zone).borderTopColor, bg),
        button: contrast(getComputedStyle(button).borderTopColor, bg),
      };
    });
    expect(ratio.zone, "drop zone border contrast").toBeGreaterThanOrEqual(3);
    expect(ratio.button, "Choose files border contrast").toBeGreaterThanOrEqual(3);
  });
}
