// WEB-MOTION-2 acceptance: the boot splash, the page transitions and the open-a-world steps of the Park web app,
// in a real browser. Pinned to design_handoff_tilo_web_app/README.md "Interactions and motion" (Page change, Open a
// world, Boot, Async actions, Reduced motion), "Performance", and the keyframes of the reference
// (design_handoff_tilo_web_app/design/Tilo App.dc.html: tiloSlide, tiloSpin):
//   Boot         a paper splash, a 200 px bar sliding with tiloSlide 1.1 s, "Loading your city"; the shell stays
//                hidden under it until the fonts are in; then it fades over .45 s and goes; the page bundles are
//                prefetched afterwards.
//   Page change  out: opacity 0 and translateY(-4px) in 200 ms; the page swaps and the window scrolls to the top;
//                in: from translateY(10px), opacity .24 s ease and transform .38 s cubic-bezier(.2,.8,.2,1). The top
//                bar steps 35% -> 78% -> 100%, hides, resets.
//   Open a world 3 steps, every 340 ms (a city) or 250 ms (a town or village); the page swaps at step 3; the card
//                fades out over 280 ms; the ring spins with tiloSpin .7 s.
// The bar for all of it (ticket): animate only transform and opacity (a bar may scaleX), no backdrop-filter on a
// moving layer, no animation at all under prefers-reduced-motion or the 'still' motion preference (a page change is
// then instant), CLS 0, no sideways scroll at 390, no console error, no requestAnimationFrame loop, and on a 4x
// CPU-throttled 390x844 phone no long task over 50 ms during transitions. HR-1 to HR-7: this is UI chrome that moves
// when a person acts, never a state of an agent; a settled page shows no motion of its own.
//
// How motion is seen: the specs never ask HOW the app moves (CSS transition, CSS animation or script). The probe in
// e2e/support/motionProbe.ts writes down every animation the browser reports (duration, easing, the properties, the
// first and last value) and samples the chrome every ~4 ms. A page swap is the moment <main>'s text changes; the
// shipped markup the specs rely on is the shell's own: the nav's `.park-shell__bar` (its first child is the fill),
// the splash `[aria-label="Loading Tilo"]`, the loader's `[role=status]` with "OPENING" and `.park-shell__lbar`.
// Tabs are clicked from script (not input), so any layout shift they cause still counts toward CLS.
// Run on a private port, one worker:
//   TILO_WEB_PORT=5393 pnpm --filter @tilo/web exec playwright test e2e/park-motion-transitions.spec.ts --project=chromium --no-deps --workers=1
import { type Browser, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import {
  type AnimRec,
  type ProbeData,
  type Sample,
  installProbe,
  readProbe,
  startProbe,
} from "./support/motionProbe";
import { DESKTOP, MOBILE } from "./support/viewports";

const SIZES = [
  ["1440", DESKTOP],
  ["390", MOBILE],
] as const;
/** The pages that are real today and lazy-loaded (README "Prefetch the page bundles afterwards"). */
const BUNDLES = [
  "Skills/SkillsPage",
  "Ledger/LedgerPage",
  "Agenda/AgendaPage",
  "Team/TeamPage",
  "Profile/ProfilePage",
  "Connectors/ConnectorsPage",
];
const WARM = [
  "ledger",
  "agenda",
  "team",
  "skills",
  "profile",
  "connectors",
  "worlds",
  "world/k1",
] as const;
const TAB_SELECTOR = 'header nav[aria-label="Main"] a';

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it once.
test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(240_000);
  const page = await browser.newPage(baseURL ? { baseURL } : {});
  await page.goto("/park/home", { timeout: 200_000 });
  await page
    .locator("header")
    .waitFor({ timeout: 200_000 })
    .catch(() => undefined);
  await page.close();
});

// ---- helpers ----

interface Device {
  viewport?: { width: number; height: number };
  reducedMotion?: "reduce" | "no-preference";
  /** Install the probe (default true). Off for the performance run, which must not carry its polling. */
  probe?: boolean;
  /** Count requestAnimationFrame calls from the first script on. */
  raf?: boolean;
  /** Record layout shifts (CLS) from the first script on. */
  cls?: boolean;
}

/** A fresh context and page with a strong device (the budget's weak-device rules must not fire on a small CI box). */
async function newPage(
  browser: Browser,
  baseURL: string | undefined,
  d: Device = {},
): Promise<Page> {
  const ctx = await browser.newContext({
    ...(baseURL ? { baseURL } : {}),
    viewport: d.viewport ?? DESKTOP,
    reducedMotion: d.reducedMotion ?? "no-preference",
  });
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "hardwareConcurrency", { configurable: true, get: () => 8 });
    Object.defineProperty(navigator, "deviceMemory", { configurable: true, get: () => 8 });
  });
  if (d.probe !== false) await page.addInitScript(installProbe);
  if (d.raf)
    await page.addInitScript(() => {
      const w = window as unknown as { __raf: number };
      w.__raf = 0;
      const orig = window.requestAnimationFrame.bind(window);
      window.requestAnimationFrame = (cb: FrameRequestCallback) => {
        w.__raf += 1;
        return orig(cb);
      };
    });
  if (d.cls)
    await page.addInitScript(() => {
      const seen = { total: 0 };
      const po = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          const s = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
          if (!s.hadRecentInput) seen.total += s.value;
        }
      });
      po.observe({ type: "layout-shift", buffered: true });
      Reflect.set(window, "__cls", { seen, po });
    });
  return page;
}

