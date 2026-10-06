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
  [...box.querySelectorAll(`[data-testid="${id}"] .prow-title b`)].map((b) => b.textContent);

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

  it("PPL_40a not-mine is refused on an item the person made, and put-back undoes each action", () => {
    expect(reducePlate(WORK_ITEMS, { kind: "not_mine", id: "wi_budget_review" })).toEqual(
      WORK_ITEMS,
    );
    const id = "wi_venue_shortlist";
    for (const kind of ["done", "snooze", "not_mine"] as const) {
      const back = reducePlate(reducePlate(WORK_ITEMS, { kind, id }), {
        kind: "put_back",
        id,
      }).find((i) => i.id === id);
      expect(back && laneOf(back)).toBe("open");
      expect(back?.snoozed_until).toBeNull();
    }
  });

  it("PPL_40a put-back on an item that is already open is a no-op: no redundant reopened entry", () => {
    for (const id of ["wi_budget_review", "wi_venue_shortlist"]) {
      expect(reducePlate(WORK_ITEMS, { kind: "put_back", id })).toEqual(WORK_ITEMS);
      const once = reducePlate(WORK_ITEMS, { kind: "snooze", id });
      const back = reducePlate(once, { kind: "put_back", id });
      expect(reducePlate(back, { kind: "put_back", id })).toEqual(back);
    }
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

  it("PPL_40a acting leaves focus in the list: the next row's same control, else a group box", async () => {
    document.body.replaceChildren(); // the screen looks rows up by id in the document
    const box = await render(<S_27 />);
    expect(box.querySelector('[data-testid="plate-toast"]')?.getAttribute("data-on")).toBe("false");
    await click(named(box, "Done: Confirm the rate hold in writing"));
    expect(document.activeElement).toBe(named(box, "Done: Share the venue shortlist"));
    await click(named(box, "Done: Review the Q4 budget draft")); // the only overdue row
    expect(document.activeElement?.id).toBe("plate-group-soon");
    expect(document.querySelector(".plate-toast button")).not.toBe(document.activeElement);
    expect(box.querySelector('[data-testid="plate-toast"]')?.getAttribute("data-on")).toBe("true");
  });

  it("PPL_40a the strip has a pill per group with the real count, and Undo in the toast puts the item back", async () => {
    const box = await render(<S_27 />);
    const pills = [...box.querySelectorAll('[data-testid="plate-strip"] button')].map((b) =>
      b.textContent?.replace(/\s+/g, " "),
    );
    expect(pills).toEqual(["Overdue 1", "Soon 2", "Later 2", "Snoozed 1", "Done 1"]);
    await click(named(box, "Done: Review the Q4 budget draft"));
    expect(box.querySelector('[data-testid="pill-overdue"]')).toBeNull();
    await click(
      [...box.querySelectorAll(".plate-toast button")].find((b) => b.textContent === "Undo"),
    );
    expect(titles(box, "plate-overdue")).toEqual(["Review the Q4 budget draft"]);
    expect(box.querySelector('[data-testid="plate-status"]')?.textContent).toBe("Put back.");
  });

  it("PPL_40a an item's state is a chip in words: its due date, Snoozed until, Waiting for", async () => {
    const box = await render(<S_27 />);
    expect(box.textContent).toContain("Overdue, 6 Oct");
    expect(box.textContent).toContain("Due soon, 9 Oct");
    expect(box.textContent).toContain("Snoozed until 8 Oct");
    await click(named(box, "Not mine: Share the venue shortlist"));
    expect(box.textContent).toContain("Waiting for Priya Nair to reassign");
  });

  it("PPL_40a every row's source line has a decorative icon: meeting, mail or you", async () => {
    const box = await render(<S_27 />);
    const rows = [...box.querySelectorAll('[data-testid="plate-item"] .bitem-sub')];
    expect(rows.length).toBeGreaterThan(0);
    for (const sub of rows) {
      const icon = sub.querySelector("svg.source-icon");
      expect(icon?.getAttribute("aria-hidden")).toBe("true");
    }
    expect(rows.some((r) => r.textContent?.startsWith("Added by you."))).toBe(true);
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
    expect(box.textContent).toContain("Asha Rao, line 12"); // a line number, never an utterance id
    expect(box.textContent).not.toMatch(/u00[0-9]{2}|@example[.]com/);
    expect(box.textContent).toContain("Unverified"); // never dropped, never shown as backed
    expect(box.textContent).toContain("No evidence cited.");
    expect(box.textContent).not.toMatch(/talk time|sentiment|ranking|https?:\/\//i);
  });

  it("PPL_40a the strip counts meetings by group and filters the list", async () => {
    const box = await render(<S_26 params={[""]} />);
    const strip = box.querySelector('[data-testid="meeting-strip"]');
    const labels = [...(strip?.querySelectorAll("label") ?? [])].map((l) => l.textContent);
    expect(labels).toEqual(["All 4", "Needs confirming 1", "Confirmed 1", "Other 2"]);
    const radio = strip?.querySelectorAll("input")[1] as HTMLInputElement;
    await click(radio);
    expect(box.querySelectorAll('[data-testid="meeting-list"] li')).toHaveLength(1);
  });

  it("PPL_40a the filter pills are a named group of radios with one selected, like the S-14 tabs", async () => {
    document.body.replaceChildren(); // radios of the same name in earlier renders share one group
    const box = await render(<S_26 params={[""]} />);
    const strip = box.querySelector('[data-testid="meeting-strip"]');
    expect(strip?.tagName).toBe("FIELDSET");
    expect(strip?.querySelector("legend")?.textContent).toBe("Filter meetings");
    const radios = [...(strip?.querySelectorAll("input") ?? [])] as HTMLInputElement[];
    expect(radios.every((r) => r.type === "radio" && r.name === radios[0]?.name)).toBe(true);
    expect(radios.map((r) => r.checked)).toEqual([true, false, false, false]);
    await click(radios[2]);
    expect(radios.map((r) => r.checked)).toEqual([false, false, true, false]);
  });

  it("PPL_40a an attendee with no account gets a neutral glyph, not initials; the rest keep initials", async () => {
    const box = await render(<S_26 params={["mt_vendor_sync"]} />);
    const discs = [...box.querySelectorAll('ul[aria-label="Attendees"] .avatar')];
    const guest = discs.find((d) => d.parentElement?.textContent === "Dev from Acme");
    expect(guest?.querySelector("svg")).not.toBeNull();
    expect(guest?.textContent).toBe("");
    expect(discs.some((d) => d.textContent === "DA")).toBe(false);
    expect(discs.some((d) => d.textContent === "AR")).toBe(true);
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
