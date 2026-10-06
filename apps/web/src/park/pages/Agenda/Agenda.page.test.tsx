// @vitest-environment happy-dom
// WEB-9 Agenda page: exact copy (inventory.md "Tilo App Agenda"), the interactions of the reference
// (Tilo App Agenda.dc.html) and the decide() effects, rendered on the fixture Api in happy-dom.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { click, countPrimary, q, qa } from "../../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import { NotBuilt } from "../../api/liveApi";
import { cleanup, renderAgenda, settle } from "./agendaHarness";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const text = (root: ParentNode) => (root as HTMLElement).textContent ?? "";
const byText = <T extends Element>(root: ParentNode, sel: string, t: string): T => {
  const el = qa<T>(root, sel).find((e) => (e.textContent ?? "").trim() === t);
  if (!el) throw new Error(`no ${sel} with text "${t}"`);
  return el;
};
const region = (root: ParentNode, name: string) => q(root, `[aria-label="${name}"]`);
const pin = (root: ParentNode, id: string) => q(root, `[data-pin="${id}"]`);
const event = (root: ParentNode, id: string) => q<HTMLElement>(root, `[data-event="${id}"]`);
const detail = (root: ParentNode) => region(root, "Event detail");
const type = (input: HTMLInputElement, value: string) =>
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const toasted = (calls: { toast: ReturnType<typeof vi.fn> }, msg: string) =>
  expect(calls.toast).toHaveBeenCalledWith(msg, undefined, undefined);

describe("WEB_9_agenda_copy: the designed text, verbatim", () => {
  it("WEB_9_agenda_header_boards_and_week_copy", async () => {
    const { container } = await renderAgenda();
    expect(q(container, "h1").textContent).toBe("Agenda");
    for (const name of ["Boards", "This week", "Event detail"]) region(container, name);
    q(container, '[role="radiogroup"][aria-label="Board style"]');
    const t = text(container);
    for (const s of [
      "Thursday 24 September. Pins from your team and Tilo, and a week that stays in sync.",
      "Google Calendar · synced just now",
      "Anyone on the team can pin. Tilo pins action items from meetings and things that need you.",
      "Pinboard",
      "Grouped",
      "Team board",
      "Northwind Ops · 5 people and Tilo",
      "6 open",
      "My board",
      "Only you and Tilo can see this",
      "3 open",
      "TILO SUGGESTS",
      "Book the K1 Level 3 gate review",
      "Not now",
      "Pin it",
      "Approve Laptop Depot budget",
      "Tilo · today",
      "This week · 21–25 September",
      "16 events from Google Calendar · Tilo joins 4 still to come",
      "Work",
      "Personal",
      "Weekend",
      "MON",
      "THU",
      "3 events · 2.8 h",
      "09:00",
      "17:00",
    ])
      expect(t, s).toContain(s);
    expect(byText(container, "button", "Find a time").className).toContain("park-btn--primary");
    expect(countPrimary(container), "UX-1: one filled primary").toBe(1);
    expect(text(pin(container, "t1"))).toContain("Review and approve");
  });

  it("WEB_9_agenda_default_event_detail_is_the_supplier_sync", async () => {
    const { container } = await renderAgenda();
    const d = text(detail(container));
    for (const s of [
      "Work · Google Calendar",
      "Supplier sync · Northline",
      "Thu 24 Sep · 14:00–14:45",
      "TILO’S BRIEF",
      "From 14 emails · 08:10",
      "Northline wants 60-day payment terms. Your policy is 30.",
      "Tilo joins and takes notes",
      "Shares notes with attendees after",
      "Turn action items into pins",
      "Pinned to the Team board with owners",
      "Brief before it starts",
      "15 minutes ahead, in your inbox",
    ])
      expect(d, s).toContain(s);
    expect(
      qa(detail(container), '[role="switch"]').map((s) => s.getAttribute("aria-checked")),
    ).toEqual(["true", "true", "true"]);
  });
});