const cls = (page: Page): Promise<number> =>
  page.evaluate(() => {
    const held = Reflect.get(window, "__cls") as {
      seen: { total: number };
      po: PerformanceObserver;
    };
    for (const e of held.po.takeRecords()) {
      const s = e as PerformanceEntry & { value: number; hadRecentInput: boolean };
      if (!s.hadRecentInput) held.seen.total += s.value;
    }
    return held.seen.total;
  });
const rafCount = (page: Page): Promise<number> =>
  page.evaluate(() => (window as unknown as { __raf: number }).__raf);

/** Holds every font request until `release()`: the splash can then be looked at for as long as the test needs. */
async function holdFonts(page: Page): Promise<() => void> {
  let release: () => void = () => undefined;
  const gate = new Promise<void>((done) => {
    release = done;
  });
  await page.route(/\.woff2?(\?.*)?$/, async (route) => {
    await gate;
    await route.continue().catch(() => undefined);
  });
  return release;
}

/** Boot is over, the fonts are in, the city is on screen. */
async function booted(page: Page): Promise<void> {
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByText("Loading your city")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(".park-shell__backdrop")).toBeAttached();
  await expect.poll(() => page.evaluate(() => document.fonts.status)).toBe("loaded");
  await page.waitForTimeout(300);
}

/** Same-document navigation by the History API (no tab click, so no transition is asked for). */
const go = (page: Page, path: string) =>
  page.evaluate((p) => {
    window.history.pushState({}, "", p);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, `/park/${path}`);

/** A booted page on `path`, every lazy page visited once (so a chunk fetch is never what a transition measures). */
async function settled(
  browser: Browser,
  baseURL: string | undefined,
  path: string,
  d: Device = {},
): Promise<Page> {
  const page = await newPage(browser, baseURL, d);
  await page.goto(`/park/${path}`);
  await booted(page);
  for (const p of WARM) {
    await go(page, p);
    await page.waitForTimeout(250);
  }
  await go(page, path);
  await page.waitForTimeout(1_500);
  return page;
}

/** A script click on the nav tab `label`, starting the probe in the same task so t = 0 is the click. */
const clickTab = (page: Page, label: string, restart = true) =>
  page.evaluate(
    ({ label: name, restart: reset, sel }) => {
      if (reset) (window as unknown as { __probe: { start(): void } }).__probe.start();
      const tab = [...document.querySelectorAll(sel)].find(
        (a) => (a.textContent ?? "").replace(/\d+$/, "").trim() === name,
      ) as HTMLElement | undefined;
      if (!tab) throw new Error(`no tab named ${name}`);
      tab.click();
    },
    { label, restart, sel: TAB_SELECTOR },
  );

const near = (a: number, b: number, tol: number): boolean => Math.abs(a - b) <= tol;
/** translateY in px of a transform value as the browser reports it ("none", translateY(), translate(), matrix()). */
function ty(v: string | undefined): number {
  if (v === undefined || v === "" || v === "none") return 0;
  let m = /translateY\(\s*(-?[\d.]+)px\s*\)/.exec(v);
  if (m) return Number(m[1]);
  m = /translate3?d?\(\s*[^,)]+,\s*(-?[\d.]+)px/.exec(v);
  if (m) return Number(m[1]);
  m = /matrix\(([^)]+)\)/.exec(v);
  if (m) return Number((m[1] ?? "").split(",")[5]);
  m = /matrix3d\(([^)]+)\)/.exec(v);
  if (m) return Number((m[1] ?? "").split(",")[13]);
  return Number.NaN;
}
const bezier = (s: string): number[] | null => {
  const m = /cubic-bezier\(([^)]+)\)/.exec(s);
  return m ? (m[1] ?? "").split(",").map(Number) : null;
};
/** The timing function of a record: a CSS animation keeps it on the keyframes, a transition on the effect. */
const easingOf = (r: AnimRec): string => (r.easing !== "linear" ? r.easing : r.keyEasing);
const isCurve = (e: string, want: readonly number[]): boolean => {
  const b = bezier(e) ?? (e === "ease" ? [0.25, 0.1, 0.25, 1] : null);
  return b !== null && b.length === 4 && b.every((v, i) => near(v, want[i] ?? Number.NaN, 0.001));
};
const PAGE_CURVE = [0.2, 0.8, 0.2, 1] as const;
const chrome = (recs: readonly AnimRec[]): AnimRec[] => recs.filter((r) => r.zone !== "city");

/** Everything the budget says about what may animate, for every record the probe saw outside the city. */
function expectCompositorOnly(recs: readonly AnimRec[]): void {
  for (const r of chrome(recs)) {
    for (const p of r.props) {
      expect(["transform", "opacity"], `${r.zone} ${r.name} ${r.tag} animates ${p}`).toContain(p);
    }
    expect(r.blurred, `${r.zone} ${r.name} ${r.tag} is, or sits under, a backdrop-filter`).toBe(
      false,
    );
  }
}

