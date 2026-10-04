import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { type Page, expect, test } from "@playwright/test";
import { watchConsole } from "./support/screens";
import { DESKTOP, MOBILE } from "./support/viewports";
import { canvasSnapshot, fixtureUrl, speedBadge, stageSeq } from "./support/world";

// FR-WLD-08 (PRD 9.4 HR-4/HR-6, 9.6, 9.7): replay and scrub of a finished run, replay banner always
// visible. Acceptance: "scrub to any point in <= 500 ms for runs <= 5,000 events".
//
// DOM contract (this ticket):
//   [data-testid="replay-scrubber"]  the Replay region (aria-label "Replay"), on every world route
//                                    (World, Story, Trace, Inspect, Delivery) and in fixture mode;
//                                    right rail on desktop, in the column above the tabs on mobile.
//   role=slider "Replay position"    one stop per event, index 0 = before the first event; native
//                                    keys (arrows, Home, End); aria-valuetext "Event i of N, seq s,
//                                    m:ss into the run: <type>". Disabled while the run is live.
//   buttons "Previous event" / "Next event".
//   [data-testid="scrub-reason"]     why the scrubber is disabled (the run is still going).
//   [data-testid="replay-banner"]    "Replay of run #<run id> recorded <date>" (HR-4), role=status,
//                                    present whenever the run has finished; fixtures add
//                                    " · dev fixture, not a real run" (BQ-07).
// Scrubbing sets the world to stateAt(seq): stage data-seq follows, Story and Trace show the
// events up to that point. Nothing animates (jumps are instant, labelled as replay).

const CONTRACTS = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../../contracts");
const LAYOUT = fs.readFileSync(
  path.join(CONTRACTS, "fixtures/layout/valid/village_basic.json"),
  "utf8",
);
const BASE_EVENT = JSON.parse(
  fs
    .readFileSync(path.join(CONTRACTS, "fixtures/streams/village-basic.jsonl"), "utf8")
    .split("\n")[0] as string,
) as Record<string, unknown>;
const AGENTS = ["A_dir", "A_l1", "A_s1", "A_s2", "A_v1"];
const BUILDINGS = ["B1", "B2", "B3", "B4", "B5"];
const BIG = 5_000;

const scrubber = (page: Page) => page.getByTestId("replay-scrubber");
const slider = (page: Page) => scrubber(page).getByRole("slider", { name: "Replay position" });
const banner = (page: Page) => page.getByTestId("replay-banner");
const BANNER_TEXT_PAUSE = /^Replay of run #r_crowd_6_1 recorded 29 Sep 2026/;
const BANNER_TEXT = /^Replay of run #r_village_basic_1 recorded 29 Sep 2026/;

test("FR-WLD-08 a live run cannot be scrubbed: the control is disabled and says why", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(fixtureUrl("village-basic")); // plays in real time, nothing applied yet
  await expect(slider(page)).toBeDisabled();
  await expect(page.getByTestId("scrub-reason")).toContainText(/finished/i);
  await expect(banner(page)).toHaveCount(0);
});

for (const [name, viewport, extra] of [
  ["desktop", DESKTOP, {}],
  ["mobile", MOBILE, {}],
  ["stage", { width: 1920, height: 1080 }, { display: "stage" }],
] as const) {
  test(`FR-WLD-08 HR-4 the replay banner is visible, uncovered and not dismissable at ${name} size`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(fixtureUrl("village-basic", { seq: 10, ...extra }));
    await expect(banner(page)).toHaveText(BANNER_TEXT);
    await slider(page).focus();
    await page.keyboard.press("End");
    await expect.poll(() => stageSeq(page)).toBe(44);
    await expect(banner(page)).toBeVisible();
    const box = await banner(page).boundingBox();
    expect(box?.width).toBeGreaterThan(0);
    const onTop = await page.evaluate(
      ({ x, y }) => {
        const el = document.elementFromPoint(x, y);
        return !!el?.closest('[data-testid="replay-banner"]');
      },
      { x: (box?.x ?? 0) + 4, y: (box?.y ?? 0) + (box?.height ?? 0) / 2 },
    );
    expect(onTop, "something is painted over the replay banner").toBe(true);
    const role = await banner(page).getAttribute("role");
    expect(role).toBe("status");
  });
}

