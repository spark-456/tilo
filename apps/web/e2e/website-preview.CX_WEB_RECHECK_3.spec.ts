import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";

const pixel = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=";
const pixelImage = `<img alt="pixel" src="${pixel}">`;
const pages = [
  {
    name: "benign page",
    html: "<!doctype html><h1>Benign page</h1>",
    selector: "h1",
    text: "Benign page",
  },
  {
    name: "data image page",
    html: `<!doctype html><h1>Data image page</h1><img alt="pixel" src="${pixel}">`,
    selector: "img",
    text: null,
  },
  {
    name: "300 image page",
    html: `<!doctype html><h1>Three hundred images</h1>${pixelImage.repeat(300)}`,
    selector: "img",
    text: null,
  },
  {
    name: "live clock page",
    html: '<!doctype html><h1>Live clock</h1><output id="clock"></output><script>function tick(){document.querySelector("#clock").textContent=new Date().toISOString().slice(11,19)}tick();setInterval(tick,1000)</script>',
    selector: "#clock",
    text: /^\d{2}:\d{2}:\d{2}$/,
  },
];

function previewShell(origin: string): string {
  const source = readFileSync(
    resolve(process.cwd(), "../../services/api/src/tilo_api/preview.py"),
    "utf8",
  );
  const script = source.match(/_SCRIPT = """([\s\S]*?)"""/)?.[1];
  if (!script) throw new Error("preview shell script source is missing");
  const ready = script
    .replace("__ORIGINS__", JSON.stringify([origin]))
    .replace("__MAX__", "524288");
  return `<!doctype html><html><head><meta charset="utf-8"></head><body><script>${ready}</script></body></html>`;
}

test("CX_WEB_RECHECK_3 renders real website previews in Chromium", async ({ page }) => {
  const origin = new URL(String(test.info().project.use.baseURL)).origin;
  let current = "";
  await page.route("**/src/api/ClientProvider.tsx**", (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: 'export const API_URL = "https://api.example.test"; export const authToken = async () => "test-token";',
    }),
  );
  await page.route("https://api.example.test/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/preview/website") {
      return route.fulfill({
        contentType: "text/html",
        headers: {
          "content-security-policy": `sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; img-src data:; frame-ancestors ${origin}`,
        },
        body: previewShell(origin),
      });
    }
    if (url.pathname.endsWith("/result")) {
      const cors = {
        "access-control-allow-origin": origin,
        "access-control-allow-methods": "GET, OPTIONS",
        "access-control-allow-headers": "Authorization",
      };
      if (route.request().method() === "OPTIONS")
        return route.fulfill({ status: 204, headers: cors });
      return route.fulfill({
        status: 200,
        headers: { ...cors, "content-type": "text/html" },
        body: current,
      });
    }
    return route.fulfill({ status: 404, body: "" });
  });

  for (const item of pages) {
    current = item.html;
    const hash = createHash("sha256").update(item.html).digest("hex");
    await page.goto(`/e2e/fixtures/website-preview.html?hash=${hash}`, {
      waitUntil: "domcontentloaded",
    });
    const frame = page.frameLocator("iframe[title]");
    await expect(frame.locator("body")).toBeVisible();
    if (item.text instanceof RegExp)
      await expect(frame.locator(item.selector)).toHaveText(item.text);
    else if (item.text) await expect(frame.locator(item.selector)).toHaveText(item.text);
    else await expect(frame.locator("h1")).toBeVisible();
    if (item.name === "data image page")
      await expect(frame.locator("img")).toHaveJSProperty("naturalWidth", 1);
    if (item.name === "300 image page") {
      await expect(frame.locator("img")).toHaveCount(300);
      await expect
        .poll(() =>
          frame
            .locator("img")
            .evaluateAll((images) =>
              images.every((img) => (img as HTMLImageElement).naturalWidth === 1),
            ),
        )
        .toBe(true);
    }
  }
});