/** First sample time where `pick` is true. */
const when = (samples: readonly Sample[], pick: (s: Sample) => boolean): number | undefined =>
  samples.find(pick)?.t;

// ---- Boot ----

for (const [size, viewport] of SIZES) {
  test.describe(`WEB-MOTION-2 boot at ${size}`, () => {
    test(`WEB-MOTION-2 e2e: at ${size} the splash shows the logo, "Loading your city" and a bar sliding with tiloSlide 1.1 s while the fonts load; the shell stays hidden and nothing shifts`, async ({
      browser,
      baseURL,
    }) => {
      test.setTimeout(90_000);
      const page = await newPage(browser, baseURL, { viewport, cls: true });
      const problems = collectConsoleProblems(page);
      const release = await holdFonts(page);
      try {
        await page.goto("/park/home", { waitUntil: "commit" });
        const splash = page.getByRole("status", { name: "Loading Tilo" });
        await expect(splash).toBeVisible();
        await expect(splash).toContainText("tilo");
        await expect(splash).toContainText("Loading your city");
        await expect(page.locator("header")).toBeHidden();
        await expect(page.getByRole("main")).toBeHidden();

        await expect
          .poll(
            async () =>
              (await readProbe(page)).recs.some(
                (r) => r.zone === "splash" && r.name === "tiloSlide",
              ),
            {
              timeout: 10_000,
              message: "the splash's bar does not slide with tiloSlide",
            },
          )
          .toBe(true);
        const slide = (await readProbe(page)).recs.find(
          (r) => r.zone === "splash" && r.name === "tiloSlide",
        ) as AnimRec;
        expect(slide.dur, "tiloSlide lasts 1.1 s").toBe(1100);
        expect(slide.iterations, "the bar slides for as long as the splash is up").toBe(
          Number.POSITIVE_INFINITY,
        );
        expect(isCurve(easingOf(slide), [0.4, 0, 0.2, 1]), `easing ${easingOf(slide)}`).toBe(true);
        expect(slide.props).toEqual(["transform"]);
        expect(slide.from.transform).toContain("-110%");
        expect(slide.to.transform).toContain("260%");

        // Something inside the splash really moves (the bar), and the splash itself does not.
        const moved = await page.evaluate(async () => {
          const root = document.querySelector('[aria-label="Loading Tilo"]') as Element;
          const els = [root, ...root.querySelectorAll("*")];
          const read = () => els.map((e) => e.getBoundingClientRect().left);
          const a = read();
          await new Promise((done) => setTimeout(done, 350));
          const b = read();
          return els.map((_, i) => Math.abs((b[i] ?? 0) - (a[i] ?? 0)) > 2);
        });
        expect(moved[0], "the splash itself moved").toBe(false);
        expect(moved.filter(Boolean).length, "the bar does not move").toBeGreaterThanOrEqual(1);
        const data = await readProbe(page);
        expectCompositorOnly(data.recs);
        expect(
          data.samples.some((s) => s.navVisible),
          "the shell showed under the splash before the fonts were in",
        ).toBe(false);
      } finally {
        release();
      }
      await booted(page);
      await page.waitForTimeout(500);
      expect(await cls(page), "cumulative layout shift across the boot").toBe(0);
      expect(problems).toEqual([]);
      await page.context().close();
    });

    test(`WEB-MOTION-2 e2e: at ${size} once the shell is ready the splash fades over .45 s, is not cut early, and then goes`, async ({
      browser,
      baseURL,
    }) => {
      test.setTimeout(90_000);
      const page = await newPage(browser, baseURL, { viewport, cls: true });
      const release = await holdFonts(page);
      try {
        await page.goto("/park/home", { waitUntil: "commit" });
        await expect(page.getByRole("status", { name: "Loading Tilo" })).toBeVisible();
        await page.waitForTimeout(400);
        const releasedAt = await page.evaluate(() => performance.now());
        release();
        await expect
          .poll(async () => (await readProbe(page)).samples.at(-1)?.splash === null, {
            timeout: 20_000,
          })
          .toBe(true);
      } finally {
        release();
      }
      const { recs, samples } = await readProbe(page);
      const fade = recs.find(
        (r) => r.zone === "splash" && r.props.includes("opacity") && Number(r.to.opacity) === 0,
      );
      expect(fade, "the splash does not fade out").toBeDefined();
      expect(near(fade?.dur ?? 0, 450, 2), `the fade lasts ${fade?.dur} ms, not .45 s`).toBe(true);
      expect(fade?.props, "the fade changes opacity only").toEqual(["opacity"]);
      const lastUp = samples.map((s) => s.splash !== null).lastIndexOf(true);
      const goneAt = samples[lastUp + 1]?.t ?? Number.NaN;
      const fadeAt = fade?.t ?? Number.NaN;
      expect(goneAt - fadeAt, "the splash was cut before its fade ran").toBeGreaterThanOrEqual(430);
      expect(goneAt - fadeAt, "the splash lingers after its fade").toBeLessThanOrEqual(1_000);
      const revealedAt = when(samples, (s) => s.navVisible) ?? Number.NaN;
      expect(revealedAt, "the shell shows no later than the fade begins").toBeLessThanOrEqual(
        fadeAt + 30,
      );
      const during = samples.filter((s) => s.splash && s.t >= fadeAt);
      for (let i = 1; i < during.length; i++) {
        expect(during[i]?.splash?.op ?? 0, "the splash fades one way").toBeLessThanOrEqual(
          (during[i - 1]?.splash?.op ?? 0) + 0.01,
        );
      }
      expect(during.at(-1)?.splash?.op ?? 1).toBeLessThanOrEqual(0.1);
      await booted(page);
      expect(await cls(page), "cumulative layout shift across the splash").toBe(0);
      await page.context().close();
    });
  });
}

