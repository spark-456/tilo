// WEB-PARITY: open the design reference and our root-path page, freeze both the same way, set the
// theme the same way, and take full-page screenshots. Dev/test tool only.
import type { Page } from "@playwright/test";
import type { Rect } from "./diff";
import type { PageSpec, Theme } from "./pages";
import type { RegionSpec } from "./regions";
import { STYLE_PROPS, type StyleNode } from "./styles";

/** The identical freeze for both sides (the browsers also run with prefers-reduced-motion: reduce). */
const FREEZE_CSS =
  "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important;-webkit-font-smoothing:antialiased!important}";

async function freezeAndSettle(page: Page): Promise<void> {
  await page.addStyleTag({ content: FREEZE_CSS });
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
  await page.waitForTimeout(300);
}

/** Opens `Tilo App.dc.html#<hash>` and waits for the boot splash to leave (the design's own ready signal). */
export async function openDesign(page: Page, origin: string, spec: PageSpec): Promise<void> {
  await page.goto(`${origin}/${encodeURIComponent("Tilo App.dc.html")}#${spec.designHash}`);
  await page.waitForSelector('[aria-label="Loading Tilo"]', { state: "detached", timeout: 30_000 });
  await page.waitForSelector('nav[aria-label="Main"]', { timeout: 10_000 });
  await freezeAndSettle(page);
}

/** Opens our route. Returns false ("route missing") on a 4xx/5xx, the not-found screen, or no Park root. */
export async function openOurs(page: Page, origin: string, spec: PageSpec): Promise<boolean> {
  const res = await page.goto(`${origin}${spec.path}`);
  if (!res || res.status() >= 400) return false;
  const root = page.locator('[data-park], [data-testid="not-found"]').first();
  await root.waitFor({ timeout: 8_000 }).catch(() => undefined);
  if ((await page.locator('[data-testid="not-found"]').count()) > 0) return false;
  if ((await page.locator("[data-park]").count()) === 0) return false;
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
  await freezeAndSettle(page);
  return true;
}

/** Sets day or night the way each side does it: the design's own toggle; ours via data-time on [data-park]. */
export async function setTheme(page: Page, side: "design" | "ours", theme: Theme): Promise<void> {
  if (side === "design") {
    const want = theme === "night" ? "Switch to night" : "Switch to day";
    const btn = page.locator(`button[aria-label="${want}"]`);
    if ((await btn.count()) > 0) await btn.click();
    const now = theme === "night" ? "Switch to day" : "Switch to night";
    await page.waitForSelector(`button[aria-label="${now}"]`, { timeout: 5_000 });
  } else {
    await page.evaluate((t) => {
      document.documentElement.dataset.time = t;
      for (const el of document.querySelectorAll("[data-park]")) el.setAttribute("data-time", t);
    }, theme);
  }
  await freezeAndSettle(page);
}

export interface Shot {
  png: Buffer;
  /** Selector-region boxes in page pixels (null: selector not found). */
  rects: Record<string, Rect | null>;
  /** Computed styles of each selector region's root, its children and grandchildren (null: not found). */
  styles: Record<string, StyleNode[] | null>;
}

/** Full-page screenshot plus the page-pixel box of each selector region. */
export async function shoot(
  page: Page,
  side: "design" | "ours",
  regions: RegionSpec[],
): Promise<Shot> {
  const png = await page.screenshot({ fullPage: true, animations: "disabled", caret: "hide" });
  const rects: Record<string, Rect | null> = {};
  const styles: Record<string, StyleNode[] | null> = {};
  for (const r of regions) {
    if (!("design" in r)) continue;
    styles[r.name] = await page.evaluate(
      ([sel, props]) => {
        const root = document.querySelector(sel as string);
        if (!root) return null;
        const els = [root];
        for (const c of root.children) els.push(c, ...c.children);
        return els.slice(0, 60).map((el) => {
          const cs = getComputedStyle(el) as unknown as Record<string, string>;
          const text = (el.firstChild?.textContent ?? "").trim().slice(0, 24);
          return {
            label: `${el.tagName.toLowerCase()}${text ? ` "${text}"` : ""}`,
            tag: el.tagName,
            styles: Object.fromEntries((props as string[]).map((p) => [p, cs[p] ?? ""])),
          };
        });
      },
      [side === "design" ? r.design : r.ours, [...STYLE_PROPS]],
    );
    rects[r.name] = await page.evaluate(
      (sel) => {
        const b = document.querySelector(sel)?.getBoundingClientRect();
        return b ? { x: b.x + scrollX, y: b.y + scrollY, w: b.width, h: b.height } : null;
      },
      side === "design" ? r.design : r.ours,
    );
  }
  return { png, rects, styles };
}
