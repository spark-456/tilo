// WEB-MOTION-1 acceptance: the live city backdrop of the Park web app, in a real browser.
// Pinned to design_handoff_tilo_web_app/README.md "City backdrop" (animates only on Home; paused and
// covered by --veil everywhere else; drawn once, only cars and walkers are live layers), "Interactions and
// motion" (reduced motion), "Performance", and to the binding budget of the ticket (4x CPU throttle on a
// 390x844 phone: no long task over 50 ms; only transform and opacity animated; no backdrop-filter on a moving
// layer; sprite cap under 768 px and on weak devices; the loop stops when nothing moves; CLS 0 and no sideways
// scroll on every Park page; no console error). BQ-WEB-3: ambient cars and walkers may move; nothing else may.
//
// How motion is seen: the specs never ask HOW the city moves (CSS animation, WAAPI or a rAF loop are all
// fine). They sample the on-screen position of every element inside the backdrop twice, 900 ms apart, and
// count what moved ("moving") and by how much ("travel"). Which elements form the backdrop is the shipped
// WEB-3b markup: the fixed, aria-hidden `.park-shell__backdrop` layer and its `.park-shell__veil`.
// Run on a private port, one worker:
//   TILO_WEB_PORT=<own port> pnpm --filter @tilo/web exec playwright test e2e/park-motion-backdrop.spec.ts --project=chromium --no-deps --workers=1
import { type Browser, type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

const BACKDROP = ".park-shell__backdrop";
const VEIL = ".park-shell__veil";
const SAMPLE_MS = 900;
/** Every Park page (PAGE_IDS); the world page needs an id. */
const PAGES = [
  "home",
  "worlds",
  "world/k1",
  "skills",
  "ledger",
  "agenda",
  "team",
  "profile",
  "connectors",
] as const;
const INNER = PAGES.filter((p) => p !== "home");

// A cold Vite dev server optimises its dependencies on the first request and reloads the page; warm it
// once so no test pays for it.
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

/** A strong device (the budget's weak-device rules must not fire on a small CI box); a test can override it. */
const strongDevice = (page: Page) =>
  page.addInitScript(() => {
    Object.defineProperty(navigator, "hardwareConcurrency", { configurable: true, get: () => 8 });
    Object.defineProperty(navigator, "deviceMemory", { configurable: true, get: () => 8 });
  });
test.beforeEach(async ({ page }) => {
  await strongDevice(page);
});

interface Motion {
  /** Elements of the backdrop whose position changed. */
  moving: number;
  /** The sum of how far they moved, in px. */
  travel: number;
  /** Animations the browser reports as running anywhere in the document. */
  running: number;
}

/** Counts the backdrop's moving elements over `ms` (setTimeout, never rAF, so the probe adds no frames). */
const sample = (page: Page, ms = SAMPLE_MS): Promise<Motion> =>
  page.evaluate(
    async ({ sel, ms: wait }) => {
      const root = document.querySelector(sel);
      if (!root) return { moving: 0, travel: 0, running: 0 };
      const els = [...root.querySelectorAll("*")];
      const read = () =>
        els.map((e) => {
          const r = e.getBoundingClientRect();
          return [r.left, r.top] as const;
        });
      const a = read();
      await new Promise((done) => setTimeout(done, wait));
      const b = read();
      let moving = 0;
      let travel = 0;
      els.forEach((_, i) => {
        const d = Math.hypot(
          (b[i]?.[0] ?? 0) - (a[i]?.[0] ?? 0),
          (b[i]?.[1] ?? 0) - (a[i]?.[1] ?? 0),
        );
        if (d > 0.5) {
          moving += 1;
          travel += d;
        }
      });
      const running = document.getAnimations().filter((x) => x.playState === "running").length;
      return { moving, travel, running };
    },
    { sel: BACKDROP, ms },
  );

/** Boot is over, fonts are in, the city is on screen. */
async function booted(page: Page): Promise<void> {
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByText("Loading your city")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(BACKDROP)).toBeAttached();
  await expect.poll(() => page.evaluate(() => document.fonts.status)).toBe("loaded");
  await page.waitForTimeout(300);
}

/** Waits (8 s at most) until at least `min` elements of the city are moving. Fails with the numbers. */
async function liveCity(page: Page, min = 3): Promise<Motion> {
  let last: Motion = { moving: 0, travel: 0, running: 0 };
  await expect
    .poll(
      async () => {
        last = await sample(page, 400);
        return last.moving;
      },
      { timeout: 8_000, message: "the city's cars and walkers are not moving" },
    )
    .toBeGreaterThanOrEqual(min);
  return last;
}