test("WEB-MOTION-2 e2e: after the splash has gone the page bundles of the other pages are prefetched, and not before", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(90_000);
  const page = await newPage(browser, baseURL);
  const problems = collectConsoleProblems(page);
  await page.goto("/park/home");
  await booted(page);
  const names = (): Promise<{ name: string; start: number }[]> =>
    page.evaluate(() =>
      performance.getEntriesByType("resource").map((e) => ({ name: e.name, start: e.startTime })),
    );
  await expect
    .poll(
      async () => {
        const seen = await names();
        return BUNDLES.filter((b) => seen.some((e) => e.name.includes(`/pages/${b}`))).length;
      },
      { timeout: 10_000, message: "the page bundles are never prefetched" },
    )
    .toBe(BUNDLES.length);
  const { samples } = await readProbe(page);
  const lastUp = samples.map((s) => s.splash !== null).lastIndexOf(true);
  const goneAt = samples[lastUp + 1]?.t ?? Number.NaN;
  const early = (await names()).filter(
    (e) => BUNDLES.some((b) => e.name.includes(`/pages/${b}`)) && e.start < goneAt - 10,
  );
  expect(early, "a page bundle was fetched while the splash was still up").toEqual([]);
  expect(problems).toEqual([]);
  await page.context().close();
});

test("WEB-MOTION-2 e2e: with reduced motion the splash draws its bar at rest (nothing runs) and goes the moment the shell is ready, with no fade", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(90_000);
  const page = await newPage(browser, baseURL, { reducedMotion: "reduce", cls: true });
  const release = await holdFonts(page);
  try {
    await page.goto("/park/home", { waitUntil: "commit" });
    await expect(page.getByRole("status", { name: "Loading Tilo" })).toBeVisible();
    await expect(page.getByText("Loading your city")).toBeVisible();
    await page.waitForTimeout(600);
    const held = await readProbe(page);
    expect(chrome(held.recs), "animations started under reduced motion").toEqual([]);
    expect(held.samples.every((s) => s.running === 0)).toBe(true);
  } finally {
    release();
  }
  await expect
    .poll(async () => (await readProbe(page)).samples.at(-1)?.splash === null, { timeout: 20_000 })
    .toBe(true);
  const { recs, samples } = await readProbe(page);
  expect(chrome(recs), "a fade or a slide ran under reduced motion").toEqual([]);
  const revealedAt = when(samples, (s) => s.navVisible) ?? Number.NaN;
  const lastUp = samples.map((s) => s.splash !== null).lastIndexOf(true);
  const goneAt = samples[lastUp + 1]?.t ?? Number.NaN;
  expect(
    goneAt - revealedAt,
    "the splash lingers for a fade that is turned off",
  ).toBeLessThanOrEqual(120);
  expect(await cls(page)).toBe(0);
  await page.context().close();
});

// ---- Page change ----

