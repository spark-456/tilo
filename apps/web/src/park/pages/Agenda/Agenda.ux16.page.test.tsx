// @vitest-environment happy-dom
// FR-UX-16 gaps on the Agenda (supplement 1.6 row 74): the three switches of the event panel decide what
// Tilo does for that event (joins, takes notes, briefs) and what the panel and the chip claim. A switch that is
// off claims no join, no notes and no brief. No Api route exists for the switches, so a change is page state
// only, says so in words, and calls no Api and fetches nothing (HR-1..HR-7: no motion without an event).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderAgenda, settle } from "../../../../test-support/park/agendaHarness";
import { click, q, qa } from "../../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const text = (root: ParentNode) => (root as HTMLElement).textContent ?? "";
const detail = (root: ParentNode) => q(root, '[aria-label="Event detail"]');
const week = (root: ParentNode) => q(root, '[aria-label="This week"]');
const chip = (root: ParentNode, id: string) => q<HTMLElement>(root, `[data-event="${id}"]`);
const byText = (root: ParentNode, sel: string, t: string): HTMLElement => {
  const el = qa<HTMLElement>(root, sel).find((e) => (e.textContent ?? "").trim() === t);
  if (!el) throw new Error(`no ${sel} with text "${t}"`);
  return el;
};
/** The panel's switch whose label starts with `label`. */
const sw = (root: ParentNode, label: string): HTMLElement => {
  const el = qa<HTMLElement>(detail(root), '[role="switch"]').find((s) =>
    (s.textContent ?? "").startsWith(label),
  );
  if (!el) throw new Error(`no switch "${label}"`);
  return el;
};
const JOIN = "Tilo joins and takes notes";
const PINS = "Turn action items into pins";
const BRIEF = "Brief before it starts";
const joinsBadge = (root: ParentNode) => qa(root, '[aria-label="Tilo joins"]');

describe("FR_UX_16 the join switch decides whether Tilo joins and takes notes", () => {
  it("FR_UX_16 on: the chip and the panel show Tilo joining, in words, and the notes are promised", async () => {
    const { container } = await renderAgenda();
    // The default event is the supplier sync, which Tilo joins.
    expect(joinsBadge(chip(container, "sync"))).toHaveLength(1);
    expect(joinsBadge(detail(container))).toHaveLength(1);
    expect(sw(container, JOIN).getAttribute("aria-checked")).toBe("true");
    expect(text(sw(container, JOIN))).toContain("Shares notes with attendees after");
  });

  it("FR_UX_16 off: no Tilo on the chip, none in the panel, and no notes are claimed", async () => {
    const { container } = await renderAgenda();
    click(sw(container, JOIN));
    expect(sw(container, JOIN).getAttribute("aria-checked")).toBe("false");
    expect(joinsBadge(chip(container, "sync"))).toHaveLength(0);
    expect(joinsBadge(detail(container))).toHaveLength(0);
    const label = text(sw(container, JOIN));
    expect(label).not.toContain("Shares notes with attendees after");
    expect(label).toContain("Tilo stays out, so no notes are taken");
    // Action items come from the notes: with no notes there is nothing to pin.
    expect(text(sw(container, PINS))).not.toContain("Pinned to the Team board with owners");
    expect(text(sw(container, PINS))).toContain("No notes, so nothing to pin");
    // Back on: everything it promised comes back.
    click(sw(container, JOIN));
    expect(joinsBadge(chip(container, "sync"))).toHaveLength(1);
    expect(joinsBadge(detail(container))).toHaveLength(1);
    expect(text(sw(container, JOIN))).toContain("Shares notes with attendees after");
    expect(text(sw(container, PINS))).toContain("Pinned to the Team board with owners");
  });

  it("FR_UX_16 an event Tilo does not join starts off, and turning it on adds Tilo to that event only", async () => {
    const { container } = await renderAgenda();
    click(chip(container, "jin"));
    expect(sw(container, JOIN).getAttribute("aria-checked")).toBe("false");
    expect(text(sw(container, JOIN))).toContain("Tilo stays out, so no notes are taken");
    expect(joinsBadge(detail(container))).toHaveLength(0);
    click(sw(container, JOIN));
    expect(joinsBadge(chip(container, "jin"))).toHaveLength(1);
    expect(joinsBadge(detail(container))).toHaveLength(1);
    // Another meeting is untouched.
    expect(joinsBadge(chip(container, "sync"))).toHaveLength(1);
    click(chip(container, "q4"));
    expect(sw(container, JOIN).getAttribute("aria-checked")).toBe("false");
    expect(joinsBadge(chip(container, "q4"))).toHaveLength(0);
  });
});

