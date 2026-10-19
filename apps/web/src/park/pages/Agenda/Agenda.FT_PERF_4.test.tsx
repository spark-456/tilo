// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderAgenda, settle } from "../../../../test-support/park/agendaHarness";
import { click, q, qa } from "../../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import { agenda } from "../../api/fixtures/agenda";
import type { Api } from "../../api/index";
import { dated } from "../../api/sampleDates";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("FT_PERF_4 Agenda calendar enhancements", () => {
  it("FT_PERF_4 week navigation and Today button update the week title and view", async () => {
    const { container } = await renderAgenda();
    const prevBtn = q<HTMLButtonElement>(container, 'button[aria-label="Previous week"]');
    const nextBtn = q<HTMLButtonElement>(container, 'button[aria-label="Next week"]');
    const todayBtn = q<HTMLButtonElement>(container, 'button[aria-label="Today"]');

    expect(prevBtn).not.toBeNull();
    expect(nextBtn).not.toBeNull();
    expect(todayBtn).not.toBeNull();

    const titleEl = q(container, '[aria-label="This week"] .park-agenda-h2');
    const initialTitle = titleEl.textContent;
    expect(initialTitle).toContain("This week");

    // Click next week
    act(() => nextBtn.click());
    await settle();
    expect(titleEl.textContent).toContain("Week of");

    // Click previous week twice
    act(() => {
      prevBtn.click();
      prevBtn.click();
    });
    await settle();
    expect(titleEl.textContent).toContain("Week of");

    // Click Today to return
    act(() => todayBtn.click());
    await settle();
    expect(titleEl.textContent).toBe(initialTitle);
  });

  it("FT_PERF_4 day, week, and month view switcher toggles calendar view modes", async () => {
    const { container } = await renderAgenda();
    const viewSwitch = q(container, '[role="radiogroup"][aria-label="Calendar view"]');
    expect(viewSwitch).not.toBeNull();

    const dayBtn = q<HTMLButtonElement>(viewSwitch, 'button[aria-checked="false"]:nth-child(1)');
    const monthBtn = q<HTMLButtonElement>(viewSwitch, 'button[aria-checked="false"]:nth-child(3)');

    // Switch to Month view
    act(() => monthBtn.click());
    await settle();
    expect(container.querySelector(".park-agenda-cal")).not.toBeNull();

    // Switch to Day view
    act(() => dayBtn.click());
    await settle();
    const dayCols = container.querySelectorAll(".park-agenda-col");
    expect(dayCols.length).toBe(1);

    // Switch back to Week view
    const weekBtn = q<HTMLButtonElement>(viewSwitch, "button:nth-child(2)");
    act(() => weekBtn.click());
    await settle();
    expect(container.querySelectorAll(".park-agenda-col").length).toBeGreaterThanOrEqual(5);
  });

  it("FT_PERF_4 calendar body renders hours 07 to 21 with now-line", async () => {
    const { container } = await renderAgenda();
    const hourLabels = qa(container, ".park-agenda-hour").map((el) => el.textContent?.trim());
    expect(hourLabels).toContain("08:00");
    expect(hourLabels).toContain("12:00");
    expect(hourLabels).toContain("20:00");

    const nowLine = container.querySelector('[aria-label="Current time"]');
    expect(nowLine).not.toBeNull();
  });

  it("FT_PERF_4 drag a pin onto a slot opens confirm sheet before any calendar write", async () => {
    const bookSlot = vi.fn(() =>
      Promise.resolve({ ok: true as const, source: "fixture" as const }),
    );
    const baseApi = createFixtureApi();
    const api: Api = {
      ...baseApi,
      bookSlot: bookSlot as unknown as Api["bookSlot"],
    };

    const { container } = await renderAgenda({ api });
    // Open find a time to see slots
    click(q(container, "button.park-btn--primary"));
    await settle();

    const slot = q<HTMLButtonElement>(container, "[data-slot]");
    expect(slot).not.toBeNull();

    // Simulate dropping a pin onto the slot
    act(() => {
      const dropEvent = new Event("drop", { bubbles: true }) as DragEvent;
      Object.defineProperty(dropEvent, "dataTransfer", {
        value: {
          getData: (format: string) =>
            format === "application/json"
              ? JSON.stringify({ type: "pin", id: "p1", title: "Review report" })
              : "Review report",
          dropEffect: "move",
        },
      });
      slot.dispatchEvent(dropEvent);
    });
    await settle();

    // Confirm sheet is open
    const sheet = container.querySelector('[aria-label="Confirm schedule"]');
    expect(sheet).not.toBeNull();
    expect(sheet?.textContent).toContain("Review report");
    // No calendar write yet!
    expect(bookSlot).not.toHaveBeenCalled();

    // Click Cancel closes sheet without write
    const cancelBtn = sheet
      ? qa<HTMLButtonElement>(sheet, "button").find((b) => b.textContent === "Cancel")
      : undefined;
    expect(cancelBtn).toBeDefined();
    act(() => cancelBtn?.click());
    await settle();
    expect(bookSlot).not.toHaveBeenCalled();
    expect(container.querySelector('[aria-label="Confirm schedule"]')).toBeNull();

    // Drop again and click Confirm
    act(() => {
      const dropEvent = new Event("drop", { bubbles: true }) as DragEvent;
      Object.defineProperty(dropEvent, "dataTransfer", {
        value: {
          getData: (format: string) =>
            format === "application/json"
              ? JSON.stringify({ type: "pin", id: "p1", title: "Review report" })
              : "Review report",
          dropEffect: "move",
        },
      });
      slot.dispatchEvent(dropEvent);
    });
    await settle();

    const confirmSheet = container.querySelector('[aria-label="Confirm schedule"]');
    const confirmBtn = confirmSheet
      ? qa<HTMLButtonElement>(confirmSheet, "button").find((b) => b.textContent === "Confirm")
      : undefined;
    expect(confirmBtn).toBeDefined();
    act(() => confirmBtn?.click());
    await settle();

    // bookSlot is called only after confirm
    expect(bookSlot).toHaveBeenCalledTimes(1);
  });

  it("FT_PERF_4 sample dates follow today on weekend (Saturday 10 Oct is day 5)", () => {
    const a = dated(agenda, { y: 2026, m: 10, d: 10 });
    expect(a.today).toBe(5);
  });
});