/** The whole timeline of one page change, from the probe, against the README's numbers. */
function expectPageChange(data: ProbeData, at: string): { swapAt: number } {
  const { recs, samples } = data;
  const first = samples[0] as Sample;
  expect(first, `${at}: no samples`).toBeDefined();
  const swapAt = when(samples, (s) => s.mainText !== first.mainText);
  expect(swapAt, `${at}: the page never swapped`).toBeDefined();
  const swap = swapAt as number;
  // README: out first (200 ms), then the page swaps.
  expect(
    swap,
    `${at}: the page swapped before the old one had faded out (200 ms)`,
  ).toBeGreaterThanOrEqual(180);
  expect(swap, `${at}: the page took too long to swap`).toBeLessThanOrEqual(450);

  const ui = chrome(recs);
  const outs = ui.filter((r) => r.zone === "main" && r.t <= swap);
  const outOp = outs.find((r) => r.props.includes("opacity") && Number(r.to.opacity) === 0);
  expect(outOp, `${at}: the old page does not fade out`).toBeDefined();
  expect(outOp?.t ?? 999, `${at}: the old page starts to go late`).toBeLessThan(120);
  expect(near(outOp?.dur ?? 0, 200, 2), `${at}: out opacity lasts ${outOp?.dur} ms, not 200`).toBe(
    true,
  );
  const outTf = outs.find(
    (r) => r.props.includes("transform") && near(ty(r.to.transform), -4, 0.01),
  );
  expect(outTf, `${at}: the old page does not move to translateY(-4px)`).toBeDefined();
  expect(
    near(outTf?.dur ?? 0, 200, 2),
    `${at}: out transform lasts ${outTf?.dur} ms, not 200`,
  ).toBe(true);

  // README: in from translateY(10px); opacity .24 s ease, transform .38 s cubic-bezier(.2,.8,.2,1).
  const ins = ui.filter((r) => r.zone === "main" && r.t >= swap - 40 && r.t <= swap + 250);
  const inOp = ins.find((r) => r.props.includes("opacity") && Number(r.to.opacity) === 1);
  expect(inOp, `${at}: the new page does not fade in`).toBeDefined();
  expect(near(inOp?.dur ?? 0, 240, 2), `${at}: in opacity lasts ${inOp?.dur} ms, not 240`).toBe(
    true,
  );
  expect(
    isCurve(inOp ? easingOf(inOp) : "", [0.25, 0.1, 0.25, 1]),
    `${at}: in opacity easing ${inOp ? easingOf(inOp) : ""}`,
  ).toBe(true);
  expect(Number(inOp?.from.opacity ?? 1), `${at}: the new page starts visible`).toBeLessThanOrEqual(
    0.15,
  );
  const inTf = ins.find((r) => r.props.includes("transform") && near(ty(r.to.transform), 0, 0.01));
  expect(inTf, `${at}: the new page does not slide in`).toBeDefined();
  expect(near(inTf?.dur ?? 0, 380, 2), `${at}: in transform lasts ${inTf?.dur} ms, not 380`).toBe(
    true,
  );
  expect(
    isCurve(inTf ? easingOf(inTf) : "", PAGE_CURVE),
    `${at}: in transform easing ${inTf ? easingOf(inTf) : ""}`,
  ).toBe(true);
  expect(
    near(ty(inTf?.from.transform), 10, 0.5),
    `${at}: the new page starts at translateY(${ty(inTf?.from.transform)}px), not 10px`,
  ).toBe(true);

  // The budget: transform and opacity only, no blur on a moving layer.
  expectCompositorOnly(recs);

  // README: the top bar steps 35% -> 78% -> 100%, hides, resets.
  const shown = samples.filter((s) => s.barOp >= 0.5);
  expect(shown.length, `${at}: the progress bar never showed`).toBeGreaterThan(0);
  expect(shown[0]?.t ?? 999, `${at}: the bar shows late`).toBeLessThan(250);
  for (let i = 1; i < shown.length; i++) {
    expect(shown[i]?.barRatio ?? 0, `${at}: the bar went back`).toBeGreaterThanOrEqual(
      (shown[i - 1]?.barRatio ?? 0) - 0.01,
    );
  }
  const at35 = shown.findIndex((s) => s.barRatio >= 0.3 && s.barRatio <= 0.4);
  const at78 = shown.findIndex((s) => s.barRatio >= 0.74 && s.barRatio <= 0.82);
  const at100 = shown.findIndex((s) => s.barRatio >= 0.999);
  expect(at35, `${at}: the bar never reads 35%`).toBeGreaterThanOrEqual(0);
  expect(at78, `${at}: the bar never reads 78% after 35%`).toBeGreaterThan(at35);
  expect(at100, `${at}: the bar never reaches 100% after 78%`).toBeGreaterThan(at78);
  expect(
    shown.at(-1)?.t ?? 0,
    `${at}: the bar hides before the new page is in`,
  ).toBeGreaterThanOrEqual(swap + 100);
  const last = samples.at(-1) as Sample;
  expect(last.barOp, `${at}: the bar is still showing`).toBeLessThanOrEqual(0.01);
  expect(last.barRatio, `${at}: the bar was not reset`).toBeLessThanOrEqual(0.01);
  expect(last.running, `${at}: something is still running after the change`).toBe(0);
  return { swapAt: swap };
}

for (const [size, viewport] of SIZES) {
  test.describe(`WEB-MOTION-2 page change at ${size}`, () => {
    test(`WEB-MOTION-2 e2e: at ${size} a tab click from Home fades the old page out in 200 ms, swaps, and brings the new one in (.24 s opacity, .38 s transform); the bar steps to 100% and goes; CLS 0; nothing runs afterwards`, async ({
      browser,
      baseURL,
    }) => {
      test.setTimeout(120_000);
      const page = await settled(browser, baseURL, "home", { viewport, cls: true });
      const problems = collectConsoleProblems(page);
      const before = await cls(page);
      await clickTab(page, "Ledger");
      await page.waitForTimeout(2_400);
      const data = await readProbe(page);
      expectPageChange(data, `${size} Home to Ledger`);
      await expect(page.getByRole("heading", { level: 1, name: "Ledger" })).toBeVisible();
      expect((await cls(page)) - before, "layout shift across the page change").toBe(0);
      expect(
        data.samples.every((s) => s.docW <= s.clientW),
        "sideways scroll during the change",
      ).toBe(true);
      expect(problems).toEqual([]);
      await page.context().close();
    });

    test(`WEB-MOTION-2 e2e: at ${size} a tab click between two inner pages does the same, scrolls to the top at the swap (not before), and runs no requestAnimationFrame loop`, async ({
      browser,
      baseURL,
    }) => {
      test.setTimeout(120_000);
      const page = await settled(browser, baseURL, "ledger", { viewport, cls: true, raf: true });
      const problems = collectConsoleProblems(page);
      await page.evaluate(() => window.scrollTo(0, 400));
      await expect
        .poll(() => page.evaluate(() => window.scrollY), {
          message: "the Ledger is too short to scroll",
        })
        .toBeGreaterThan(100);
      const framesBefore = await rafCount(page);
      const shiftBefore = await cls(page);
      await clickTab(page, "Agenda");
      await page.waitForTimeout(2_400);
      const data = await readProbe(page);
      const { swapAt } = expectPageChange(data, `${size} Ledger to Agenda`);
      await expect(page.getByRole("heading", { level: 1, name: "Agenda" })).toBeVisible();
      const early = data.samples.filter((s) => s.t < swapAt - 20);
      expect(early.length).toBeGreaterThan(0);
      expect(
        early.every((s) => s.scrollY > 100),
        "the window scrolled to the top before the swap",
      ).toBe(true);
      const after = data.samples.filter((s) => s.t >= swapAt + 60);
      expect(
        after.every((s) => s.scrollY === 0),
        "the new page is not at the top",
      ).toBe(true);
      expect(
        (await rafCount(page)) - framesBefore,
        "requestAnimationFrame calls during the change",
      ).toBe(0);
      expect((await cls(page)) - shiftBefore, "layout shift across the page change").toBe(0);
      expect(
        data.samples.every((s) => s.docW <= s.clientW),
        "sideways scroll during the change",
      ).toBe(true);
      expect(problems).toEqual([]);
      await page.context().close();
    });
  });
}

