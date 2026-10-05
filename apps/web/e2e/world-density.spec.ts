// FR-WLD-14: Professional density draws the same world differently (smaller characters, every tag
// carries its recorded state) and changes nothing else: same run position, no console output, no
// layout shift. The unit test (src/world/density.stage.test.ts) pins what changes on a live switch.
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";
import { fixtureUrl, stageFrame } from "./support/world";

async function openStage(page: Page, mode: "friendly" | "professional") {
  await page.addInitScript((m) => {
    window.localStorage.setItem("tilo.density", m);
    const w = window as unknown as { __shifts: number[] };
    w.__shifts = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries())
        w.__shifts.push((entry as unknown as { value: number }).value);
    }).observe({ type: "layout-shift", buffered: true });
  }, mode);
  await page.goto(fixtureUrl("village-basic", { seq: 44 }));
  await expect(stageFrame(page)).toHaveAttribute("data-stage-ready", "true");
  await expect(stageFrame(page)).toHaveAttribute("data-seq", "44");
  await expect(page.locator("html")).toHaveAttribute("data-density", mode);
  // The canvas is drawn on demand (HR-2): two shots in a row agree once the frame is on it.
  let last = "";
  await expect
    .poll(async () => {
      const shot = (await stageFrame(page).locator("canvas").screenshot()).toString("base64");
      const same = shot === last;
      last = shot;
      return same;
    })
    .toBe(true);
  return last;
}

test("FR-WLD-14: Professional draws the same run at the same seq, differently, with nothing logged and no shift", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize(DESKTOP);
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(m.text());
  });
  const friendly = await openStage(page, "friendly");
  const friendlyShifts = await page.evaluate(
    () => (window as unknown as { __shifts: number[] }).__shifts,
  );
  const professional = await openStage(page, "professional");
  const professionalShifts = await page.evaluate(
    () => (window as unknown as { __shifts: number[] }).__shifts,
  );
  expect(professional, "the canvas differs between the modes").not.toBe(friendly);
  expect(friendlyShifts).toEqual([]);
  expect(professionalShifts).toEqual([]);
  expect(problems).toEqual([]);
});

test("FR-WLD-14: Professional on a phone and in 1920 stage mode draws the same run with nothing logged and no shift", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(m.text());
  });
  const shifts = () => page.evaluate(() => (window as unknown as { __shifts: number[] }).__shifts);
  await page.setViewportSize(MOBILE);
  const phone = await openStage(page, "professional");
  expect(await shifts()).toEqual([]);
  // The tags that are too small to read there (state words, gate states, rank words) are not drawn.
  await page.setViewportSize({ width: 1920, height: 1080 });
  const wide = await openStage(page, "professional");
  expect(wide, "a full-size stage draws more than a phone's").not.toBe(phone);
  expect(await shifts()).toEqual([]);
  expect(problems).toEqual([]);
});