test("FR-WLD-08 keyboard and buttons move the world to stateAt(seq), labelled with seq and time", async ({
  page,
}) => {
  const problems = watchConsole(page);
  await page.setViewportSize(DESKTOP);
  await page.goto(fixtureUrl("village-basic", { seq: 10 }));
  await expect(slider(page)).toBeEnabled();
  await expect(slider(page)).toHaveAttribute("aria-valuetext", /Event 10 of 44, seq 10, 0:\d\d/);
  await slider(page).focus();
  await page.keyboard.press("Home");
  await expect.poll(() => stageSeq(page)).toBe(0);
  await expect(slider(page)).toHaveAttribute("aria-valuetext", /before the first event/);
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => stageSeq(page)).toBe(1);
  await scrubber(page).getByRole("button", { name: "Next event" }).click();
  await expect.poll(() => stageSeq(page)).toBe(2);
  await scrubber(page).getByRole("button", { name: "Previous event" }).click();
  await expect.poll(() => stageSeq(page)).toBe(1);
  await slider(page).focus();
  await page.keyboard.press("End");
  await expect.poll(() => stageSeq(page)).toBe(44);
  await expect(scrubber(page).getByRole("button", { name: "Next event" })).toBeDisabled();
  expect(problems.filter((p) => !/adblock|extension/i.test(p))).toEqual([]);
});