describe("FR_UX_16 the brief switch decides whether Tilo briefs", () => {
  it("FR_UX_16 on: the brief and when it arrives are shown", async () => {
    const { container } = await renderAgenda();
    expect(sw(container, BRIEF).getAttribute("aria-checked")).toBe("true");
    expect(text(detail(container))).toContain("TILO’S BRIEF");
    expect(text(detail(container))).toContain("From 14 emails · 08:10");
    expect(qa(detail(container), "button").map((b) => b.textContent)).not.toContain(
      "Ask Tilo for a brief",
    );
  });

  it("FR_UX_16 off: no brief is claimed and the person can ask for one", async () => {
    const { container, ...h } = await renderAgenda();
    click(sw(container, BRIEF));
    expect(sw(container, BRIEF).getAttribute("aria-checked")).toBe("false");
    expect(h.toast()).toBe("Brief preference off for Supplier sync · Northline");
    const d = text(detail(container));
    expect(d).not.toContain("TILO’S BRIEF");
    expect(d).not.toContain("From 14 emails · 08:10");
    expect(d).not.toContain("Northline wants 60-day payment terms");
    expect(d).not.toContain("arrives 15 min before");
    // MB-10: the sample ask cannot queue an automatic brief.
    click(byText(detail(container), "button", "Ask Tilo for a brief"));
    expect(sw(container, BRIEF).getAttribute("aria-checked")).toBe("false");
    expect(h.toast()).toBe(
      "Brief generation is not available in this sample for Supplier sync · Northline",
    );
    expect(text(detail(container))).not.toContain("TILO’S BRIEF");
  });

  it("FR_UX_16 on again with the switch: the brief comes back and the toast says so", async () => {
    const { container, ...h } = await renderAgenda();
    click(sw(container, BRIEF));
    click(sw(container, BRIEF));
    expect(h.toast()).toBe("Automatic briefs are not available yet for Supplier sync · Northline");
    expect(text(detail(container))).toContain("TILO’S BRIEF");
    expect(qa(detail(container), "button").map((b) => b.textContent)).not.toContain(
      "Ask Tilo for a brief",
    );
  });

  it("FR_UX_16 MB_10 turning on a sample switch does not invent a brief", async () => {
    const { container } = await renderAgenda();
    click(chip(container, "jin"));
    expect(sw(container, BRIEF).getAttribute("aria-checked")).toBe("false");
    expect(text(detail(container))).not.toContain("TILO’S BRIEF");
    click(sw(container, BRIEF));
    expect(text(detail(container))).not.toContain("TILO’S BRIEF");
    expect(text(detail(container))).not.toContain("Queued · arrives 15 min before");
    expect(qa(detail(container), "button").map((b) => b.textContent)).toContain(
      "Ask Tilo for a brief",
    );
    // Off again: still no brief has been made.
    click(sw(container, BRIEF));
    expect(text(detail(container))).not.toContain("Queued · arrives 15 min before");
    expect(text(detail(container))).not.toContain("TILO’S BRIEF");
  });

  it("FR_UX_16 the switches are per event: a brief switched off on one meeting leaves another", async () => {
    const { container } = await renderAgenda();
    click(sw(container, BRIEF));
    click(chip(container, "lead"));
    expect(sw(container, BRIEF).getAttribute("aria-checked")).toBe("true");
    expect(text(detail(container))).toContain("TILO’S BRIEF");
  });
});

describe("FR_UX_16 the switches are page state: honest, and no Api call", () => {
  it("FR_UX_16 the panel says the switches are not connected yet", async () => {
    const { container } = await renderAgenda();
    const note = text(detail(container));
    expect(note).toContain("Not connected yet");
    expect(note).toContain("kept on this page only");
  });

  it("FR_UX_16 flipping every switch calls no Api method and fetches nothing", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const calls: string[] = [];
    let armed = false;
    const api = new Proxy(createFixtureApi(), {
      get(target, key: string) {
        const v = Reflect.get(target, key);
        if (typeof v !== "function") return v;
        return (...args: unknown[]) => {
          if (armed) calls.push(key);
          return (v as (...a: unknown[]) => unknown)(...args);
        };
      },
    }) as Api;
    const { container } = await renderAgenda({ api });
    armed = true;
    for (const label of [JOIN, PINS, BRIEF]) click(sw(container, label));
    await settle();
    expect(calls).toEqual([]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("FR_UX_16 day load, calendar chips and the weekend", () => {
  it("FR_UX_16 day load counts the person's meetings only, and a booked meeting adds to it", async () => {
    const { container } = await renderAgenda();
    const loads = () => qa(week(container), ".park-agenda-dayload").map((e) => e.textContent);
    // Tilo's own runs (tiloOnly) and the Tilo calendar are not load.
    expect(loads()).toEqual([
      "3 events · 2.3 h",
      "3 events · 2 h",
      "3 events · 2.5 h",
      "3 events · 2.8 h",
      "3 events · 2 h",
    ]);
    click(byText(week(container), "button", "Weekend"));
    expect(loads().slice(5)).toEqual(["1 event · 2 h", "Free"]);
    click(byText(container, "button", "Find a time"));
    click(qa<HTMLElement>(week(container), "[data-slot]")[0] as HTMLElement);
    await settle();
    expect(loads()[3]).toBe("4 events · 3.3 h");
  });

  it("FR_UX_16 calendar chips say on or off in their state, not by opacity alone", async () => {
    const { container } = await renderAgenda();
    const work = byText(week(container), "button", "Work");
    expect(work.getAttribute("aria-pressed")).toBe("true");
    click(work);
    expect(work.getAttribute("aria-pressed")).toBe("false");
    expect(container.querySelector('[data-event="sync"]')).toBeNull();
    expect(container.querySelector('[data-event="gym"]')).not.toBeNull();
    // The meeting still open in the panel keeps its switches.
    expect(qa(detail(container), '[role="switch"]')).toHaveLength(3);
  });
});
