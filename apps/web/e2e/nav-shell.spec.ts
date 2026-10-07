// Issue #227 Bundle C (shell and global hierarchy): the primary nav (C1, C4), the reserved strip for
// the dev "Fixture replay" pill (C2), one right-rail contract (C3), the button hierarchy (C5) and
// the Inspect hint (C6), at 1440x900, 390x844 and 320x640, in normal and stage mode (?display=stage).
import { type Page, expect, test } from "@playwright/test";
import { readShifts, watchShifts } from "./support/shifts";
import { DESKTOP, MOBILE } from "./support/viewports";

const SMALL = { width: 320, height: 640 } as const;
const VIEWPORTS = [DESKTOP, MOBILE, SMALL] as const;
const W = "/world/w_village_basic";
// WEB-CUTOVER: "/" is the Park Home (its own shell), so the old flow shell's "start of the flow" is S-02.
const FLOW = "/task/task_fixture_1/understanding";

type Rect = { x: number; y: number; width: number; height: number };
const overlaps = (a: Rect, b: Rect) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

// C4: the active item matches the route. "none" is the phone's Home (no tab for it).
const ACTIVE: ReadonlyArray<readonly [string, string]> = [
  [FLOW, "Home"],
  [`${W}/stage`, "World"],
  [`${W}/story`, "Story"],
  [`${W}/trace`, "Story"],
  [`${W}/delivery`, "World"],
  ["/worlds/replays", "World"],
  ["/needs-you", "Needs you"],
  ["/library", "Library"],
  ["/settings", "More"],
  ["/autonomy", "More"],
];