test("WEB-MOTION-2 e2e: two tab clicks in a row end on the second page, with the page fully in, the bar gone and nothing running", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(120_000);
  const page = await settled(browser, baseURL, "home");
  const problems = collectConsoleProblems(page);
  await clickTab(page, "Ledger");
  await page.waitForTimeout(80);
  await clickTab(page, "Agenda", false);
  await page.waitForTimeout(2_600);
  await expect(page).toHaveURL(/\/park\/agenda$/);
  await expect(page.getByRole("heading", { level: 1, name: "Agenda" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Ledger" })).toHaveCount(0);
  const { samples } = await readProbe(page);
  const last = samples.at(-1) as Sample;
  expect(last.barOp, "the bar is stuck").toBeLessThanOrEqual(0.01);
  expect(last.running, "an animation is stuck").toBe(0);
  const shown = await page.evaluate(() => {
    const h1 = document.querySelector("main h1") as Element;
    let op = 1;
    for (let n: Element | null = h1; n && n !== document.documentElement; n = n.parentElement)
      op *= Number(getComputedStyle(n).opacity);
    return op;
  });
  expect(shown, "the page is stuck half faded").toBeGreaterThanOrEqual(0.99);
  expect(problems).toEqual([]);
  await page.context().close();
});

test("WEB-MOTION-2 e2e: a settled page shows no motion of its own (nothing pulses, slides or fades while nobody acts; HR-2)", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(120_000);
  const page = await settled(browser, baseURL, "ledger");
  await startProbe(page);
  await page.waitForTimeout(2_500);
  const { recs, samples } = await readProbe(page);
  expect(chrome(recs), "an animation started with nobody acting").toEqual([]);
  expect(
    samples.every(
      (s) => s.running === 0 && s.barOp <= 0.01 && s.splash === null && s.loader === null,
    ),
  ).toBe(true);
  await page.context().close();
});

test("WEB-MOTION-2 e2e: with prefers-reduced-motion a tab click swaps the page at once and starts no animation or transition anywhere", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(120_000);
  const page = await settled(browser, baseURL, "home", { reducedMotion: "reduce", cls: true });
  const problems = collectConsoleProblems(page);
  const shiftBefore = await cls(page);
  await clickTab(page, "Ledger");
  await page.waitForTimeout(1_800);
  const { recs, samples } = await readProbe(page);
  expect(chrome(recs), "animations ran under reduced motion").toEqual([]);
  expect(
    samples.every((s) => s.running === 0),
    "something ran under reduced motion",
  ).toBe(true);
  const first = samples[0] as Sample;
  const swapAt = when(samples, (s) => s.mainText !== first.mainText);
  expect(swapAt, "the page never swapped").toBeDefined();
  expect(swapAt ?? 999, "the page change is not instant under reduced motion").toBeLessThanOrEqual(
    150,
  );
  expect(samples.filter((s) => s.barOp > 0.01).every((s) => s.running === 0)).toBe(true);
  expect(samples.at(-1)?.barOp ?? 1, "the bar is still showing").toBeLessThanOrEqual(0.01);
  await expect(page.getByRole("heading", { level: 1, name: "Ledger" })).toBeVisible();
  expect((await cls(page)) - shiftBefore, "layout shift across the page change").toBe(0);
  expect(problems).toEqual([]);
  await page.context().close();
});