/** Counts the app's requestAnimationFrame calls from now on (installed before the page loads). */
const countFrames = (page: Page) =>
  page.addInitScript(() => {
    const w = window as unknown as { __raf: number };
    w.__raf = 0;
    const orig = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (cb: FrameRequestCallback) => {
      w.__raf += 1;
      return orig(cb);
    };
  });
const frames = (page: Page, ms = 700): Promise<number> =>
  page.evaluate(async (wait) => {
    const w = window as unknown as { __raf: number };
    const from = w.__raf;
    await new Promise((done) => setTimeout(done, wait));
    return w.__raf - from;
  }, ms);

/** Same-document navigation, as the app's own router does it. */
const go = (page: Page, path: string) =>
  page.evaluate((p) => {
    window.history.pushState({}, "", p);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, `/park/${path}`);
const veiled = (page: Page, on: boolean) =>
  expect
    .poll(
      () =>
        page.evaluate(
          (s) => Number(getComputedStyle(document.querySelector(s) as Element).opacity),
          VEIL,
        ),
      {
        timeout: 5_000,
      },
    )
    .toBe(on ? 1 : 0);

const setHidden = (page: Page, hidden: boolean) =>
  page.evaluate((h) => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => h });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => (h ? "hidden" : "visible"),
    });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);

interface Device {
  viewport?: { width: number; height: number };
  cores?: number;
  memory?: number;
  reducedMotion?: "reduce" | "no-preference";
  /** Count requestAnimationFrame calls from the first script on (read with `frames`). */
  frames?: boolean;
}
/** A fresh page on Home with the given device, ready and settled. */
async function openHome(
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
  await page.addInitScript(
    ({ cores, memory }) => {
      if (cores !== undefined)
        Object.defineProperty(navigator, "hardwareConcurrency", {
          configurable: true,
          get: () => cores,
        });
      if (memory !== undefined)
        Object.defineProperty(navigator, "deviceMemory", { configurable: true, get: () => memory });
    },
    { cores: d.cores ?? 8, memory: d.memory ?? 8 },
  );
  if (d.frames) await countFrames(page);
  await page.goto("/park/home");
  await booted(page);
  return page;
}

test.describe("WEB-MOTION-1 the city on Home is alive", () => {
  test.use({ viewport: DESKTOP });

  test("WEB-MOTION-1 e2e: Home shows cars and walkers moving at 1440 (and the console stays clean)", async ({
    page,
  }) => {
    const problems = collectConsoleProblems(page);
    await page.goto("/park/home");
    await booted(page);
    const m = await liveCity(page, 3);
    expect(m.travel).toBeGreaterThan(5);
    expect(problems).toEqual([]);
  });

  test("WEB-MOTION-1 e2e: only cars and walkers are live layers; the drawn city never moves", async ({
    page,
  }) => {
    await page.goto("/park/home");
    await booted(page);
    await liveCity(page, 3);
    const report = await page.evaluate(
      async ({ sel, ms }) => {
        const root = document.querySelector(sel) as Element;
        const els = [...root.querySelectorAll("*")];
        const pos = () => els.map((e) => e.getBoundingClientRect());
        const a = pos();
        await new Promise((done) => setTimeout(done, ms));
        const b = pos();
        const big: string[] = [];
        let moving = 0;
        els.forEach((e, i) => {
          const [p, q] = [a[i], b[i]];
          if (!p || !q) return;
          const moved = Math.hypot(q.left - p.left, q.top - p.top) > 0.5;
          if (moved) moving += 1;
          // The static art is large (a building row, a road, a picture of the whole city); a car or a walker is small.
          if (moved && (q.width > 260 || q.height > 260))
            big.push(`${e.tagName} ${Math.round(q.width)}x${Math.round(q.height)}`);
        });
        const pictures = els.filter(
          (e) => e.tagName === "IMG" && e.getBoundingClientRect().width > 400,
        );
        return { moving, big, pictures: pictures.length };
      },
      { sel: BACKDROP, ms: SAMPLE_MS },
    );
    expect(report.moving).toBeGreaterThanOrEqual(3);
    expect(report.pictures, "the drawn city is one or more large pictures").toBeGreaterThan(0);
    expect(
      report.big,
      "a large element moved: the picture must be drawn once, not animated",
    ).toEqual([]);
  });

  test("WEB-MOTION-1 e2e: the page itself is still: outside the city nothing moves on Home (agents animate only from recorded events, HR-1, BQ-WEB-3)", async ({
    page,
  }) => {
    await page.goto("/park/home");
    await booted(page);
    await liveCity(page, 3);
    const outside = await page.evaluate(
      async ({ sel, ms }) => {
        const root = document.querySelector(sel);
        const els = [...document.body.querySelectorAll("*")].filter(
          (e) => !root?.contains(e) && e !== root,
        );
        const pos = () => els.map((e) => e.getBoundingClientRect());
        const a = pos();
        const running = document
          .getAnimations()
          .filter((x) => x.playState === "running")
          .map((x) => (x.effect as KeyframeEffect | null)?.target as Element | null)
          .filter((t) => t && !root?.contains(t))
          .map((t) => (t as Element).tagName);
        await new Promise((done) => setTimeout(done, ms));
        const b = pos();
        const moved = els
          .map((e, i) => ({
            e,
            d: Math.hypot(
              (b[i]?.left ?? 0) - (a[i]?.left ?? 0),
              (b[i]?.top ?? 0) - (a[i]?.top ?? 0),
            ),
          }))
          .filter((x) => x.d > 0.5)
          .map((x) => x.e.tagName);
        return { moved, running };
      },
      { sel: BACKDROP, ms: SAMPLE_MS },
    );
    expect(outside.running, "an animation running outside the city").toEqual([]);
    expect(outside.moved, "an element outside the city moved by itself").toEqual([]);
  });
});

