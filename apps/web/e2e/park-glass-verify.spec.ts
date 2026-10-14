// GLASS-VERIFY (owner: "glass surfaces let text show through"; GLASS-1 227ce0a6 made the tokens opaque):
// every Park page, day and night, 1440x900 and 390x844. A text run is a defect when no card-level ancestor under it
// is a solid colour (so it is drawn straight over the city or a translucent/blurred fill), or when the card that
// holds it is faded (opacity < 1) or blurs what is behind it.
// Run on a private port with heavy.lock: TILO_WEB_PORT=5795 pnpm --filter @tilo/web exec playwright test
// e2e/park-glass-verify.spec.ts --project=chromium --no-deps --workers=1
// GLASS_OUT=<dir> also writes one PNG per scene (the before/after shots of agy-bridge/reports/glass-verify/).
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { type Page, expect, test } from "@playwright/test";

const OUT = process.env.GLASS_OUT;
const TAG = process.env.GLASS_TAG ?? "after";

interface Scene {
  readonly name: string;
  readonly path: string;
  readonly prep?: (page: Page) => Promise<void>;
}

const SCENES: readonly Scene[] = [
  {
    name: "home-confirm",
    path: "/",
    prep: async (page) => {
      await page.getByRole("textbox", { name: "Describe your task" }).fill("Compare suppliers");
      await page.getByRole("button", { name: "Start task", exact: true }).click();
      await page.locator(".park-home-plan").waitFor({ timeout: 15_000 });
    },
  },
  { name: "home", path: "/" },
  { name: "worlds", path: "/worlds" },
  { name: "world", path: "/world/k1" },
  { name: "world-story", path: "/world/k1/story" },
  { name: "world-trace", path: "/world/k1/trace" },
  { name: "world-delivery", path: "/world/k1/delivery" },
  { name: "skills", path: "/skills" },
  { name: "agenda", path: "/agenda" },
  { name: "team", path: "/team" },
  { name: "connectors", path: "/connectors" },
  { name: "profile", path: "/profile" },
  { name: "ledger", path: "/ledger" },
  { name: "stage", path: "/world/w_village_basic/stage?fixture=village-basic" },
  {
    name: "popover-notifications",
    path: "/",
    prep: async (page) => {
      await page.getByRole("button", { name: "Notifications" }).click();
    },
  },
  {
    name: "popover-account",
    path: "/",
    prep: async (page) => {
      await page.getByRole("button", { name: "Account menu" }).click();
    },
  },
  {
    name: "toast-world",
    path: "/world/k1",
    prep: async (page) => {
      const approve = page.getByRole("button", { name: /^Approve/ }).first();
      if ((await approve.count()) > 0) await approve.click();
      await page.locator(".park-toast").first().waitFor({ timeout: 5_000 });
    },
  },
];

const VIEWS = [
  { tag: "1440", width: 1440, height: 900 },
  { tag: "390", width: 390, height: 844 },
] as const;

