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

    test("PPL-40a S-27: after an action the toast is on screen above the nav and never covers the last rows", async ({
      page,
    }) => {
      await watchShifts(page);
      await page.goto("/plate");
      const slot = page.getByTestId("plate-toast");
      const scrolled = () =>
        page.evaluate(
          () =>
            window.scrollY +
            [...document.querySelectorAll("*")].reduce((n, el) => n + el.scrollTop, 0),
        );
      // What the toast overlaps: visible buttons, links and summaries under it, and the nav.
      const overlaps = () =>
        slot.evaluate((el) => {
          const t = el.querySelector(".plate-toast")?.getBoundingClientRect();
          if (!t) return { inView: false, under: ["no toast"], nav: false };
          const hit = (r: DOMRect) =>
            r.left < t.right && r.right > t.left && r.top < t.bottom && r.bottom > t.top;
          const under = [...document.querySelectorAll("main button, main a, main summary")].flatMap(
            (b) => {
              const r = b.getBoundingClientRect();
              const shown = r.bottom > 0 && r.top < window.innerHeight && r.width > 0;
              return el.contains(b) || !shown || !hit(r) ? [] : [b.textContent?.trim() ?? ""];
            },
          );
          const nav = [...document.querySelectorAll("nav")].some((n) => {
            const r = n.getBoundingClientRect();
            return r.height > 0 && getComputedStyle(n).position === "fixed" && hit(r);
          });
          const inView = t.top >= 0 && t.bottom <= window.innerHeight && t.width > 0;
          return { inView, under, nav };
        });
      const first = page.getByRole("button", { name: /^Done: Review the Q4/ });
      await first.scrollIntoViewIfNeeded();
      const before = await scrolled();
      await first.click();
      await expect(page.getByTestId("plate-status")).toHaveText(/^Marked done/);
      expect(await scrolled()).toBe(before);
      // A sticky toast sits over whatever scrolls under the bottom of the view; it is on screen,
      // clear of the nav, and gone after 8 s (below).
      const now = await overlaps();
      expect([now.inView, now.nav]).toEqual([true, false]);
      // At the end of the page it sits below the last row, not over it.
      await page.evaluate(() => {
        for (const el of document.querySelectorAll("*")) el.scrollTop = el.scrollHeight;
        window.scrollTo(0, document.documentElement.scrollHeight);
      });
      expect(await overlaps()).toEqual({ inView: true, under: [], nav: false });
      expect(
        await page.evaluate(() => (window as unknown as { __shifts: number[] }).__shifts),
      ).toEqual([]);
    });

    test("PPL-40a S-27: the toast clears itself after 8 s, unless focus is in it, and one replaces the last", async ({
      page,
    }) => {
      await page.clock.install();
      await page.goto("/plate");
      const slot = page.getByTestId("plate-toast");
      const status = page.getByTestId("plate-status");
      await page.getByRole("button", { name: /^Snooze until tomorrow: Call Acme/ }).click();
      await expect(slot).toHaveAttribute("data-on", "true");
      await page.getByRole("button", { name: /^Done: Review the Q4/ }).click();
      await expect(status).toHaveText("Marked done: Review the Q4 budget draft."); // replaced, not stacked
      await expect(slot.locator(".plate-toast")).toHaveCount(1);
      await page.clock.fastForward(5000);
      await expect(slot).toHaveAttribute("data-on", "true");
      await page.clock.fastForward(4000);
      await expect(slot).toHaveAttribute("data-on", "false");
      await expect(status).toHaveText("");
      // With focus on Undo it stays; once focus leaves, it goes.
      await page.getByRole("button", { name: /^Done: Confirm the rate hold/ }).click();
      await page.getByRole("button", { name: "Undo" }).focus();
      await page.clock.fastForward(20_000);
      await expect(slot).toHaveAttribute("data-on", "true");
      await page.getByRole("button", { name: "Undo" }).blur();
      await page.clock.fastForward(9000);
      await expect(slot).toHaveAttribute("data-on", "false");
    });

    test("PPL-40a S-27: acting on a row never scrolls the page, keeps focus in the list and announces it", async ({
      page,
    }) => {
      await watchShifts(page);
      await page.goto("/plate");
      // The status is a polite live region that is in the page before anything is done, and no
      // blank toast box is kept yet.
      const status = page.getByTestId("plate-status");
      await expect(page.getByRole("status").and(status)).toHaveCount(1); // <output>: role status, polite
      await expect(page.getByTestId("plate-toast")).toHaveAttribute("data-on", "false");
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
      // Centred, clear of the sticky toast, so the click itself needs no scroll.
      await soon.evaluate((el) => el.scrollIntoView({ block: "center" }));
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