test("WEB-MOTION-2 e2e: with the 'still' motion preference (Profile > Appearance) a tab click is instant and starts no animation or transition", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(120_000);
  const page = await settled(browser, baseURL, "profile");
  await go(page, "profile?tab=appearance");
  await page.getByRole("button", { name: "Still", exact: true }).click();
  await expect(page.getByRole("button", { name: "Still", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.waitForTimeout(800);
  await clickTab(page, "Ledger");
  await page.waitForTimeout(1_800);
  const { recs, samples } = await readProbe(page);
  expect(chrome(recs), "animations ran with the still preference").toEqual([]);
  expect(samples.every((s) => s.running === 0)).toBe(true);
  const first = samples[0] as Sample;
  const swapAt = when(samples, (s) => s.mainText !== first.mainText);
  expect(
    swapAt ?? 999,
    "the page change is not instant with the still preference",
  ).toBeLessThanOrEqual(150);
  await expect(page.getByRole("heading", { level: 1, name: "Ledger" })).toBeVisible();
  await page.context().close();
});

test("WEB-MOTION-2 e2e: at 390x844 with the CPU slowed 4x, no long task over 50 ms while pages change (Home, Ledger, Agenda, Team, Skills, Home)", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(180_000);
  const page = await settled(browser, baseURL, "home", { viewport: MOBILE, probe: false });
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await page.waitForTimeout(500);
  const supported = await page.evaluate(() =>
    PerformanceObserver.supportedEntryTypes.includes("longtask"),
  );
  expect(supported, "the browser must report long tasks").toBe(true);
  await page.evaluate(() => {
    const seen: number[] = [];
    Reflect.set(window, "__long", seen);
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) seen.push(e.duration);
    }).observe({ type: "longtask" });
  });
  const tour = ["Ledger", "Agenda", "Team", "Skills", "Home"];
  for (const label of tour) {
    await clickTab(page, label, false);
    await page.waitForTimeout(1_800);
  }
  const long = await page.evaluate(() => Reflect.get(window, "__long") as number[]);
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  expect(
    long.filter((d) => d > 50),
    "long tasks (ms) while pages change at 4x",
  ).toEqual([]);
  await page.context().close();
});

// ---- Open a world ----

/** The loader's timeline from the probe: the three steps, the swap at step 3, the fade (or none), the bars. */
function expectLoader(
  data: ProbeData,
  o: { stepMs: number; reduced: boolean; size: string },
): void {
  const { recs, samples } = data;
  const at = `${o.size} ${o.stepMs} ms`;
  const opened = when(samples, (s) => s.loader !== null);
  expect(opened, `${at}: no loader card showed`).toBeDefined();
  const t0 = opened as number;
  const tick = (n: number) => when(samples, (s) => (s.loader?.ticks ?? 0) >= n);
  const [t1, t2, t3] = [tick(1), tick(2), tick(3)];
  expect(t1 && t2 && t3, `${at}: the three steps did not tick`).toBeTruthy();
  const slack = 110;
  expect(
    near((t1 as number) - t0, o.stepMs, slack),
    `${at}: step 1 after ${(t1 as number) - t0} ms`,
  ).toBe(true);
  expect(
    near((t2 as number) - (t1 as number), o.stepMs, slack),
    `${at}: step 2 after ${(t2 as number) - (t1 as number)} ms`,
  ).toBe(true);
  expect(
    near((t3 as number) - (t2 as number), o.stepMs, slack),
    `${at}: step 3 after ${(t3 as number) - (t2 as number)} ms`,
  ).toBe(true);
  // The page swaps at step 3, under the card.
  const first = samples.find((s) => s.t >= t0 && s.loader) as Sample;
  const swapAt = when(samples, (s) => s.t > t0 && s.mainText !== first.mainText);
  expect(swapAt, `${at}: the page never swapped`).toBeDefined();
  expect(
    near(swapAt as number, t3 as number, 150),
    `${at}: swap at ${swapAt}, step 3 at ${t3}`,
  ).toBe(true);
  const lastUp = samples.map((s) => s.loader !== null).lastIndexOf(true);
  const goneAt = samples[lastUp + 1]?.t ?? Number.NaN;

  const ui = chrome(recs);
  if (o.reduced) {
    expect(ui, `${at}: animations ran under reduced motion`).toEqual([]);
    expect(samples.every((s) => s.running === 0)).toBe(true);
    expect(
      goneAt - (t3 as number),
      `${at}: the card lingers for a fade that is turned off`,
    ).toBeLessThanOrEqual(o.stepMs + 150);
    expect(goneAt - (t3 as number)).toBeGreaterThanOrEqual(o.stepMs - slack);
  } else {
    // README: the card fades out over 280 ms after the last step.
    const fade = ui.find(
      (r) => r.zone === "loader" && r.props.includes("opacity") && Number(r.to.opacity) === 0,
    );
    expect(fade, `${at}: the card does not fade out`).toBeDefined();
    expect(near(fade?.dur ?? 0, 280, 2), `${at}: the fade lasts ${fade?.dur} ms, not 280`).toBe(
      true,
    );
    expect(
      near((fade?.t ?? 0) - (t3 as number), o.stepMs, slack),
      `${at}: the fade starts ${(fade?.t ?? 0) - (t3 as number)} ms after step 3`,
    ).toBe(true);
    expect(
      goneAt - (fade?.t ?? 0),
      `${at}: the card was cut before its fade ran`,
    ).toBeGreaterThanOrEqual(260);
    expect(goneAt - (fade?.t ?? 0), `${at}: the card lingers after its fade`).toBeLessThanOrEqual(
      450,
    );
    // README Async actions: the current step's ring spins with tiloSpin .7 s.
    const spins = ui.filter((r) => r.zone === "loader" && r.name === "tiloSpin");
    expect(spins.length, `${at}: the ring does not spin`).toBeGreaterThan(0);
    for (const s of spins) {
      expect(s.dur).toBe(700);
      expect(s.iterations).toBe(Number.POSITIVE_INFINITY);
      expect(easingOf(s)).toBe("linear");
      expect(s.props).toEqual(["transform"]);
      expect(s.to.transform).toMatch(/360deg/);
    }
    expectCompositorOnly(recs);
  }
  expect(first.loader?.rings, `${at}: the first step shows one ring`).toBe(1);

  // The card's own bar: one way, from about 30% to full.
  const bar = samples.filter((s) => s.loader).map((s) => s.loader?.ratio ?? 0);
  expect(bar[0] ?? 1, `${at}: the card's bar starts past 30%`).toBeLessThanOrEqual(0.31);
  for (let i = 1; i < bar.length; i++)
    expect(bar[i] ?? 0, `${at}: the card's bar went back`).toBeGreaterThanOrEqual(
      (bar[i - 1] ?? 0) - 0.01,
    );
  expect(Math.max(...bar), `${at}: the card's bar never fills`).toBeGreaterThanOrEqual(0.99);
  // The top bar follows it: it shows, only grows while the card is up, is full by step 3, and is gone at the end.
  const top = samples.filter((s) => s.loader && s.barOp >= 0.5).map((s) => s.barRatio);
  expect(top.length, `${at}: the top bar did not show while the card was up`).toBeGreaterThan(0);
  for (let i = 1; i < top.length; i++)
    expect(top[i] ?? 0, `${at}: the top bar went back`).toBeGreaterThanOrEqual(
      (top[i - 1] ?? 0) - 0.01,
    );
  expect(
    Math.max(...top),
    `${at}: the top bar is not full by the page swap`,
  ).toBeGreaterThanOrEqual(0.99);
  const end = samples.at(-1) as Sample;
  expect(end.barOp, `${at}: the top bar is still showing`).toBeLessThanOrEqual(0.01);
  expect(end.barRatio).toBeLessThanOrEqual(0.01);
  expect(end.running, `${at}: something is still running`).toBe(0);
}

