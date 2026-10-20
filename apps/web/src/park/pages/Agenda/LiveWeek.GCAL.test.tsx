// @vitest-environment happy-dom
// GCAL: the live week reads like Google Calendar: Month Year title, Create, My calendars filters, an event popover
// card, an "Add title" quick-create, and one calm line (no empty box) when the range has no events.
import { act } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import type { AgendaPlateRow } from "../../api/types";
import { LiveWeek } from "./LiveWeek";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 9, 21, 10, 30));
});

const entry = (id: string, title: string, hour: number): AgendaPlateRow => ({
  ref: { kind: "calendar_entry", id },
  title,
  at: new Date(2026, 9, 21, hour, 0).toISOString(),
  due: null,
  from: "Google Calendar",
  group: "calendar",
});
const props = (rows: AgendaPlateRow[], onSchedule = vi.fn()) => ({
  rows,
  parked: [],
  today: "2026-10-21",
  meetings: [],
  onSchedule,
  host: null,
  minutes: null,
  getJson: null,
});

it("GCAL_title_is_month_and_year_with_a_create_button", () => {
  const m = mount(<LiveWeek {...props([])} />);
  expect(m.container.querySelector(".cx-agenda-weektitle h2")?.textContent).toMatch(/October/);
  expect(m.container.querySelector(".cx-agenda-create")?.textContent).toBe("+ Create");
});

it("GCAL_my_calendars_checkbox_hides_that_calendars_events", async () => {
  const m = mount(<LiveWeek {...props([entry("a", "Project review", 9)])} />);
  expect(m.container.querySelectorAll(".cx-agenda-event")).toHaveLength(1);
  const work = m.container.querySelector<HTMLInputElement>(
    '[aria-label="My calendars"] [data-event-tone="work"] input',
  );
  await act(async () => work?.click());
  expect(m.container.querySelectorAll(".cx-agenda-event")).toHaveLength(0);
});

it("GCAL_empty_week_shows_one_calm_line_and_still_draws_the_grid", () => {
  const m = mount(<LiveWeek {...props([])} />);
  expect(m.container.querySelector(".cx-agenda-emptyline")?.textContent).toBe(
    "No events this week. Connect Google Calendar or press Create.",
  );
  expect(m.container.querySelectorAll("[data-week-slot]").length).toBeGreaterThan(0);
});

it("GCAL_clicking_an_event_opens_a_popover_card_and_escape_closes_it", async () => {
  const m = mount(<LiveWeek {...props([entry("a", "Project review", 9)])} />);
  await act(async () => m.container.querySelector<HTMLButtonElement>(".cx-agenda-event")?.click());
  const card = m.container.querySelector('[aria-label="Event details"]');
  expect(card?.textContent).toContain("Project review");
  expect(card?.querySelector(".cx-agenda-popdot")).not.toBeNull();
  await act(async () => {
    card?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
  expect(m.container.querySelector('[aria-label="Event details"]')).toBeNull();
});

it("GCAL_quick_create_passes_the_typed_title_to_schedule", async () => {
  const onSchedule = vi.fn();
  const m = mount(<LiveWeek {...props([], onSchedule)} />);
  await act(async () => m.container.querySelector<HTMLButtonElement>("[data-week-slot]")?.click());
  const input = m.container.querySelector<HTMLInputElement>('input[aria-label="Add title"]');
  expect(input).not.toBeNull();
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, "Planning");
    input?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const invite = [...m.container.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Invite others"),
  );
  await act(async () => invite?.click());
  expect(onSchedule.mock.calls[0]?.[2]).toBe("Planning");
});
