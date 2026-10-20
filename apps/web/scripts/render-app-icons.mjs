// MOBILE (PWA): render the home-screen icons from the Studio logomark (shell `park-shell__logomark`: a 36px
// priFill square, radius 12, a 22x12 white visor, radius 5, with two 3px eyes 5px apart). Run once after the mark
// changes: `node scripts/render-app-icons.mjs` (the repository's Playwright install; Edge locally, Chromium on CI).
// "any" icons keep the rounded square on a clear ground; "maskable" and the Apple icon fill the whole square, because
// the platform cuts its own shape (the visor sits well inside the maskable safe circle of 40% radius).
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const INK = "#0B0B0C"; // studio day priFill and the eyes
const VISOR = "#FFFFFF";
const out = join(fileURLToPath(new URL("..", import.meta.url)), "public", "icons");

/** The logomark in its own 36-unit box, drawn at `size` px; `bleed` fills the square instead of rounding it. */
function mark(size, bleed) {
  const ground = bleed
    ? `<rect width="36" height="36" fill="${INK}"/>`
    : `<rect width="36" height="36" rx="12" fill="${INK}"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 36 36">${ground}<rect x="7" y="12" width="22" height="12" rx="5" fill="${VISOR}"/><circle cx="14" cy="18" r="1.5" fill="${INK}"/><circle cx="22" cy="18" r="1.5" fill="${INK}"/></svg>`;
}

const ICONS = [
  ["tilo-192.png", 192, false],
  ["tilo-512.png", 512, false],
  ["tilo-maskable-192.png", 192, true],
  ["tilo-maskable-512.png", 512, true],
  ["apple-touch-icon-180.png", 180, true],
];

await mkdir(out, { recursive: true });
const browser = await chromium.launch(process.env.CI ? {} : { channel: "msedge" });
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const [name, size, bleed] of ICONS) {
    await page.setViewportSize({ width: size, height: size });
    await page.setContent(
      `<!doctype html><html><body style="margin:0;background:transparent">${mark(size, bleed)}</body></html>`,
    );
    await page
      .locator("svg")
      .screenshot({ path: join(out, name), omitBackground: !bleed, animations: "disabled" });
  }
} finally {
  await browser.close();
}