/** Runs in the page: the text runs that have no solid card under them. */
function scan(): { sel: string; text: string; why: string }[] {
  const rgba = (c: string): [number, number, number, number] => {
    const m = /rgba?\(([^)]+)\)/.exec(c);
    if (!m) return [0, 0, 0, 0];
    const p = (m[1] ?? "")
      .split(/[ ,/]+/)
      .filter(Boolean)
      .map(Number);
    return [p[0] ?? 0, p[1] ?? 0, p[2] ?? 0, p[3] ?? 1];
  };
  const PAGE_LEVEL = (el: Element) =>
    el === document.body ||
    el === document.documentElement ||
    el.hasAttribute("data-park") ||
    el.tagName === "MAIN" ||
    /(^|\s)(park-shell__(main|page|root|content)|park-home-root|park-page)(\s|$)/.test(
      el.className?.toString() ?? "",
    );
  const out: { sel: string; text: string; why: string }[] = [];
  const seen = new Set<string>();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = (n.textContent ?? "").trim();
    const el = n.parentElement;
    if (!el || text.length < 2) continue;
    if (el.closest("script,style,noscript,svg,[hidden],[aria-hidden='true']")) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) === 0) continue;
    if (r.bottom < 0 || r.top > innerHeight * 3) continue;
    let why = "";
    let solid: Element | null = null;
    for (let a: Element | null = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      const [, , , alpha] = rgba(s.backgroundColor);
      if (s.backdropFilter !== "none" && s.backdropFilter !== "") {
        why = `blurs behind (${s.backdropFilter})`;
      }
      if (alpha >= 0.999 && !PAGE_LEVEL(a)) {
        solid = a;
        break;
      }
      if (alpha > 0 && alpha < 0.999 && why === "")
        why = `translucent fill (alpha ${alpha.toFixed(2)})`;
      if (PAGE_LEVEL(a)) break;
    }
    if (solid) {
      // tints and blurs between the text and a solid card are harmless. A faded solid fill (a disabled button, a
      // done pin) is a defect only when no other solid card sits behind it: one above it hides the city again.
      why = "";
      let fadedAt: Element | null = null;
      for (let a: Element | null = solid; a; a = a.parentElement) {
        const o = Number(getComputedStyle(a).opacity);
        if (o < 0.999 && o > 0) {
          fadedAt = a;
          why = `solid card faded (opacity ${o.toFixed(2)})`;
          break;
        }
      }
      for (let a = fadedAt?.parentElement ?? null; a && !PAGE_LEVEL(a); a = a.parentElement) {
        const [, , , alpha] = rgba(getComputedStyle(a).backgroundColor);
        if (alpha >= 0.999) {
          why = "";
          break;
        }
      }
    } else if (why === "") {
      why = "drawn straight over the page (no card fill)";
    }
    if (why === "") continue;
    const cls = (el.className?.toString() ?? "").split(/\s+/).filter(Boolean).slice(0, 2).join(".");
    const sel = `${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""}`;
    const key = `${sel}|${why}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ sel, text: text.slice(0, 40), why });
  }
  return out;
}

async function setTheme(page: Page, time: "day" | "night"): Promise<void> {
  const toggle = page.locator('button[aria-label^="Switch to"]').first();
  if ((await toggle.count()) === 0) return;
  const label = (await toggle.getAttribute("aria-label")) ?? "";
  const wantsNight = time === "night";
  const isDay = /night/i.test(label); // "Switch to night" is offered while it is day
  if (wantsNight === isDay) await toggle.click();
  await page.waitForTimeout(400);
}

for (const v of VIEWS) {
  for (const time of ["day", "night"] as const) {
    test.describe(`GLASS-VERIFY ${v.tag} ${time}`, () => {
      test.use({ viewport: { width: v.width, height: v.height } });
      for (const s of SCENES) {
        test(`GLASS_VERIFY_${s.name}_${v.tag}_${time}`, async ({ page }) => {
          await page.goto(s.path, { timeout: 120_000 });
          await expect(page.locator("[data-park]").first()).toBeVisible({ timeout: 120_000 });
          await page.evaluate(() => document.fonts.ready.then(() => undefined));
          await setTheme(page, time);
          await page.waitForTimeout(1200);
          if (s.prep) {
            await s.prep(page);
            await page.waitForTimeout(600);
          }
          const found = await page.evaluate(scan);
          if (OUT) {
            mkdirSync(join(OUT, TAG), { recursive: true });
            await page.screenshot({ path: join(OUT, TAG, `${s.name}-${v.tag}-${time}.png`) });
          }
          if (OUT && found.length > 0) {
            const lines = found.map((f) => `  ${f.sel} "${f.text}": ${f.why}`);
            appendFileSync(
              join(OUT, TAG, "findings.txt"),
              [`${s.name} ${v.tag} ${time}`, ...lines, ""].join(String.fromCharCode(10)),
            );
          }
          expect(
            found.map((f) => `${f.sel} "${f.text}": ${f.why}`),
            `${s.name} ${v.tag} ${time}`,
          ).toEqual([]);
        });
      }
    });
  }
}
