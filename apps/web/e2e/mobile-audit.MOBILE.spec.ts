// MOBILE audit (local only, `TILO_MOBILE_OUT=<dir>`): every main page at 360, 390 and 430 px, portrait, day and night,
// in fixture mode. Writes a full-page screenshot per page and `metrics.json` (horizontal scroll, elements past the
// right edge, controls under 44px, text under 14px, fixed layers at the bottom without a safe-area inset). It asserts
// nothing; `mobile-pwa.MOBILE.spec.ts` holds the pinned rules.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { type Page, test } from "@playwright/test";
import { MOBILE_PAGES } from "./support/mobilePages";

const OUT = process.env.TILO_MOBILE_OUT ?? "";
const WIDTHS = (process.env.TILO_MOBILE_WIDTHS ?? "360,390,430").split(",").map(Number);
const THEMES = (process.env.TILO_MOBILE_THEMES ?? "day,night").split(",");

async function measure(page: Page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const vh = window.innerHeight;
    const name = (el: Element) => {
      const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/)[0] : "";
      const label = el.getAttribute("aria-label") ?? (el.textContent ?? "").trim().slice(0, 30);
      return `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""} "${label}"`;
    };
    const shown = (el: Element) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
    };
    const clipped = (el: Element) => {
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const s = getComputedStyle(p);
        if (
          s.overflowX !== "visible" &&
          s.overflowX !== "clip" &&
          p.scrollWidth > p.clientWidth + 1
        )
          return true;
        if (s.overflowX === "hidden" || s.overflowX === "clip") return true;
      }
      return false;
    };
    const all = [...document.querySelectorAll("body *")];
    const past = all
      .filter((el) => shown(el) && !clipped(el))
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return r.right > vw + 1 || r.left < -1;
      })
      .slice(0, 12)
      .map(
        (el) =>
          `${name(el)} ${Math.round(el.getBoundingClientRect().left)}..${Math.round(el.getBoundingClientRect().right)}`,
      );
    const controls = [
      ...document.querySelectorAll(
        'a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="tab"], [role="menuitem"], [role="switch"], [role="checkbox"], [role="radio"], summary',
      ),
    ].filter(shown);
    const small = controls
      .filter((el) => {
        if (el.closest("[aria-hidden='true'], [inert]")) return false;
        const r = el.getBoundingClientRect();
        if (r.width >= 44 && r.height >= 44) return false;
        // a link inside a sentence is exempt (WCAG 2.5.8 inline)
        if (el.tagName === "A" && getComputedStyle(el).display === "inline") return false;
        // a native radio/checkbox whose label is the target
        if (el instanceof HTMLInputElement && ["radio", "checkbox"].includes(el.type)) {
          const label =
            el.closest("label") ?? (el.id ? document.querySelector(`label[for="${el.id}"]`) : null);
          if (label) {
            const lr = label.getBoundingClientRect();
            if (lr.height >= 44) return false;
          }
        }
        return true;
      })
      .map((el) => {
        const r = el.getBoundingClientRect();
        return `${name(el)} ${Math.round(r.width)}x${Math.round(r.height)}`;
      });
    const tiny = new Map<string, number>();
    for (const el of all) {
      if (!shown(el) || el.closest("[aria-hidden='true']")) continue;
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && (n.textContent ?? "").trim());
      if (!own) continue;
      const px = Number.parseFloat(getComputedStyle(el).fontSize);
      if (px < 14) {
        const key = `${name(el).split(" ")[0]} ${px}px`;
        tiny.set(key, (tiny.get(key) ?? 0) + 1);
      }
    }
    const bottomFixed = all
      .filter((el) => {
        const s = getComputedStyle(el);
        if (s.position !== "fixed" || !shown(el)) return false;
        const r = el.getBoundingClientRect();
        return r.bottom > vh - 40 && r.height < vh - 10;
      })
      .map((el) => `${name(el)} bottom=${getComputedStyle(el).bottom}`);
    return {
      vw,
      scrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      hscroll: document.documentElement.scrollWidth > vw + 1,
      past,
      small,
      tiny: [...tiny.entries()].map(([k, n]) => `${k} x${n}`),
      bottomFixed,
    };
  });
}

test.describe("MOBILE audit", () => {
  test.skip(!OUT, "local audit: set TILO_MOBILE_OUT");
  for (const theme of THEMES) {
    for (const width of WIDTHS) {
      test(`MOBILE audit ${width} ${theme}`, async ({ page }) => {
        test.setTimeout(240_000);
        mkdirSync(OUT, { recursive: true });
        await page.setViewportSize({ width, height: 844 });
        await page.addInitScript((t) => {
          sessionStorage.setItem("tilo-boot-seen", "1");
          localStorage.setItem("tilo.time", t);
        }, theme);
        const errors: string[] = [];
        page.on("console", (m) => {
          if (m.type() === "error") errors.push(m.text());
        });
        const result: Record<string, unknown> = {};
        for (const [id, path] of MOBILE_PAGES) {
          errors.length = 0;
          await page.goto(path);
          await page
            .locator(`[data-testid="park-page-${id}"], [data-park] main`)
            .first()
            .waitFor({ timeout: 30_000 })
            .catch(() => {});
          await page.waitForTimeout(id === "world" ? 2500 : 900);
          await page.evaluate(() => document.fonts.ready.then(() => undefined));
          result[id] = { ...(await measure(page)), errors: [...errors] };
          await page.screenshot({
            path: join(OUT, `${width}-${theme}-${id}.png`),
            fullPage: true,
            animations: "disabled",
          });
        }
        writeFileSync(join(OUT, `metrics-${width}-${theme}.json`), JSON.stringify(result, null, 2));
      });
    }
  }
});
