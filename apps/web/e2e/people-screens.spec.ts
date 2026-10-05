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
      // Focus stays in the list (the next group's box, as the only overdue row left); Undo is in the page.
      await expect(page.locator("#plate-group-soon")).toBeFocused();
      await expect(page.getByRole("button", { name: "Undo" })).not.toBeFocused();
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

    test("PPL-40a S-27: the toast never covers a visible button, at the top, middle or end of the page", async ({
      page,
    }) => {
      await watchShifts(page);
      await page.goto("/plate");
      await page.getByRole("button", { name: /^Snooze until tomorrow: Call Acme/ }).click();
      await page.getByRole("button", { name: /^Done: Review the Q4/ }).click();
      await expect(page.getByTestId("plate-status")).toBeVisible();
      const slot = page.getByTestId("plate-toast");
      const covered = () =>
        slot.evaluate((el) => {
          const toast = el.querySelector(".plate-toast")?.getBoundingClientRect();
          if (!toast) return ["no toast"];
          const vh = window.innerHeight;
          return [...document.querySelectorAll("main button, main a, main summary")].flatMap(
            (b) => {
              if (el.contains(b)) return [];
              const r = b.getBoundingClientRect();
              const shown = r.bottom > 0 && r.top < vh && r.width > 0;
              const hit =
                r.left < toast.right &&
                r.right > toast.left &&
                r.top < toast.bottom &&
                r.bottom > toast.top;
              return shown && hit ? [`${b.textContent?.trim()}`] : [];
            },
          );
        });
      for (const to of [0, 0.5, 1]) {
        await page.evaluate((f) => {
          for (const el of document.querySelectorAll("*"))
            if (
              el.scrollHeight > el.clientHeight + 1 &&
              getComputedStyle(el).overflowY !== "visible"
            )
              el.scrollTop = (el.scrollHeight - el.clientHeight) * f;
          window.scrollTo(0, (document.documentElement.scrollHeight - innerHeight) * f);
        }, to);
        expect(await covered()).toEqual([]);
      }
      // The box is reserved at toast height before any toast shows, so nothing shifts.
      const box = await slot.boundingBox();
      expect(box?.height).toBeGreaterThanOrEqual(name === "mobile" ? 100 : 68);
      await expect(slot).toHaveAttribute("data-used", "true");
      expect(
        await page.evaluate(() => (window as unknown as { __shifts: number[] }).__shifts),
      ).toEqual([]);
    });

    test("PPL-40a S-27: acting on a row never scrolls the page, keeps focus in the list and announces it", async ({
      page,
    }) => {
      await watchShifts(page);
      await page.goto("/plate");
      // The status is a polite live region that is in the page before anything is done, and no
      // blank toast box is reserved yet.
      const status = page.getByTestId("plate-status");
      await expect(page.getByRole("status").and(status)).toHaveCount(1); // <output>: role status, polite
      await expect(page.getByTestId("plate-toast")).toHaveAttribute("data-used", "false");
      expect((await page.getByTestId("plate-toast").boundingBox())?.height ?? 0).toBeLessThan(2);
      const scrolled = () =>
        page.evaluate(
          () =>
            window.scrollY +
            [...document.querySelectorAll("*")].reduce((n, el) => n + el.scrollTop, 0),
        );
      // First row of the first group: it is the only overdue row, so focus lands on the next
      // group's box, exactly where the list now begins.
      const first = page.getByRole("button", { name: "Done: Review the Q4 budget draft" });
      await first.scrollIntoViewIfNeeded();
      const before = await scrolled();
      await first.click();
      await expect(status).toHaveText("Marked done: Review the Q4 budget draft.");
      expect(await scrolled()).toBe(before);
      await expect(page.locator("#plate-group-soon")).toBeFocused();
      // First row of a group with more rows: focus lands on the next row's same control.
      const soon = page.getByRole("button", { name: "Done: Confirm the rate hold in writing" });
      await soon.scrollIntoViewIfNeeded();
      const mid = await scrolled();
      await soon.click();
      await expect(status).toHaveText("Marked done: Confirm the rate hold in writing.");
      expect(await scrolled()).toBe(mid);
      await expect(
        page.getByRole("button", { name: "Done: Share the venue shortlist with the team" }),
      ).toBeFocused();
      // The toast's Undo is in the page, reachable by Tab, and a row put back is focused.
      await page.getByRole("button", { name: "Undo" }).focus();
      await page.keyboard.press("Enter");
      await expect(status).toHaveText("Put back.");
      await expect(
        page.getByRole("button", { name: "Done: Confirm the rate hold in writing" }),
      ).toBeFocused();
      expect(
        await page.evaluate(() => (window as unknown as { __shifts: number[] }).__shifts),
      ).toEqual([]);
    });

    test("PPL-40a S-26: the filter pills are a named radio group with one selected", async ({
      page,
    }) => {
      await page.goto("/meetings");
      const group = page.getByRole("group", { name: "Filter meetings" });
      await expect(group.getByRole("radio")).toHaveCount(4);
      await expect(group.getByRole("radio", { name: /^All/ })).toBeChecked();
      await group.getByRole("radio", { name: /^Confirmed/ }).check();
      await expect(group.getByRole("radio", { name: /^Confirmed/ })).toBeChecked();
      await expect(group.getByRole("radio", { name: /^All/ })).not.toBeChecked();
      await page.keyboard.press("ArrowRight");
      await expect(group.getByRole("radio", { name: /^Other/ })).toBeChecked();
    });

    test("PPL-40a S-26: an attendee with no account has a neutral glyph, not initials", async ({
      page,
    }) => {
      await page.goto("/meetings/mt_vendor_sync");
      await expect(page.getByRole("heading", { level: 2, name: /^Minutes: / })).toBeVisible();
      const guest = page
        .getByRole("list", { name: "Attendees" })
        .getByRole("listitem")
        .filter({ hasText: "Dev from Acme" });
      await expect(guest.locator(".avatar svg")).toHaveCount(1);
      await expect(guest.locator(".avatar")).toHaveText("");
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
