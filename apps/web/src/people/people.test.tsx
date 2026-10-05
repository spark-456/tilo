// @vitest-environment happy-dom
// PPL-40a / FR-PA-03: S-26 Meetings and S-27 My plate on contract-shaped fixtures. The plate order
// is code (FR-PA-02), the three plate actions and the minutes confirm change only what the contracts
// allow, and only the person's own records and a teammate's display name are ever read (ADR-0016).
import fc from "fast-check";
import { type ReactElement, act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { S_26 } from "../screens/S_26";
import { S_27 } from "../screens/S_27";
import { WORK_ITEMS } from "./data";
import { bucketOf, byDue, laneOf, reducePlate } from "./plate";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function render(ui: ReactElement) {
  const box = document.createElement("div");
  document.body.append(box);
  await act(async () => createRoot(box).render(ui));
  return box;
}
const click = (el: Element | null | undefined) =>
  act(async () => {
    (el as HTMLElement).click();
  });
const named = (box: Element, name: string) =>
  [...box.querySelectorAll("button")].find((b) => b.getAttribute("aria-label")?.startsWith(name));
const titles = (box: Element, id: string) =>
  [...box.querySelectorAll(`[data-testid="${id}"] .bitem-main b`)].map((b) => b.textContent);

describe("PPL-40a plate order (FR-PA-02)", () => {
  it("PPL_40a buckets a due date against the preview day: overdue, 48 hours, the rest", () => {
    expect(bucketOf("2026-10-06", "2026-10-07")).toBe("overdue");
    expect(bucketOf("2026-10-07", "2026-10-07")).toBe("soon");
    expect(bucketOf("2026-10-09", "2026-10-07")).toBe("soon");
    expect(bucketOf("2026-10-10", "2026-10-07")).toBe("rest");
    expect(bucketOf(null, "2026-10-07")).toBe("rest");
  });

  it("PPL_40a lists the same ids in the same order whatever order the items arrive in", () => {
    const sorted = (xs: typeof WORK_ITEMS) => [...xs].sort(byDue).map((i) => i.id);
    fc.assert(
      fc.property(fc.shuffledSubarray([...WORK_ITEMS], { minLength: WORK_ITEMS.length }), (xs) => {
        expect(sorted(xs)).toEqual(sorted(WORK_ITEMS));
      }),
    );
  });

  it("PPL_40a done, snooze and not-mine each record one history entry and move the item", () => {
    const id = "wi_venue_shortlist";
    const applied = (kind: "done" | "snooze" | "not_mine") => {
      const item = reducePlate(WORK_ITEMS, { kind, id }).find((i) => i.id === id);
      if (!item) throw new Error("item missing");
      return item;
    };
    const before = WORK_ITEMS.find((i) => i.id === id)?.history.length ?? 0;
    expect(laneOf(applied("done"))).toBe("done");
    expect(laneOf(applied("snooze"))).toBe("snoozed");
    expect(laneOf(applied("not_mine"))).toBe("asked");
    for (const kind of ["done", "snooze", "not_mine"] as const)
      expect(applied(kind).history).toHaveLength(before + 1);
    expect(reducePlate(WORK_ITEMS, { kind: "done", id: "wi_nobody" })).toEqual(WORK_ITEMS);
  });
});

describe("PPL-40a S-27 My plate", () => {
  it("PPL_40a shows the preview note and the open items in plate order, flagged and snoozed apart", async () => {
    const box = await render(<S_27 />);
    expect(box.querySelector('[data-testid="people-preview"]')?.textContent).toContain(
      "Preview, not connected",
    );
    expect(titles(box, "plate-overdue")).toEqual(["Review the Q4 budget draft"]);
    expect(titles(box, "plate-soon")).toEqual([
      "Confirm the rate hold in writing",
      "Share the venue shortlist with the team",
    ]);
    expect(titles(box, "plate-snoozed")).toEqual(["Get a hotel quote for the offsite"]);
    expect(box.textContent).toContain("Flagged: any follow-up needs you");
    expect(box.textContent).not.toMatch(/@example\.com|Asia\/Kolkata/); // ADR-0016: no contact data
  });

  it("PPL_40a Done moves the item to Done and says so in a status line", async () => {
    const box = await render(<S_27 />);
    await click(named(box, "Done: Review the Q4 budget draft"));
    expect(box.querySelector('[data-testid="plate-overdue"]')).toBeNull();
    expect(titles(box, "plate-done")).toContain("Review the Q4 budget draft");
    expect(box.querySelector('[data-testid="plate-status"]')?.textContent).toBe(
      "Marked done: Review the Q4 budget draft.",
    );
  });

  it("PPL_40a Not mine is offered only on an item someone else assigned", async () => {
    const box = await render(<S_27 />);
    expect(named(box, "Not mine: Share the venue shortlist")).toBeDefined();
    expect(named(box, "Not mine: Review the Q4 budget draft")).toBeUndefined();
    await click(named(box, "Not mine: Share the venue shortlist"));
    expect(titles(box, "plate-asked")).toEqual(["Share the venue shortlist with the team"]);
  });
});

describe("PPL-40a S-26 Meetings", () => {
  it("PPL_40a opens on the minutes that need confirming, with one primary button and evidence", async () => {
    const box = await render(<S_26 params={[""]} />);
    expect(box.querySelectorAll("button.primary")).toHaveLength(1);
    expect(box.querySelector('[data-testid="minutes"]')?.textContent).toContain(
      "Launch on 17 October.",
    );
    expect(box.textContent).toContain("Let's go with the 17th of October for launch.");
    expect(box.textContent).toContain("Unverified"); // never dropped, never shown as backed
    expect(box.textContent).toContain("No evidence cited.");
    expect(box.textContent).not.toMatch(/talk time|sentiment|ranking|https?:\/\//i);
  });

  it("PPL_40a Confirm minutes swaps the button for the confirmed chip", async () => {
    const box = await render(<S_26 params={[""]} />);
    await click([...box.querySelectorAll("button.primary")][0]);
    expect(box.querySelectorAll("button.primary")).toHaveLength(0);
    expect(box.textContent).toContain("Confirmed by you, 7 Oct 2026");
  });

  it("PPL_40a a live meeting has no minutes yet and a discarded one kept nothing", async () => {
    const live = await render(<S_26 params={["mt_design_review"]} />);
    expect(live.querySelector('[data-testid="no-minutes"]')?.textContent).toContain(
      "no minutes yet",
    );
    const gone = await render(<S_26 params={["mt_standup"]} />);
    expect(gone.querySelector('[data-testid="no-minutes"]')?.textContent).toContain(
      "Nothing was kept",
    );
  });

  it("PPL_40a a flagged transcript says so on its minutes", async () => {
    const box = await render(<S_26 params={["mt_vendor_sync"]} />);
    expect(box.querySelector('[data-testid="minutes-flagged"]')).not.toBeNull();
  });
});
