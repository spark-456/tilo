// @vitest-environment happy-dom
// UX-AUDIT: the live calendar's Delete asks once before it removes a scheduled meeting, and Previous / Next name the
// view they step through (day, week or month).
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import type { MeetingHostApi } from "../../api/live/meetingHost";
import type { PeopleRow } from "../../api/live/peopleLists";
import { LiveWeek } from "./LiveWeek";

afterEach(cleanup);

const at = (hour: number) => {
  const d = new Date();
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
};

const meeting: PeopleRow = {
  id: "m_1",
  title: "Supplier review",
  status: "scheduled",
  at: at(10),
  body: null,
  scope: null,
  setter: null,
  personalUser: null,
  source: null,
  end: at(11),
};

const buttonNamed = (root: HTMLElement, name: string) =>
  [...root.querySelectorAll("button")].find((b) => b.textContent?.trim() === name);

it("UX_AUDIT_live_calendar_delete_asks_before_removing_a_meeting", async () => {
  const remove = vi.fn(async () => undefined);
  const onDeleted = vi.fn();
  const host = { remove } as unknown as MeetingHostApi;
  const m = mount(
    <LiveWeek
      rows={[]}
      parked={[]}
      meetings={[meeting]}
      onSchedule={vi.fn()}
      host={host}
      minutes={null}
      getJson={null}
      onDeleted={onDeleted}
    />,
  );
  const event = m.container.querySelector<HTMLButtonElement>(".cx-agenda-event");
  expect(event, "the meeting is on the calendar").not.toBeNull();
  await act(async () => event?.click());

  await act(async () => buttonNamed(m.container, "Delete")?.click());
  expect(remove, "the first click only asks").not.toHaveBeenCalled();
  expect(m.container.textContent).toContain("Delete this meeting? Tilo will not join it.");

  await act(async () => buttonNamed(m.container, "Keep it")?.click());
  expect(remove).not.toHaveBeenCalled();
  expect(buttonNamed(m.container, "Delete"), "Keep it puts Delete back").toBeDefined();

  await act(async () => buttonNamed(m.container, "Delete")?.click());
  await act(async () => buttonNamed(m.container, "Yes, delete it")?.click());
  expect(remove).toHaveBeenCalledWith("m_1");
  expect(onDeleted).toHaveBeenCalledTimes(1);
});

it("UX_AUDIT_live_calendar_previous_and_next_name_the_current_view", async () => {
  const m = mount(
    <LiveWeek
      rows={[]}
      parked={[]}
      meetings={[]}
      onSchedule={vi.fn()}
      host={null}
      minutes={null}
      getJson={null}
    />,
  );
  expect(m.container.querySelector('button[aria-label="Previous week"]')).not.toBeNull();
  await act(async () => buttonNamed(m.container, "Day")?.click());
  expect(m.container.querySelector('button[aria-label="Previous day"]')).not.toBeNull();
  expect(m.container.querySelector('button[aria-label="Next day"]')).not.toBeNull();
  await act(async () => buttonNamed(m.container, "Month")?.click());
  expect(m.container.querySelector('button[aria-label="Next month"]')).not.toBeNull();
});