test.describe("WEB-MOTION-1 paused under the veil, and when nobody is looking", () => {
  test.use({ viewport: DESKTOP });

  test("WEB-MOTION-1 e2e: the city runs on Home, stops under the --veil on every other page, and runs again on Home", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await countFrames(page);
    await page.goto("/park/home");
    await booted(page);
    await liveCity(page, 3);
    await veiled(page, false);
    for (const path of INNER) {
      await go(page, path);
      await veiled(page, true);
      await page.waitForTimeout(400); // a frame already scheduled may still run
      const m = await sample(page);
      expect(m.moving, `${path}: city elements still moving`).toBe(0);
      expect(m.running, `${path}: animations still running`).toBe(0);
      expect(await frames(page, 500), `${path}: the frame loop must have stopped`).toBe(0);
    }
    await go(page, "home");
    await veiled(page, false);
    const again = await liveCity(page, 3);
    expect(again.moving).toBeGreaterThanOrEqual(3);
  });

  test("WEB-MOTION-1 e2e: a hidden tab pauses the city and the frame loop, and showing it again resumes", async ({
    page,
  }) => {
    await countFrames(page);
    await page.goto("/park/home");
    await booted(page);
    await liveCity(page, 3);
    await setHidden(page, true);
    await page.waitForTimeout(400);
    const m = await sample(page);
    expect(m.moving, "city still moving in a hidden tab").toBe(0);
    expect(m.running).toBe(0);
    expect(await frames(page, 500), "frame loop still running in a hidden tab").toBe(0);
    await setHidden(page, false);
    await liveCity(page, 3);
  });
});

test.describe("WEB-MOTION-1 reduced motion is a static frame", () => {
  test("WEB-MOTION-1 e2e: prefers-reduced-motion shows the drawn city with nothing running, while the same page without it moves", async ({
    browser,
    baseURL,
  }) => {
    const live = await openHome(browser, baseURL, { reducedMotion: "no-preference" });
    await liveCity(live, 3); // the control: this page does move
    await live.context().close();

    const page = await openHome(browser, baseURL, { reducedMotion: "reduce", frames: true });
    const m = await sample(page);
    expect(m.moving, "city elements moving under reduced motion").toBe(0);
    expect(m.running, "animations running under reduced motion").toBe(0);
    expect(await frames(page, 500), "frame loop running under reduced motion").toBe(0);
    const pictures = await page.evaluate(
      (sel) =>
        [...document.querySelectorAll(`${sel} img`)].filter(
          (i) => i.getBoundingClientRect().width > 0,
        ).length,
      BACKDROP,
    );
    expect(pictures, "the static frame is still drawn").toBeGreaterThan(0);
    await page.context().close();
  });
});

