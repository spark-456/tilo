import { expect, test } from "@playwright/test";
import { isHostNoiseUrl } from "./support/console";

// CX-UX-CONSOLE-SWEEP: public routes, every Park page, each World lens, and each Needs-you sheet.
// Dynamic routes use the bundled fixture world and a representative inspect target.
const ROUTES = [
  "/",
  "/worlds",
  "/world/k1",
  "/skills",
  "/ledger",
  "/agenda",
  "/team",
  "/profile",
  "/connectors",
  "/settings",
  "/library",
  "/more",
  "/chat",
  "/needs",
  "/world/w_village_basic/stage",
  "/world/w_village_basic/story",
  "/world/w_village_basic/trace",
  "/world/w_village_basic/delivery",
  "/world/w_village_basic/inspect/B1",
  "/needs-you",
  "/needs-you/gate",
  "/needs-you/consent",
  "/privacy",
  "/terms",
  "/not-a-page",
] as const;

for (const [name, viewport] of [
  ["desktop", { width: 1440, height: 900 }],
  ["mobile", { width: 390, height: 844 }],
] as const) {
  test(`CX-UX-CONSOLE-SWEEP ${name} routes have no console, request, or horizontal overflow errors`, async ({
    browser,
    baseURL,
  }) => {
    test.setTimeout(180_000);
    const page = await browser.newPage({ viewport, ...(baseURL ? { baseURL } : {}) });
    const findings: string[] = [];
    let route = "";
    page.on("console", (message) => {
      if (
        (message.type() === "error" || message.type() === "warning") &&
        !isHostNoiseUrl(message.location().url)
      ) {
        findings.push(`${route} console ${message.type()}: ${message.text()}`);
      }
    });
    page.on("pageerror", (error) => findings.push(`${route} pageerror: ${error.message}`));
    page.on("response", (response) => {
      if (response.status() >= 400 && !isHostNoiseUrl(response.url())) {
        findings.push(`${route} HTTP ${response.status()}: ${response.url()}`);
      }
    });
    page.on("requestfailed", (request) => {
      if (!isHostNoiseUrl(request.url())) {
        findings.push(`${route} request failed: ${request.url()} ${request.failure()?.errorText}`);
      }
    });

    for (const path of ROUTES) {
      route = path;
      await page.goto(path, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(350);
      const overflow = await page.evaluate(() => {
        const width = document.documentElement.clientWidth;
        const excess = document.documentElement.scrollWidth - width;
        if (excess <= 1) return null;
        const offenders = [...document.querySelectorAll("body *")]
          .filter((el) => el.getBoundingClientRect().right > width + 1)
          .slice(0, 4)
          .map(
            (el) =>
              `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ""}.${String(el.className).split(" ")[0]}`,
          );
        return `${excess}px (${offenders.join(", ")})`;
      });
      if (overflow) findings.push(`${path} horizontal overflow: ${overflow}`);
    }
    await page.close();
    expect(findings, findings.join("\n")).toEqual([]);
  });
}