describe("WEB_9_agenda_boards: pins", () => {
  it("WEB_9_agenda_style_toggle_groups_the_pins", async () => {
    const { container } = await renderAgenda();
    click(byText(container, '[role="radio"]', "Grouped"));
    const team = q(container, '[data-board="team"]');
    for (const s of ["TILO SUGGESTS · 1", "NEEDS SOMEONE · 2", "THIS WEEK · 4", "DONE · 1"])
      expect(text(team), s).toContain(s);
    byText(team, "button", "Pin");
    expect(q(team, "input").getAttribute("aria-label")).toBe("Pin to Team board");
    click(byText(container, '[role="radio"]', "Pinboard"));
    expect(text(team)).not.toContain("NEEDS SOMEONE");
  });

  it("WEB_9_agenda_pin_something_adds_a_note_and_ignores_blank_input", async () => {
    const { container } = await renderAgenda();
    const team = q(container, '[data-board="team"]');
    const input = q<HTMLInputElement>(team, "input");
    click(byText(team, "button", "Pin it"));
    expect(text(team)).toContain("6 open");
    type(input, "  Order name tags ");
    click(byText(team, "button", "Pin it"));
    expect(text(team)).toContain("Order name tags");
    expect(text(team)).toContain("Added just now");
    expect(text(team)).toContain("Alex · just now");
    expect(text(team)).toContain("7 open");
    expect(q<HTMLInputElement>(team, "input").value).toBe("");
    type(q<HTMLInputElement>(container, '[data-board="me"] input'), "Call the bank");
    act(() => {
      q(container, '[data-board="me"] input').dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
      );
    });
    expect(text(q(container, '[data-board="me"]'))).toContain("Call the bank");
  });

  it("WEB_9_agenda_check_marks_done_and_back", async () => {
    const { container } = await renderAgenda();
    const p = () => pin(container, "t3");
    click(q(p(), 'button[aria-label="Mark as done"]'));
    expect(text(p())).toContain("Done");
    expect(p().style.opacity).toBe("0.62");
    expect(text(q(container, '[data-board="team"]'))).toContain("5 open");
    click(q(p(), 'button[aria-label="Mark as not done"]'));
    expect(text(p())).toContain("Priya · Thu 1 Oct");
  });

  it("WEB_9_agenda_tilo_suggestions_block_it_dismiss_and_find", async () => {
    const { container, calls } = await renderAgenda();
    const m0 = pin(container, "m0");
    expect(text(m0)).toContain("Block it");
    click(byText(m0, "button", "Block it"));
    toasted(calls, "Blocked 09:30–11:30 on Monday in Google Calendar");
    expect(text(pin(container, "m0"))).toContain("Focus time · Mon 28 Sep");
    expect(text(pin(container, "m0"))).toContain("09:30–11:30, added to your Google Calendar");
    expect(text(pin(container, "m0"))).toContain("Blocked by Tilo");
    click(byText(pin(container, "t0"), "button", "Not now"));
    expect(container.querySelector('[data-pin="t0"]')).toBeNull();
  });

  it("WEB_9_agenda_open_and_review_go_to_the_world", async () => {
    const { container, calls } = await renderAgenda();
    click(byText(pin(container, "m2"), "button", "Open"));
    expect(calls.go).toHaveBeenCalledWith("world", { id: "invoice" });
    click(byText(pin(container, "t1"), "button", "Review and approve"));
    expect(calls.go).toHaveBeenCalledWith("world", { id: "k1" });
    click(q(pin(container, "t1"), 'button[aria-label="Mark as done"]'));
    expect(calls.go).toHaveBeenCalledTimes(3);
    expect(calls.decide).not.toHaveBeenCalled();
  });
});

