// FR-PA-12 / FR-PA-18 (docs/prd-addendum-people-agents.md): the assistant panel shell on the screens
// of the app, at 1440x900 and 390x844. It opens with the right context chip, causes no layout shift,
// traps focus and gives it back, keeps its open state for the session, and passes axe.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { DESKTOP, MOBILE } from "./support/viewports";

// WEB-CUTOVER: "/", "/worlds" and "/team" are Park pages now (they have no assistant panel); the old
// Start row is removed with the replaced S-01 screen, S-18 moved to /team/console, and OLD-UI-OUT 3 moved the Library and Worlds replays to Park.
const SCREENS = [
  ["/task/task_fixture_1/understanding", "Understanding"],
  ["/task/task_fixture_1/approaches", "Approaches"],
  ["/world/w_village_basic/stage", "World"],
  ["/needs-you", "Needs-you queue"],
  ["/channels", "Channels"],
  ["/settings", "Settings"],
] as const;

async function watchShifts(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __shifts: number[] };
    w.__shifts = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        const s = e as unknown as { value: number; hadRecentInput: boolean };
        if (!s.hadRecentInput) w.__shifts.push(s.value);
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
}
const shifts = (page: Page) =>
  page.evaluate(() => (window as unknown as { __shifts: number[] }).__shifts);

for (const viewport of [DESKTOP, MOBILE]) {
  const at = `${viewport.width}x${viewport.height}`;
  for (const [path, label] of SCREENS) {
    test(`FR-PA-12 ${path} at ${at}: opens with the context chip, no shift, focus trapped and restored`, async ({
      page,
    }) => {
      test.setTimeout(90_000);
      await page.setViewportSize(viewport);
      await watchShifts(page);
      await page.goto(`${path}${path.startsWith("/world/") ? "?speed=1000" : ""}`);
      const open = page.getByTestId("assistant-open");
      await expect(open).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(500);
      const before = (await shifts(page)).length;

      await open.click();
      const dialog = page.getByRole("dialog", { name: "Assistant" });
      await expect(dialog).toBeVisible();
      await expect(page.getByTestId("assistant-context")).toContainText(`You are on: ${label}`);
      await expect(dialog.locator("input")).toBeFocused();

      // Focus stays inside the panel however far Tab is pressed.
      for (let i = 0; i < 6; i++) {
        await page.keyboard.press("Tab");
        expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
      }
      await page.keyboard.press("Shift+Tab");
      expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);

      await page.keyboard.press("Escape");
      await expect(dialog).toHaveCount(0);
      await expect(open).toBeFocused();
      expect((await shifts(page)).length).toBe(before); // opening and closing moved nothing
    });
  }

  test(`FR-PA-12 at ${at}: the launcher's box covers no button, link or input on any screen, and the panel is modal`, async ({
    page,
  }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(viewport);
    const paths = [
      ...SCREENS.map(([p]) => p),
      "/no-such-page",
      "/more",
      "/estimate",
      "/team/console",
      "/pilot",
      "/needs-you/gate",
      "/world/w_village_basic/story",
      "/world/w_village_basic/trace",
      "/world/w_village_basic/delivery",
      "/world/w_village_basic/inspect/B1",
    ];
    for (const path of paths) {
      await page.goto(`${path}${path.startsWith("/world/") ? "?speed=1000" : ""}`);
      const launcher = page.getByTestId("assistant-open");
      await expect(launcher).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(300);
      const covered = await launcher.evaluate((el) => {
        const me = el.getBoundingClientRect();
        const hit: string[] = [];
        for (const other of document.querySelectorAll(
          "button, a[href], input, select, textarea, summary, [role='button']",
        )) {
          if (other === el || el.contains(other)) continue;
          const r = other.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) continue; // not displayed
          const w = Math.min(me.right, r.right) - Math.max(me.left, r.left);
          const h = Math.min(me.bottom, r.bottom) - Math.max(me.top, r.top);
          if (w <= 0.5 || h <= 0.5) continue;
          // Content scrolled out of its own clipped region is not on screen there: only an element
          // that is painted at the overlap counts.
          const x = Math.max(me.left, r.left) + w / 2;
          const y = Math.max(me.top, r.top) + h / 2;
          if (document.elementsFromPoint(x, y).some((e) => other.contains(e))) {
            hit.push(`${other.tagName} ${(other.textContent ?? "").trim()}`);
          }
        }
        return hit;
      });
      expect(covered, `${path} at ${at}`).toEqual([]);
    }
    await page.getByTestId("assistant-open").click();
    const dialog = page.getByRole("dialog", { name: "Assistant" });
    expect(await dialog.evaluate((el) => el.matches(":modal"))).toBe(true);
  });

  test(`FR-PA-18 at ${at}: axe clean with the panel open, the answer is a preview notice, the open state persists`, async ({
    page,
  }) => {
    test.setTimeout(90_000);
    await page.setViewportSize(viewport);
    await page.goto("/autonomy");
    await page.getByTestId("assistant-open").click();
    const dialog = page.getByRole("dialog", { name: "Assistant" });
    await dialog.getByLabel("Ask Tilo").fill("What is on my plate?");
    await dialog.getByRole("button", { name: "Send" }).click();
    await expect(dialog.getByRole("log")).toContainText("What is on my plate?");
    await expect(dialog.getByRole("log")).toContainText("not connected");
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag22aa"])
      .analyze();
    expect(results.violations.map((v) => `${v.id}: ${v.nodes[0]?.target}`)).toEqual([]);
    await page.reload();
    await expect(page.getByRole("dialog", { name: "Assistant" })).toBeVisible();
  });
}