test.describe("WEB-MOTION-1 performance budget", () => {
  test("WEB-MOTION-1 e2e: at 390x844 with the CPU slowed 4x, the idle city causes no long task over 50 ms", async ({
    browser,
    baseURL,
  }) => {
    test.setTimeout(90_000);
    const page = await openHome(browser, baseURL, { viewport: MOBILE });
    await liveCity(page, 1); // the city is moving before the measurement
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await page.waitForTimeout(500);
    const supported = await page.evaluate(() =>
      PerformanceObserver.supportedEntryTypes.includes("longtask"),
    );
    expect(supported, "the browser must report long tasks").toBe(true);
    const long = await page.evaluate(
      (ms) =>
        new Promise<number[]>((done) => {
          const seen: number[] = [];
          const po = new PerformanceObserver((list) => {
            for (const e of list.getEntries()) seen.push(e.duration);
          });
          po.observe({ type: "longtask" });
          setTimeout(() => {
            for (const e of po.takeRecords()) seen.push(e.duration);
            po.disconnect();
            done(seen);
          }, ms);
        }),
      4_000,
    );
    const stillMoving = await sample(page, 400);
    expect(stillMoving.moving, "the city must still be moving at the end").toBeGreaterThanOrEqual(
      1,
    );
    expect(
      long.filter((d) => d > 50),
      "long tasks (ms) during idle city motion",
    ).toEqual([]);
    await page.context().close();
  });

  for (const [name, viewport] of [
    ["1440", DESKTOP],
    ["390", MOBILE],
  ] as const) {
    test(`WEB-MOTION-1 e2e: at ${name} only transform and opacity change over time (nothing that lays out or repaints)`, async ({
      browser,
      baseURL,
    }) => {
      const page = await openHome(browser, baseURL, { viewport });
      await liveCity(page, 1);
      const report = await page.evaluate(
        async ({ sel, ms }) => {
          const root = document.querySelector(sel) as Element;
          const els = [root, ...root.querySelectorAll("*")];
          // What the browser says is running: every keyframe property must be transform or opacity.
          const META = new Set(["offset", "easing", "composite", "computedOffset"]);
          const keyframeProps = new Set<string>();
          for (const a of document.getAnimations()) {
            if (a.playState !== "running" || !(a.effect instanceof KeyframeEffect)) continue;
            for (const f of a.effect.getKeyframes())
              for (const k of Object.keys(f)) if (!META.has(k)) keyframeProps.add(k);
          }
          // What a script-driven loop would change: any layout or paint property that differs between two samples.
          const WATCH = [
            "left",
            "top",
            "right",
            "bottom",
            "width",
            "height",
            "margin-left",
            "margin-top",
            "padding-left",
            "padding-top",
            "background-position",
            "background-color",
            "color",
            "filter",
            "box-shadow",
            "border-top-width",
            "clip-path",
            "font-size",
          ];
          const read = () =>
            els.map((e) => WATCH.map((p) => getComputedStyle(e).getPropertyValue(p)));
          const a = read();
          await new Promise((done) => setTimeout(done, ms));
          const b = read();
          const changed = new Set<string>();
          els.forEach((_, i) =>
            WATCH.forEach((p, j) => {
              if (a[i]?.[j] !== b[i]?.[j]) changed.add(p);
            }),
          );
          return { keyframeProps: [...keyframeProps].sort(), changed: [...changed].sort() };
        },
        { sel: BACKDROP, ms: SAMPLE_MS },
      );
      for (const p of report.keyframeProps)
        expect(["transform", "opacity"], `animated property ${p}`).toContain(p);
      expect(report.changed, "layout or paint properties changing over time").toEqual([]);
      await page.context().close();
    });
  }

  test("WEB-MOTION-1 e2e: no backdrop-filter on the city or on anything that moves or holds a mover", async ({
    browser,
    baseURL,
  }) => {
    const page = await openHome(browser, baseURL);
    await liveCity(page, 3);
    const offenders = await page.evaluate(
      async ({ sel, ms }) => {
        const root = document.querySelector(sel) as Element;
        const els = [...root.querySelectorAll("*")];
        const a = els.map((e) => e.getBoundingClientRect());
        await new Promise((done) => setTimeout(done, ms));
        const b = els.map((e) => e.getBoundingClientRect());
        const out: string[] = [];
        const blurred = (e: Element) => {
          const s = getComputedStyle(e);
          return (
            (s.backdropFilter && s.backdropFilter !== "none") ||
            ((s as unknown as Record<string, string>).webkitBackdropFilter ?? "none") !== "none"
          );
        };
        els.forEach((e, i) => {
          const moved =
            Math.hypot((b[i]?.left ?? 0) - (a[i]?.left ?? 0), (b[i]?.top ?? 0) - (a[i]?.top ?? 0)) >
            0.5;
          if (!moved) return;
          for (
            let n: Element | null = e;
            n && n !== document.documentElement;
            n = n.parentElement
          ) {
            if (blurred(n)) out.push(`${n.tagName}.${n.className}`);
          }
        });
        return [...new Set(out)];
      },
      { sel: BACKDROP, ms: SAMPLE_MS },
    );
    expect(offenders).toEqual([]);
    await page.context().close();
  });

  test("WEB-MOTION-1 e2e: the sprite count is capped under 768 px and on weak devices (cores <= 4 or memory <= 4 GB), and not otherwise", async ({
    browser,
    baseURL,
  }) => {
    test.setTimeout(120_000);
    const count = async (d: Device, min = 1): Promise<Motion> => {
      const page = await openHome(browser, baseURL, d);
      const m = await liveCity(page, min);
      const sized = await sample(page);
      await page.context().close();
      return {
        moving: Math.max(m.moving, sized.moving),
        travel: sized.travel,
        running: sized.running,
      };
    };
    const full = await count({ viewport: DESKTOP, cores: 8, memory: 8 }, 3);
    expect(full.moving).toBeGreaterThanOrEqual(3);

    const phone = await count({ viewport: { width: 767, height: 900 } });
    expect(phone.moving, "under 768 px: capped, not removed").toBeGreaterThanOrEqual(1);
    expect(phone.moving, "under 768 px: capped").toBeLessThan(full.moving);

    const edge = await count({ viewport: { width: 768, height: 1024 } }, 3);
    expect(edge.moving, "768 px is not under 768: no cap").toBeGreaterThanOrEqual(
      full.moving * 0.9,
    );

    const fourCores = await count({ viewport: DESKTOP, cores: 4, memory: 8 });
    expect(fourCores.travel, "4 cores or fewer: capped or calm (less motion)").toBeLessThan(
      full.travel * 0.9,
    );
    const fourGb = await count({ viewport: DESKTOP, cores: 8, memory: 4 });
    expect(fourGb.travel, "4 GB or less: capped or calm (less motion)").toBeLessThan(
      full.travel * 0.9,
    );

    const fiveCores = await count({ viewport: DESKTOP, cores: 5, memory: 8 }, 3);
    expect(fiveCores.moving, "5 cores is not weak: no cap").toBeGreaterThanOrEqual(
      full.moving * 0.9,
    );
    expect(fiveCores.travel).toBeGreaterThanOrEqual(full.travel * 0.9);
  });
});