for (const [path, label] of ACTIVE) {
  test(`UX-227-C4 ${path} marks "${label}" current (aria-current) and nothing else`, async ({
    page,
  }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto(path);
    const nav = page.getByRole("navigation", { name: /primary/i });
    await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
    await expect(nav.getByRole("link", { name: new RegExp(`^${label}`) })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
}

for (const viewport of VIEWPORTS) {
  for (const display of ["", "&display=stage"]) {
    const where = `${viewport.width}x${viewport.height}${display}`;
    const phone = viewport.width < 768;

    test(`UX-227-C1 nav labels sit on one line, at the type step, in targets of the size WCAG asks at ${where}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.goto(`/needs-you?speed=20${display}`);
      const nav = page.getByRole("navigation", { name: /primary/i });
      const links = nav.getByRole("link");
      const count = await links.count();
      expect(count).toBe(phone ? 5 : 6);
      for (let i = 0; i < count; i++) {
        const link = links.nth(i);
        const info = await link.evaluate((el) => {
          const label = el.querySelector(".nav-label") as HTMLElement;
          const r = el.getBoundingClientRect();
          const lr = label.getBoundingClientRect();
          return {
            text: label.textContent,
            fits: label.scrollWidth <= Math.ceil(lr.width) && lr.right <= r.right + 0.5,
            lines: Math.round(lr.height / Number.parseFloat(getComputedStyle(label).lineHeight)),
            px: Number.parseFloat(getComputedStyle(label).fontSize),
            w: r.width,
            h: r.height,
            hasIcon: !!el.querySelector("svg.nav-icon"),
          };
        });
        const scale = display && !phone ? 1.25 : 1; // the tabs share the phone's width: no scaling
        expect(info.hasIcon, `${info.text} has an icon`).toBe(true);
        expect(info.fits, `${info.text} fits its link`).toBe(true);
        expect(info.lines, `${info.text} is one line`).toBe(1);
        expect(info.px, `${info.text} label size`).toBeCloseTo((phone ? 12 : 14) * scale, 1);
        expect(info.w).toBeGreaterThanOrEqual(phone ? 44 : 24);
        expect(info.h).toBeGreaterThanOrEqual(phone ? 44 : 24);
      }
    });

    test(`UX-227-C2 the dev pill sits in a reserved strip and covers no control at ${where}`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      for (const path of [FLOW, "/worlds/replays", "/needs-you", `${W}/story`]) {
        await page.goto(`${path}${path.includes("?") ? "&" : "?"}speed=20${display}`);
        const pill = page.getByTestId("fixture-replay-banner");
        const badge = page.getByTestId("speed-badge");
        await expect(pill).toBeVisible();
        const strip = (await page.locator(".status-strip").boundingBox()) as Rect;
        const shell = (await page
          .locator(phone ? ".screen-page, .stage-frame" : ".left-rail")
          .first()
          .boundingBox()) as Rect;
        const p = (await pill.boundingBox()) as Rect;
        expect(p.y).toBeGreaterThanOrEqual(strip.y);
        expect(p.y + p.height).toBeLessThanOrEqual(strip.y + strip.height);
        expect(p.x + p.width).toBeLessThanOrEqual(viewport.width);
        const boxes = [p];
        if (path !== FLOW) {
          // The flow screens show no replayed run, so it has no speed badge (HR-6).
          await expect(badge).toBeVisible();
          const b = (await badge.boundingBox()) as Rect;
          expect(b.y + b.height).toBeLessThanOrEqual(strip.y + strip.height);
          expect(overlaps(p, b), "pill and badge overlap").toBe(false);
          boxes.push(b);
        }
        expect(shell.y, "the shell starts below the strip").toBeGreaterThanOrEqual(
          strip.y + strip.height - 0.5,
        );
        if (path === FLOW) {
          const card = (await page.getByTestId("flow-shell").boundingBox()) as Rect;
          expect(card.y, "the flow card starts below the strip").toBeGreaterThanOrEqual(
            strip.y + strip.height - 0.5,
          );
        }
        const hits = await overlappingControls(page, boxes);
        expect(hits, `controls under the pill on ${path}`).toEqual([]);
      }
    });
  }
}

async function overlappingControls(page: Page, boxes: Rect[]): Promise<string[]> {
  return page.evaluate((rects) => {
    const out: string[] = [];
    for (const el of document.querySelectorAll("a, button, input, select, textarea, summary")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      for (const q of rects) {
        if (r.left < q.x + q.width && q.x < r.right && r.top < q.y + q.height && q.y < r.bottom) {
          out.push(`${el.tagName} ${(el.textContent ?? "").trim().slice(0, 30)}`);
        }
      }
    }
    return out;
  }, boxes);
}

for (const viewport of VIEWPORTS) {
  for (const display of ["", "&display=stage"]) {
    test(`UX-227-C zero layout shift on the shell routes at ${viewport.width}x${viewport.height}${display}`, async ({
      page,
    }) => {
      test.setTimeout(60_000);
      await page.setViewportSize(viewport);
      await watchShifts(page);
      for (const path of [FLOW, "/worlds/replays", "/library?speed=50"]) {
        await page.goto(`${path}${path.includes("?") ? "&" : "?"}x=1${display}`);
        await expect(page.getByRole("navigation", { name: /primary/i })).toBeVisible();
        expect(await readShifts(page), path).toEqual([]);
      }
    });
  }
}

test("UX-227-C1 the Needs-you badge counts the queue S-06 lists, and is absent at zero", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  await page.goto("/needs-you?speed=5", { waitUntil: "commit" }); // the replay starts at mount
  const link = page.getByRole("navigation", { name: /primary/i }).getByRole("link", {
    name: /^Needs you/,
  });
  await expect(page.getByTestId("nav-needs-badge")).toHaveCount(0); // nothing waits yet (HR-1)
  const rows = page.getByTestId("needs-queue").locator("li");
  await expect(rows).toHaveCount(1, { timeout: 30_000 });
  await expect(page.getByTestId("nav-needs-badge")).toHaveText("1 waiting");
  await expect(link).toHaveAccessibleName("Needs you 1 waiting");
  await expect(page.getByTestId("nav-needs-badge")).toHaveCount(0, { timeout: 30_000 }); // answered
});

test("UX-227-C3 every route has the same right rail: card, Needs you, Team; links are 24 px", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  for (const path of [
    FLOW,
    "/worlds/replays",
    "/needs-you",
    "/settings",
    `${W}/story`,
    `${W}/delivery`,
  ]) {
    await page.goto(`${path}?speed=1000`);
    const rail = page.getByTestId("right-rail");
    await expect(rail.getByRole("region", { name: "Live meter" }), path).toBeVisible();
    await expect(rail.getByRole("heading", { level: 2, name: "Needs you" }), path).toBeVisible();
    await expect(rail.getByRole("heading", { level: 2, name: "Team" }), path).toBeVisible();
    const small = await rail.evaluate((el) =>
      [...el.querySelectorAll("a, button")]
        .map((a) => a.getBoundingClientRect())
        .filter((r) => r.width > 0 && (r.width < 24 || r.height < 24))
        .map((r) => `${Math.round(r.width)}x${Math.round(r.height)}`),
    );
    expect(small, `rail targets under 24x24 on ${path}`).toEqual([]);
    // The card never claims "0 credits" for a run that has not started (and a finished run says Done).
    const text = await rail.getByRole("region", { name: "Live meter" }).innerText();
    expect(text, path).not.toMatch(/Getting ready[\s\S]*\b0\b[\s\S]*credits/);
  }
});

test("UX-227-C5 one filled primary: iris with a lip; the secondary is quiet (1 px line plus lip)", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(FLOW);
  const primary = page.locator("button.primary");
  await expect(primary).toHaveCount(1);
  const look = await primary.evaluate((el) => {
    const s = getComputedStyle(el);
    return {
      bg: s.backgroundColor,
      lip: s.borderBottomWidth,
      disabled: (el as HTMLButtonElement).disabled,
    };
  });
  expect(look.lip).toBe("4px");
  expect(look.bg, "a disabled primary is still iris, not grey").not.toBe("rgb(233, 231, 225)");
  for (const el of await page.locator(".secondary:visible").all()) {
    const s = await el.evaluate((n) => {
      const c = getComputedStyle(n);
      return { top: c.borderTopWidth, bottom: c.borderBottomWidth };
    });
    expect(s.top, "no 2 px outline").not.toBe("2px");
  }
});

test("UX-227-C6 the lens screens show the Inspect hint, not 'Nothing selected'", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  for (const lens of ["story", "trace"]) {
    await page.goto(`${W}/${lens}`);
    const bar = page.getByTestId("selection-bar");
    await expect(bar).toContainText("Choose anything to inspect it");
    await expect(page.locator("body")).not.toContainText("Nothing selected");
  }
});
