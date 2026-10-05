// NFR-01 (PRD 17.1): "Landing page to interactive: <= 2.0 s desktop broadband; <= 3.5 s mid-range phone
// on 4G". Written from the PRD text. Local run (`TILO_NFR01=1 TILO_WEB_PORT=<port> pnpm exec playwright test --project=nfr01 --no-deps`; CI never sets it): the
// production build served by `vite preview`, cold cache. It is a proxy for the deployed number, which is
// measured on tilo-dev after the deploy (docs/open-questions.md): no CDN, no TLS and no real radio here.
//
// "Interactive" = the person can type: the task box is there and a first character typed into it comes
// back through the app (the counter changes), measured from the start of navigation.
//   desktop broadband: no throttling.
//   mid-range phone on 4G: a 390x844 viewport, CPU slowed 4x, the WebPageTest "4G" profile
//   (9 Mbps down, 1.5 Mbps up, 170 ms round trip).
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "../support/viewports";

const BUDGET_S = { desktop: 2.0, phone: 3.5 } as const;

async function msToInteractive(page: Page): Promise<number> {
  const start = performance.now();
  await page.goto("/", { waitUntil: "commit" });
  const box = page.getByLabel("Describe your task");
  await box.fill("x");
  await expect(page.locator(".task-count")).toHaveText(/^1 \/ 4,000$/); // the input went through React
  return performance.now() - start;
}

test("NFR-01 landing page to interactive is within 2.0 s on desktop broadband", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  const ms = await msToInteractive(page);
  expect(ms / 1000, `took ${ms.toFixed(0)} ms`).toBeLessThanOrEqual(BUDGET_S.desktop);
});

test("NFR-01 landing page to interactive is within 3.5 s on a mid-range phone on 4G", async ({
  page,
}) => {
  await page.setViewportSize(MOBILE);
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 170,
    downloadThroughput: (9 * 1024 * 1024) / 8,
    uploadThroughput: (1.5 * 1024 * 1024) / 8,
  });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  const ms = await msToInteractive(page);
  expect(ms / 1000, `took ${ms.toFixed(0)} ms`).toBeLessThanOrEqual(BUDGET_S.phone);
});
