// PPL-40a / FR-PA-03: S-26 Meetings (minutes, evidence quotes, confirm) and S-27 My plate (done,
// snooze, not mine) on fixtures, at 1440x900 and 390x844: the actions work, axe is clean, the
// targets are big enough, nothing shifts, the console stays quiet, and one filled primary per screen.
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

for (const [name, viewport] of Object.entries({ desktop: DESKTOP, mobile: MOBILE })) {
  const min = name === "mobile" ? 44 : 24;
  test.describe(`PPL-40a people screens at ${name}`, () => {
    test.use({ viewport });

    test("PPL-40a S-26: opens on the minutes to confirm, with evidence, and Confirm minutes works", async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await watchShifts(page);
      await page.goto("/meetings");
      await expect(page.getByTestId("people-preview")).toContainText("Preview, not connected");
      await expect(
        page.getByRole("heading", { level: 2, name: "Minutes: Q4 planning" }),
      ).toBeVisible();
      await page.getByText("Evidence (2 quotes)").first().click();
      await expect(
        page.getByText("Let's go with the 17th of October for launch.").first(),
      ).toBeVisible();
      await expect(page.locator("button.primary")).toHaveCount(1);
      await page.getByRole("button", { name: "Confirm minutes" }).click();
      await expect(page.getByText("Confirmed by you, 7 Oct 2026")).toBeVisible();
      await expect(page.locator("button.primary")).toHaveCount(0);
      // Another meeting is its own address, and the page keeps a single heading level order.
      await page.getByRole("link", { name: /Design review/ }).click();
      await expect(page).toHaveURL(/\/meetings\/mt_design_review$/);
      await expect(page.getByTestId("no-minutes")).toContainText("no minutes yet");
      expect(problems, problems.join("\n")).toEqual([]);
      expect(
        await page.evaluate(() => (window as unknown as { __shifts: number[] }).__shifts),
      ).toEqual([]);
    });

    test("PPL-40a S-27: Done and Snooze move an item and say so; Not mine is only on an assigned one", async ({
      page,
    }) => {
      const problems = collectConsoleProblems(page);
      await watchShifts(page);
      await page.goto("/plate");
      await expect(page.getByTestId("people-preview")).toContainText("Preview, not connected");
      await expect(page.getByTestId("plate-overdue")).toContainText("Review the Q4 budget draft");
      await expect(page.getByRole("button", { name: /^Not mine/ })).toHaveCount(1);
      await page.getByRole("button", { name: "Done: Review the Q4 budget draft" }).click();
      await expect(page.getByTestId("plate-status")).toHaveText(
        "Marked done: Review the Q4 budget draft.",
      );
      await expect(page.getByRole("button", { name: "Undo" })).toBeFocused();
      await expect(page.getByTestId("plate-done")).toContainText("Review the Q4 budget draft");
      await page.getByRole("button", { name: "Undo" }).click();
      await expect(page.getByTestId("plate-overdue")).toContainText("Review the Q4 budget draft");
      await page
        .getByRole("button", { name: "Snooze until tomorrow: Call Acme about the delivery date" })
        .click();
      await expect(page.getByTestId("plate-snoozed")).toContainText(
        "Call Acme about the delivery date",
      );
      await page.getByRole("button", { name: /^Not mine: Share the venue/ }).click();
      await expect(page.getByTestId("plate-asked")).toContainText("Share the venue shortlist");
      expect(problems, problems.join("\n")).toEqual([]);
      expect(
        await page.evaluate(() => (window as unknown as { __shifts: number[] }).__shifts),
      ).toEqual([]);
    });

    test("PPL-40a S-27: the strip jumps to a group and the Evidence trigger shows quotes with line numbers", async ({
      page,
    }) => {
      await page.goto("/plate");
      await page.getByTestId("pill-rest").click();
      await expect(page.locator("#plate-group-rest")).toBeFocused();
      await page.getByText("Evidence (1 quote)").last().click();
      await expect(page.getByText("line 31")).toBeVisible();
    });

    for (const path of ["/meetings", "/plate"]) {
      test(`PPL-40a ${path}: axe clean, targets at least ${min}px, no filled primary beyond the one`, async ({
        page,
      }) => {
        await page.goto(path);
        await expect(page.getByTestId("people-preview")).toBeVisible();
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
          .analyze();
        expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
        const small = await page.locator("main a, main button, main summary").evaluateAll(
          (els, side) =>
            els.flatMap((el) => {
              const r = el.getBoundingClientRect();
              return r.width < side || r.height < side
                ? [`${el.textContent?.trim()} ${r.width}x${r.height}`]
                : [];
            }),
          min,
        );
        expect(small).toEqual([]);
        await expect(page.locator("button.primary")).toHaveCount(path === "/meetings" ? 1 : 0);
      });
    }

    test("PPL-40a More lists both screens and the left rail keeps More current on them", async ({
      page,
    }) => {
      await page.goto("/more");
      await page.getByRole("link", { name: "My plate" }).click();
      await expect(page.getByTestId("plate")).toBeVisible();
      await expect(
        page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: /^More/ }),
      ).toHaveAttribute("aria-current", "page");
      await page.goto("/more");
      await page.getByRole("link", { name: "Meetings" }).click();
      await expect(page.getByTestId("meetings")).toBeVisible();
    });
  });
}
