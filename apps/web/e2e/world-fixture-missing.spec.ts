import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { stageCanvas, stageFrame } from "./support/world";

// P0-08b review finding (b): an unknown or empty ?fixture= name must not log to the console
// (Vite's SPA fallback answers a missing fixture file with index.html and status 200). Instead an
// in-app role="alert" explains the fixture could not be loaded, naming it when a name was given,
// and the stage frame still renders.

test.use({ viewport: DESKTOP });

const CASES = [
  { label: "an unknown", query: "?fixture=no-such-fixture", name: "no-such-fixture" },
  { label: "an empty", query: "?fixture=", name: null },
  // "%" must be URL-encoded into the fetch path, or Vite answers 500 and the browser logs it.
  { label: "a percent-sign", query: "?fixture=%25", name: "%" },
  { label: "a malformed-escape", query: "?fixture=%25zz", name: "%zz" },
] as const;

for (const { label, query, name } of CASES) {
  test(`FR_WLD_04 P0-08b fixture mode: ${label} ?fixture= shows an in-app alert and logs nothing`, async ({
    page,
  }) => {
    const messages: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error" || msg.type() === "warning") {
        messages.push(`[${msg.type()}] ${msg.text()}`);
      }
    });
    page.on("pageerror", (err) => messages.push(`[pageerror] ${err.message}`));

    await page.goto(`/${query}`);
    await expect(stageFrame(page)).toBeVisible();
    await expect(stageCanvas(page)).toBeVisible();

    const alert = page.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/could not be loaded/i);
    if (name !== null) await expect(alert).toContainText(name);

    await page.waitForTimeout(500);
    expect(messages, messages.join("\n")).toEqual([]);
  });
}

test("FR_WLD_04 P0-08b fixture mode: a valid fixture shows no alert", async ({ page }) => {
  await page.goto("/?fixture=village-basic&seq=20");
  await expect(stageCanvas(page)).toBeVisible();
  await expect.poll(async () => stageFrame(page).getAttribute("data-seq")).toBe("20");
  await expect(page.getByRole("alert")).toHaveCount(0);
});

// P0-08b qa finding: trace rows must keep a fixed height while events stream in (no layout shift).
test("FR_WLD_04 P0-08b fixture mode: streaming crowd-20 into the trace list causes no layout shift", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const w = window as unknown as { cls: number };
    w.cls = 0;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) w.cls += (e as unknown as { value: number }).value;
    }).observe({ type: "layout-shift", buffered: true });
  });
  await page.goto("/?fixture=crowd-20");
  await expect(stageCanvas(page)).toBeVisible();
  await page.waitForTimeout(4000);
  expect(await page.evaluate(() => (window as unknown as { cls: number }).cls)).toBe(0);
});