test("FR-WLD-08 a scrubbed frame is the frame a direct ?seq= load draws (deterministic)", async ({
  page,
  context,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(fixtureUrl("village-basic", { seq: 44 }));
  await slider(page).fill("20");
  await expect.poll(() => stageSeq(page)).toBe(20);
  const direct = await context.newPage();
  await direct.setViewportSize(DESKTOP);
  await direct.goto(fixtureUrl("village-basic", { seq: 20 }));
  await expect.poll(() => stageSeq(direct)).toBe(20);
  expect(await canvasSnapshot(page)).toBe(await canvasSnapshot(direct));
});

test("FR-WLD-08 a run that played out live can then be scrubbed, and the banner appears with the end", async ({
  page,
  context,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(fixtureUrl("village-basic", { speed: 100 }));
  await expect(banner(page)).toHaveCount(0); // live: no replay banner, scrubber disabled
  await expect(slider(page)).toBeEnabled({ timeout: 15_000 });
  await expect(banner(page)).toHaveText(BANNER_TEXT);
  await expect.poll(() => stageSeq(page)).toBe(44);
  await slider(page).fill("20");
  await expect.poll(() => stageSeq(page)).toBe(20);
  await expect(banner(page)).toHaveText(BANNER_TEXT);
  const direct = await context.newPage();
  await direct.setViewportSize(DESKTOP);
  await direct.goto(fixtureUrl("village-basic", { seq: 20 }));
  await expect.poll(() => stageSeq(direct)).toBe(20);
  expect(await canvasSnapshot(page)).toBe(await canvasSnapshot(direct));
});

test("FR-WLD-08 HR-6 the speed badge stays while scrubbing a replay at another speed", async ({
  page,
}) => {
  await page.setViewportSize(DESKTOP);
  await page.goto(fixtureUrl("village-basic", { seq: 10, speed: 20 }));
  await slider(page).fill("5");
  await expect.poll(() => stageSeq(page)).toBe(5);
  await expect(speedBadge(page)).toContainText("Replay at 20× speed");
  await expect(banner(page)).toHaveText(BANNER_TEXT);
});

for (const viewport of [DESKTOP, MOBILE]) {
  test(`FR-WLD-08 Story and Trace show the run up to the scrub point, no layout shift, at ${viewport.width}px`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.setViewportSize(viewport);
    await page.addInitScript(() => {
      const w = window as unknown as { __shifts: number[] };
      w.__shifts = [];
      new PerformanceObserver((list) => {
        for (const e of list.getEntries())
          w.__shifts.push((e as unknown as { value: number }).value);
      }).observe({ type: "layout-shift", buffered: true });
    });
    await page.goto("/world/w_village_basic/trace?speed=25");
    await expect(slider(page)).toBeDisabled(); // still running
    const live = await scrubber(page).boundingBox();
    await expect(slider(page)).toBeEnabled({ timeout: 40_000 }); // finished
    await expect(banner(page)).toHaveText(BANNER_TEXT);
    const done = await scrubber(page).boundingBox();
    expect(done?.height, "the region is the same box live and finished").toBe(live?.height);
    await slider(page).fill("12");
    await expect(page.getByTestId("trace-lens-row")).toHaveCount(12);
    await page
      .getByRole("navigation", { name: "Lens" })
      .getByRole("link", { name: "Story" })
      .click();
    const seqs = await page
      .locator(".story-list li")
      .evaluateAll((els) => els.map((el) => Number(el.getAttribute("data-seq"))));
    expect(seqs.length).toBeGreaterThan(0);
    expect(Math.max(...seqs)).toBeLessThanOrEqual(12);
    await expect(slider(page)).toHaveAttribute("aria-valuetext", /Event 12 of 44/);
    await slider(page).fill("44");
    await expect(page.locator(".story-list li")).toHaveCount(44);
    const shifts = await page.evaluate(
      () => (window as unknown as { __shifts: number[] }).__shifts,
    );
    expect(shifts).toEqual([]);
  });
}

test("FR-WLD-08 targets are at least 24 px on desktop and 44 px on mobile", async ({ page }) => {
  for (const [viewport, min] of [
    [DESKTOP, 24],
    [MOBILE, 44],
  ] as const) {
    await page.setViewportSize(viewport);
    await page.goto(fixtureUrl("village-basic", { seq: 10 }));
    await expect(slider(page)).toBeEnabled();
    for (const target of [slider(page), scrubber(page).getByRole("button")]) {
      for (const box of await target.evaluateAll((els) =>
        els.map((el) => el.getBoundingClientRect().toJSON()),
      )) {
        expect(box.height, `${viewport.width}px target`).toBeGreaterThanOrEqual(min);
        expect(box.width).toBeGreaterThanOrEqual(min);
      }
    }
  }
});

test(`FR-WLD-08 perf: scrub a ${BIG}-event run to any point in <= 500 ms`, async ({ page }) => {
  test.setTimeout(60_000);
  const events = Array.from({ length: BIG }, (_, i) =>
    JSON.stringify({
      ...BASE_EVENT,
      id: `01JB5VQ${String(i + 1).padStart(19, "0")}`,
      seq: i + 1,
      ts: new Date(Date.UTC(2026, 8, 29, 9, 30, 0) + i * 1000).toISOString(),
      type: i % 2 === 0 ? "agent.working" : "agent.moved",
      actor: AGENTS[i % AGENTS.length],
      target: BUILDINGS[i % BUILDINGS.length],
    }),
  ).join("\n");
  await page.route("**/fixtures/scrub-5000.layout.json", (r) =>
    r.fulfill({ contentType: "application/json", body: LAYOUT }),
  );
  await page.route("**/fixtures/scrub-5000.events.jsonl", (r) =>
    r.fulfill({ contentType: "text/plain", body: events }),
  );
  await page.setViewportSize(DESKTOP);
  await page.goto(fixtureUrl("scrub-5000", { seq: BIG }));
  await expect.poll(() => stageSeq(page), { timeout: 20_000 }).toBe(BIG);
  await expect(slider(page)).toBeEnabled();
  // The slowest jump first: from the start to the end, with the whole Trace list to build.
  const jumps = [0, 4_999, 2_500, 1, 3_333, BIG];
  const measured: string[] = [];
  for (const target of jumps) {
    const ms = await page.evaluate(async (to) => {
      const input = document.querySelector<HTMLInputElement>(
        '[data-testid="replay-scrubber"] input[type="range"]',
      );
      const frame = document.querySelector('[data-testid="stage-frame"]');
      if (!input || !frame) throw new Error("scrubber or stage missing");
      const t0 = performance.now();
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      set?.call(input, String(to));
      input.dispatchEvent(new Event("input", { bubbles: true }));
      while (frame.getAttribute("data-seq") !== String(to)) {
        await new Promise((resolve) => requestAnimationFrame(resolve));
        if (performance.now() - t0 > 5_000) throw new Error(`never reached seq ${to}`);
      }
      return performance.now() - t0;
    }, target);
    measured.push(`${target}: ${ms.toFixed(0)} ms`);
    expect(ms, `scrub to ${target} took ${ms.toFixed(0)} ms`).toBeLessThanOrEqual(500);
  }
  test.info().annotations.push({ type: "scrub ms", description: measured.join(", ") });
  console.log(`SCRUB MS ${measured.join(", ")}`);
});

// FR-WLD-07 + FR-WLD-08: pause-6 records world.paused at seq 24 with 15 stragglers after it, so it
// ends paused. Once finished it can be scrubbed; the veil follows the recorded status at the scrub
// point (HR-1), and the veil (in the stage) and the replay banner (in the rail or the column below
// the stage) are both visible and never cover each other.
for (const viewport of [DESKTOP, MOBILE]) {
  test(`FR-WLD-08 a finished paused run scrubs; veil and replay banner both stay visible at ${viewport.width}px`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    const problems = watchConsole(page);
    await page.setViewportSize(viewport);
    await page.goto(fixtureUrl("pause-6", { speed: 100 }));
    await expect(slider(page)).toBeEnabled({ timeout: 20_000 });
    await expect.poll(() => stageSeq(page)).toBe(39);
    const veil = page.getByTestId("world-veil");
    await expect(veil).toBeVisible();
    await expect(banner(page)).toBeVisible();
    const apart = async () => {
      const [v, b] = await Promise.all([veil.boundingBox(), banner(page).boundingBox()]);
      expect(v && b, "veil and banner both have a box").toBeTruthy();
      if (!v || !b) return;
      const overlap =
        v.x < b.x + b.width && b.x < v.x + v.width && v.y < b.y + b.height && b.y < v.y + v.height;
      expect(overlap, "the veil covers the replay banner").toBe(false);
    };
    await apart();
    await slider(page).fill("10"); // before world.paused: the record had no pause yet
    await expect.poll(() => stageSeq(page)).toBe(10);
    await expect(veil).toHaveCount(0);
    await expect(banner(page)).toBeVisible();
    await slider(page).fill("30"); // after it: paused again
    await expect.poll(() => stageSeq(page)).toBe(30);
    await expect(veil).toBeVisible();
    await expect(banner(page)).toHaveText(BANNER_TEXT_PAUSE);
    await apart();
    expect(problems.filter((p) => !/adblock|extension/i.test(p))).toEqual([]);
  });
}

test("FR-WLD-08 an empty run opened at ?seq=0 says there is nothing to replay, not that it is still going", async ({
  page,
}) => {
  await page.route("**/fixtures/scrub-empty.layout.json", (r) =>
    r.fulfill({ contentType: "application/json", body: LAYOUT }),
  );
  await page.route("**/fixtures/scrub-empty.events.jsonl", (r) =>
    r.fulfill({ contentType: "text/plain", body: "" }),
  );
  await page.setViewportSize(DESKTOP);
  await page.goto(fixtureUrl("scrub-empty", { seq: 0 }));
  await expect(page.getByTestId("scrub-reason")).toContainText(/no events/i);
  await expect(page.getByTestId("scrub-reason")).not.toContainText(/still going/i);
  await expect(slider(page)).toBeDisabled();
});
