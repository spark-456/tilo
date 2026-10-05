// PPL-40b / FR-PB-08, FR-CAL-01: S-28 Pinboards and S-29 Calendar on fixtures, at 1440x900 and
// 390x844: they render, the console stays quiet, axe WCAG 2.2 AA is clean, nothing shifts, nothing
// scrolls sideways, the targets are big enough, and everything works from the keyboard.
import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";
import { collectConsoleProblems } from "./support/console";
import { DESKTOP, MOBILE } from "./support/viewports";

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
const sideways = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

async function clean(page: Page, min: number) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  const small = await page.locator("main a, main button, main summary").evaluateAll(
    (els, side) =>
      els.flatMap((el) => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return []; // not shown (the other tab)
        return r.width < side || r.height < side
          ? [`${el.textContent?.trim()} ${r.width}x${r.height}`]
          : [];
      }),
    min,
  );
  expect(small).toEqual([]);
  expect(await sideways(page)).toBeLessThanOrEqual(0);
}

for (const [name, viewport] of Object.entries({ desktop: DESKTOP, mobile: MOBILE })) {
  const min = name === "mobile" ? 44 : 24;
  test.describe(`PPL-40b people screens at ${name}`, () => {
    test.use({ viewport });

    test("PPL-40b S-28: both boards render, one tab at a time on a phone, with nothing hidden shown", async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await watchShifts(page);
      await page.goto("/pinboards");
      await expect(page.getByTestId("people-preview")).toContainText("Preview, not connected");
      await expect(page.getByTestId("team-pins")).toContainText("Rate sheet goes to Acme by 9 Oct");
      await expect(page.getByTestId("pins-unowned")).toContainText(
        "Offsite venue still to be chosen",
      );
      if (name === "mobile") {
        await expect(page.getByTestId("personal-pins")).toBeHidden();
        await page.getByRole("radio", { name: "Your board" }).check();
      }
      await expect(page.getByTestId("personal-pins")).toContainText("Follow up on the rate sheet");
      if (name === "desktop") await expect(page.getByTestId("team-pins")).toBeVisible();
      const text = await page.locator("main").innerText();
      for (const hidden of ["Draft the press note", "Old agenda", "Ask Dev about the venue"])
        expect(text).not.toContain(hidden);
      await expect(page.locator("button.primary")).toHaveCount(0);
      expect(problems, problems.join("\n")).toEqual([]);
      expect(await shifts(page)).toEqual([]);
      expect(await sideways(page)).toBeLessThanOrEqual(0);
    });

    test("PPL-40b S-28: sort, filter and Get in touch work from the keyboard, and nothing is sent", async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await watchShifts(page);
      await page.goto("/pinboards");
      const due = page.getByTestId("team-pins").getByRole("button", { name: "Due" });
      await due.focus();
      await page.keyboard.press("Enter");
      await expect(page.locator('th[aria-sort="ascending"]').first()).toContainText("Due");
      await page.keyboard.press("Enter");
      await expect(page.locator('th[aria-sort="descending"]').first()).toContainText("Due");
      await page.getByRole("radio", { name: /Deadlines/ }).focus();
      await page.keyboard.press("Space");
      await expect(page.getByTestId("team-pins")).toContainText("Acme rate hold runs out");
      await expect(page.getByTestId("team-pins")).not.toContainText("Launch is 17 October");
      await page.getByRole("radio", { name: /^All/ }).focus();
      await page.keyboard.press("Space");
      const touch = page.getByRole("button", {
        name: /^Get in touch with Priya Nair about Launch is 17/,
      });
      await touch.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByTestId("pin-draft")).toBeFocused();
      await expect(page.getByTestId("pin-draft")).toContainText(
        "Nothing is sent from this preview",
      );
      await expect(page.getByTestId("pin-draft")).toContainText("Draft to Priya Nair");
      await clean(page, min);
      expect(problems, problems.join("\n")).toEqual([]);
      expect(await shifts(page)).toEqual([]);
    });

    test("PPL-40b S-28: axe clean and targets at least the size, on a board with nothing in it", async ({
      page,
    }) => {
      await page.goto("/pinboards");
      await page.getByRole("radio", { name: /Links/ }).check();
      await expect(page.getByTestId("personal-empty")).toBeAttached();
      await clean(page, min);
    });

    test("PPL-40b S-29: the day agenda cites its sources, marks Tilo's proposal private, shows teammates as free/busy only", async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await watchShifts(page);
      await page.goto("/calendar");
      await expect(page.getByTestId("people-preview")).toContainText("Preview, not connected");
      const rows = page.getByTestId("agenda-row");
      await expect(rows).toHaveCount(4);
      await expect(rows.nth(0)).toContainText("Design review");
      await expect(rows.nth(3)).toContainText("Proposed, private to you");
      await expect(rows.nth(3).getByRole("button", { name: /Accept/ })).toHaveAttribute(
        "aria-disabled",
        "true",
      );
      await expect(page.getByTestId("free-busy")).toContainText("Priya Nair");
      await expect(page.getByTestId("free-busy")).toContainText("Busy 15:00 to 15:30");
      await expect(page.locator("main")).not.toContainText("Dentist");
      await clean(page, min);
      expect(problems, problems.join("\n")).toEqual([]);
      expect(await shifts(page)).toEqual([]);
    });

    test("PPL-40b S-29: the week is a stacked list with no sideways scroll, and the switch works from the keyboard", async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await watchShifts(page);
      await page.goto("/calendar");
      await page.getByRole("radio", { name: "Day" }).focus();
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("radio", { name: "Week" })).toBeChecked();
      await expect(page.locator('[data-testid^="day-"]')).toHaveCount(7);
      await expect(page.getByTestId("agenda-row").first()).toBeVisible();
      await expect(page.locator("main")).toContainText("Dentist"); // yours, on the 9th
      await expect(page.locator("main")).not.toContainText("Vendor call");
      await clean(page, min);
      expect(problems, problems.join("\n")).toEqual([]);
      expect(await shifts(page)).toEqual([]);
    });

    test("PPL-40b S-29: opening a meeting row shows its prep, built from records", async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await watchShifts(page);
      await page.goto("/calendar");
      await page.getByRole("button", { name: "Later", exact: true }).click();
      await page.getByRole("button", { name: "Prepare for Q4 planning" }).click();
      const prep = page.getByTestId("prep");
      await expect(prep).toContainText("Launch date");
      await expect(page.getByTestId("prep-items")).toContainText(
        "Confirm the rate hold in writing",
      );
      await expect(page.getByTestId("prep-pins")).toContainText("Rate sheet goes to Acme by 9 Oct");
      await expect(page.getByTestId("prep-minutes").getByRole("link")).toHaveAttribute(
        "href",
        "/meetings/mt_q4_plan",
      );
      await clean(page, min);
      await page.getByRole("button", { name: "Close prep" }).click();
      await expect(prep).toHaveCount(0);
      expect(problems, problems.join("\n")).toEqual([]);
      expect(await shifts(page)).toEqual([]);
    });

    test("PPL-40b More lists both screens and the left rail keeps More current on them", async ({
      page,
    }) => {
      await page.goto("/more");
      await page.getByRole("link", { name: "Pinboards" }).click();
      await expect(page.getByTestId("pinboards")).toBeVisible();
      await expect(
        page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: /^More/ }),
      ).toHaveAttribute("aria-current", "page");
      await page.goto("/more");
      await page.getByRole("link", { name: "Calendar" }).click();
      await expect(page.getByTestId("calendar")).toBeVisible();
    });
  });
}