describe("WEB_9_agenda_week: the calendar", () => {
  it("WEB_9_agenda_calendar_filters_and_weekend", async () => {
    const { container } = await renderAgenda();
    const week = region(container, "This week");
    event(container, "read");
    click(byText(week, "button", "Tilo"));
    expect(container.querySelector('[data-event="read"]')).toBeNull();
    expect(byText(week, "button", "Tilo").getAttribute("aria-pressed")).toBe("false");
    expect(container.querySelector('[data-event="run"]')).toBeNull();
    click(byText(week, "button", "Weekend"));
    expect(text(week)).toContain("This week · 21–27 September");
    expect(text(week)).toContain("SAT");
    event(container, "run");
  });

  it("WEB_9_agenda_picking_an_event_fills_the_detail", async () => {
    const { container } = await renderAgenda();
    click(event(container, "nl"));
    const d = text(detail(container));
    for (const s of [
      "NOTES BY TILO",
      "Agreed the NDA wording, pending Jin’s final read.",
      "FOLLOW-UPS",
      "Jin confirms NDA wording",
      "Pinned to Team board · due Fri",
      "Done by Tilo · Tue 14:20",
    ])
      expect(d, s).toContain(s);
    expect(d).not.toContain("Tilo joins and takes notes");
    click(event(container, "gym"));
    expect(text(detail(container))).toContain("No notes for this one.");
  });

  it("WEB_9_agenda_ask_tilo_for_a_brief_and_the_switches", async () => {
    const { container, calls } = await renderAgenda();
    click(event(container, "read"));
    click(byText(detail(container), "button", "Ask Tilo for a brief"));
    toasted(calls, "Tilo will brief you 15 minutes before Read Tilo’s brief");
    expect(text(detail(container))).toContain("Queued · arrives 15 min before");
    click(event(container, "sync"));
    click(q(detail(container), '[role="switch"]'));
    toasted(calls, "Tilo won’t join this one");
    expect(text(region(container, "This week"))).toContain("Tilo joins 3 still to come");
    click(q(detail(container), '[role="switch"]'));
    toasted(calls, "Tilo will join Supplier sync · Northline");
  });

  it("WEB_9_agenda_find_a_time_books_a_slot_and_pins_it", async () => {
    const { container, calls } = await renderAgenda();
    const week = region(container, "This week");
    click(byText(container, "button", "Find a time"));
    expect(text(week)).toContain("K1 Level 3 gate review · 30 min · Alex, Jin, Priya, Tom");
    expect(text(week)).toContain("Tilo checked all four calendars. Pick a dashed slot to book it.");
    expect(qa(week, "[data-slot]").map((s) => s.textContent)).toEqual([
      "16:00 · all free",
      "09:30 · all free",
      "14:00 · all free",
    ]);
    click(byText(week, "button", "Cancel"));
    expect(qa(week, "[data-slot]")).toHaveLength(0);
    click(byText(container, "button", "Find a time"));
    click(qa(week, "[data-slot]")[0] as HTMLElement);
    await settle();
    toasted(calls, "Booked Thu 16:00. Invites sent from Google Calendar");
    expect(qa(week, "[data-slot]")).toHaveLength(0);
    expect(container.querySelector('[data-pin="t0"]')).toBeNull();
    expect(text(pin(container, "tg"))).toContain("K1 gate review booked");
    expect(text(pin(container, "tg"))).toContain("Thu 16:00. Invites sent to Jin, Priya and Tom.");
    expect(text(detail(container))).toContain("K1 gate review");
    expect(text(detail(container))).toContain("Thu 24 Sep · 16:00–16:30 · booked by Tilo");
    expect(text(detail(container))).toContain("Booked by Tilo");
    click(byText(container, "button", "Find a time"));
    toasted(calls, "Already booked for Thu 16:00");
  });

  it("WEB_9_agenda_narrow_width_stacks_the_detail_under_the_calendar", async () => {
    const wide = await renderAgenda({ vw: 1440 });
    const cols = (c: HTMLElement) => q(c, "[data-week-grid]").style.gridTemplateColumns;
    expect(cols(wide.container)).toBe("minmax(0,1fr) 340px");
    cleanup();
    const narrow = await renderAgenda({ vw: 900 });
    expect(cols(narrow.container)).toBe("minmax(0,1fr)");
  });
});

describe("WEB_9_agenda_decide: every approval goes through app.decide(key)", () => {
  it("WEB_9_agenda_the_depot_pin_follows_dec", async () => {
    const { container, decideFromOutside, calls } = await renderAgenda();
    expect(text(pin(container, "t1"))).toContain("£3,420 for 6 test laptops · K1 electric scooter");
    decideFromOutside("depot");
    const t1 = text(pin(container, "t1"));
    expect(t1).toContain("Approved · £3,420 · K1 electric scooter");
    expect(t1).toContain("Done");
    expect(t1).not.toContain("Review and approve");
    expect(text(q(container, '[data-board="team"]'))).toContain("5 open");
    expect(calls.decide).not.toHaveBeenCalled();
  });

  it("WEB_9_agenda_the_gate_brief_reads_the_depot_decision", async () => {
    const first = await renderAgenda();
    click(byText(first.container, "button", "Find a time"));
    click(qa(region(first.container, "This week"), "[data-slot]")[0] as HTMLElement);
    await settle();
    expect(text(detail(first.container))).toContain(
      "Laptop Depot budget is still waiting for sign-off.",
    );
    first.decideFromOutside("depot");
    expect(text(detail(first.container))).toContain("Laptop Depot budget was approved today.");
  });
});

describe("WEB_9_agenda_honesty_and_states", () => {
  it("WEB_9_agenda_marks_fixture_data_and_never_hides_it", async () => {
    const { container } = await renderAgenda();
    expect(q(container, "[data-park-agenda]").getAttribute("data-source")).toBe("fixture");
  });

  it("WEB_9_agenda_not_built_shows_not_connected_yet_and_no_pins", async () => {
    const api = {
      ...createFixtureApi(),
      getAgenda: () => Promise.reject(new NotBuilt("getAgenda")),
    };
    const { container } = await renderAgenda({ api });
    expect(text(container)).toContain("Not connected yet");
    expect(text(container)).not.toContain("Book the K1 Level 3 gate review");
    expect(container.querySelector("[data-event]")).toBeNull();
  });

  it("WEB_9_agenda_logs_nothing_to_the_console_in_day_or_night", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    for (const time of ["day", "night"] as const) {
      const { container } = await renderAgenda({ time });
      expect(container.querySelector(`[data-time="${time}"]`)).not.toBeNull();
      click(byText(container, '[role="radio"]', "Grouped"));
      click(byText(container, "button", "Weekend"));
      await settle();
      cleanup();
    }
    expect(err).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
  });
});