for (const [size, viewport] of [
  ["1440", DESKTOP],
  ["390", MOBILE],
] as const) {
  test.describe(`WEB-MOTION-1 every Park page at ${size}`, () => {
    test.use({ viewport });

    for (const path of PAGES) {
      test(`WEB-MOTION-1 e2e: /park/${path} at ${size} shifts nothing (CLS 0), has no sideways scroll and no console error`, async ({
        page,
      }) => {
        const problems = collectConsoleProblems(page);
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
        await page.goto(`/park/${path}`);
        await booted(page);
        // The city is alive on Home while the page is measured, so a layout shift caused by the motion is seen.
        if (path === "home") await liveCity(page, size === "390" ? 1 : 3);
        await page.waitForTimeout(1_500);
        const cls = await page.evaluate(() => {
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
        expect(cls, "cumulative layout shift").toBe(0);
        const width = await page.evaluate(() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
          bodyScroll: document.body.scrollWidth,
        }));
        expect(width.scroll, "sideways scroll").toBeLessThanOrEqual(width.client);
        expect(width.bodyScroll).toBeLessThanOrEqual(width.client);
        expect(problems).toEqual([]);
      });
    }
  });
}

test.describe("WEB-MOTION-1 console stays clean through a tour", () => {
  test.use({ viewport: MOBILE });

  test("WEB-MOTION-1 e2e: no console error or warning while the city runs, pauses on every page and resumes (390x844)", async ({
    page,
  }) => {
    test.setTimeout(90_000);
    const problems = collectConsoleProblems(page);
    await page.goto("/park/home");
    await booted(page);
    await liveCity(page, 1);
    for (const path of INNER) {
      await go(page, path);
      await page.waitForTimeout(250);
    }
    await go(page, "home");
    await liveCity(page, 1);
    await setHidden(page, true);
    await page.waitForTimeout(300);
    await setHidden(page, false);
    await page.waitForTimeout(500);
    expect(problems).toEqual([]);
  });
});
