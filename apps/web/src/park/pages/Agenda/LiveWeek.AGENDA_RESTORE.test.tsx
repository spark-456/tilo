// @vitest-environment happy-dom
// AGENDA-RESTORE: the live week keeps the design handoff's calendar look: a 07:00 to 21:00 hour grid, a labelled
// now-line, tone-coloured blocks that show title and time, overlapping blocks side by side, Today's calendar.
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

const entry = (id: string, title: string, hour: number, minute = 0): AgendaPlateRow => ({
  ref: { kind: "calendar_entry", id },
  title,
  at: new Date(2026, 9, 21, hour, minute).toISOString(),
  due: null,
  from: "Google Calendar",
  group: "calendar",
});
const props = (rows: AgendaPlateRow[], compact = false) => ({
  rows,
  parked: [],
  today: "2026-10-21",
  meetings: [],
  onSchedule: vi.fn(),
  host: null,
  minutes: null,
  getJson: null,
  compact,
});

it("AGENDA_RESTORE_hour_grid_runs_from_07_to_21_with_a_labelled_now_line", () => {
  const m = mount(<LiveWeek {...props([])} />);
  const labels = [...m.container.querySelectorAll(".cx-agenda-hours span")].map(
    (n) => n.textContent,
  );
  expect(labels[0]).toBe("07:00");
  expect(labels.at(-1)).toBe("21:00");
  expect(labels).toHaveLength(15);
  const now = m.container.querySelector('[role="img"][aria-label="Current time"]');
  expect(now).not.toBeNull();
  expect(now?.tagName).toBe("SPAN");
});

it("AGENDA_RESTORE_blocks_show_title_and_time_in_their_tone", () => {
  const m = mount(<LiveWeek {...props([entry("a", "Project review", 9, 0)])} />);
  const block = m.container.querySelector<HTMLButtonElement>(".cx-agenda-event");
  expect(block?.getAttribute("data-event-tone")).toBe("work");
  expect(block?.querySelector("strong")?.textContent).toBe("Project review");
  expect(block?.querySelector("span")?.textContent).toMatch(/9:00|09:00/);
  // A calendar entry has no end: the block is the 44 px tap target, its end is not invented.
  expect(Number.parseFloat(block?.style.height ?? "0")).toBeGreaterThanOrEqual(44);
});

it("AGENDA_RESTORE_overlapping_blocks_sit_side_by_side", () => {
  const m = mount(
    <LiveWeek {...props([entry("a", "Stand-up", 9, 0), entry("b", "Design review", 9, 15)])} />,
  );
  const [first, second] = [...m.container.querySelectorAll<HTMLButtonElement>(".cx-agenda-event")];
  expect(first?.style.width).toBe("calc(50% - 6px)");
  expect(second?.style.width).toBe("calc(50% - 6px)");
  expect(first?.style.left).not.toBe(second?.style.left);
});

it("AGENDA_RESTORE_today_calendar_lists_todays_entries_in_time_order", () => {
  const m = mount(
    <LiveWeek {...props([entry("b", "Customer call", 14, 30), entry("a", "Stand-up", 9, 0)])} />,
  );
  const today = m.container.querySelector('[aria-label="Today\'s calendar"]');
  expect(today?.querySelector("h2")?.textContent).toBe("Today's calendar");
  expect([...(today?.querySelectorAll("li strong") ?? [])].map((n) => n.textContent)).toEqual([
    "Stand-up",
    "Customer call",
  ]);
  expect(today?.querySelector("a")?.textContent).toBe("Check Google Calendar");
});

it("AGENDA_RESTORE_a_phone_opens_on_one_day_and_the_month_view_has_no_plain_div_label", () => {
  const phone = mount(<LiveWeek {...props([], true)} />);
  const scroll = phone.container.querySelector('[aria-label="Week time slots"]');
  expect(scroll?.getAttribute("data-view")).toBe("day");
  const month = phone.container.querySelector('[aria-label="Month calendar"]');
  expect(month?.tagName).toBe("SECTION");
});