/** The bell, then the notification that opens a world (the same way a person does). */
async function openFromBell(page: Page, title: RegExp): Promise<void> {
  await page.getByRole("button", { name: "Notifications" }).click();
  await page.getByRole("button", { name: title }).click();
}

for (const [size, viewport] of SIZES) {
  test.describe(`WEB-MOTION-2 open a world at ${size}`, () => {
    test(`WEB-MOTION-2 e2e: at ${size} a city's steps tick every 340 ms, the page swaps at step 3, the ring spins (tiloSpin .7 s), the card fades out over 280 ms, bars one way`, async ({
      browser,
      baseURL,
    }) => {
      test.setTimeout(120_000);
      const page = await settled(browser, baseURL, "home", { viewport, cls: true });
      const problems = collectConsoleProblems(page);
      const shiftBefore = await cls(page);
      await startProbe(page);
      await openFromBell(page, /Laptop Depot needs budget sign-off/);
      await expect(page).toHaveURL(/\/park\/world\/k1$/, { timeout: 6_000 });
      await page.waitForTimeout(1_800);
      const data = await readProbe(page);
      expectLoader(data, { stepMs: 340, reduced: false, size });
      expect(
        data.samples.every((s) => s.docW <= s.clientW),
        "sideways scroll while the card was up",
      ).toBe(true);
      expect((await cls(page)) - shiftBefore, "layout shift while a world opens").toBe(0);
      expect(problems).toEqual([]);
      await page.context().close();
    });

    test(`WEB-MOTION-2 e2e: at ${size} a village's steps tick every 250 ms, with the same swap at step 3 and the same 280 ms fade`, async ({
      browser,
      baseURL,
    }) => {
      test.setTimeout(120_000);
      const page = await settled(browser, baseURL, "home", { viewport });
      await startProbe(page);
      await openFromBell(page, /Competitor pricing is ready/);
      await expect(page).toHaveURL(/\/park\/world\/comp$/, { timeout: 6_000 });
      await page.waitForTimeout(1_800);
      expectLoader(await readProbe(page), { stepMs: 250, reduced: false, size });
      await page.context().close();
    });
  });
}

test("WEB-MOTION-2 e2e: with prefers-reduced-motion opening a world still ticks its steps and swaps at step 3, but nothing spins, fades or slides, and the card goes at the last step", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(120_000);
  const page = await settled(browser, baseURL, "home", { reducedMotion: "reduce" });
  const problems = collectConsoleProblems(page);
  await startProbe(page);
  await openFromBell(page, /Competitor pricing is ready/);
  await expect(page).toHaveURL(/\/park\/world\/comp$/, { timeout: 6_000 });
  await page.waitForTimeout(1_500);
  expectLoader(await readProbe(page), { stepMs: 250, reduced: true, size: "reduced" });
  expect(problems).toEqual([]);
  await page.context().close();
});
