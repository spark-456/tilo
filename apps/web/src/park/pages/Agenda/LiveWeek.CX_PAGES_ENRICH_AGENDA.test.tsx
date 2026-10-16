// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import type { MeetingHostApi } from "../../api/live/meetingHost";
import { LiveWeek } from "./LiveWeek";
import { ScheduleWithOthersDialog } from "./ScheduleWithOthersDialog";

afterEach(cleanup);

const props = (onSchedule = vi.fn()) => ({
  rows: [],
  parked: [],
  meetings: [],
  onSchedule,
  host: null,
  minutes: null,
  getJson: null,
});

it("CX_PAGES_ENRICH_AGENDA_drag_prefills_schedule_dialog_with_snapped_time_and_length", async () => {
  const onSchedule = vi.fn();
  const m = mount(<LiveWeek {...props(onSchedule)} />);
  const slots = m.container.querySelectorAll<HTMLButtonElement>("[data-week-slot]");
  await act(async () => {
    slots[0]?.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    slots[2]?.dispatchEvent(new Event("pointermove", { bubbles: true }));
    slots[2]?.dispatchEvent(new Event("pointerup", { bubbles: true }));
  });
  expect(onSchedule).toHaveBeenCalledTimes(1);
  const [start, length] = onSchedule.mock.calls[0] as [string, number];
  expect(new Date(start).getMinutes() % 15).toBe(0);
  expect(length).toBe(45);

  const api = {
    people: vi.fn(async () => ({ you: "person", people: [] })),
  } as unknown as MeetingHostApi;
  let dialog: ReturnType<typeof mount>;
  await act(async () => {
    dialog = mount(
      <ScheduleWithOthersDialog
        api={api}
        start={start}
        minutes={length}
        onClose={() => undefined}
        onScheduled={() => undefined}
      />,
    );
    await Promise.resolve();
  });
  const dateField = dialog.container.querySelector<HTMLInputElement>('input[name="start"]');
  expect(dateField?.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  expect(dialog.container.querySelector("select")?.value).toBe("45");
});

it("CX_PAGES_ENRICH_AGENDA_meeting_block_opens_details_and_recorded_brief", async () => {
  const getJson = vi.fn(async () => ({
    meeting_id: "mt_meeting1",
    agenda_points: [{ title: "Planning", talk_points: [{ text: "Confirm the launch date." }] }],
    carry_over: [],
  }));
  const meeting = {
    id: "mt_meeting1",
    title: "Review planning",
    status: "scheduled",
    at: new Date(new Date().setHours(10, 0, 0, 0)).toISOString(),
    end: new Date(new Date().setHours(10, 30, 0, 0)).toISOString(),
    source: "bot",
    body: null,
    scope: null,
    setter: null,
    personalUser: null,
  };
  const m = mount(<LiveWeek {...props()} meetings={[meeting]} getJson={getJson} />);
  const block = [...m.container.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Review planning"),
  );
  expect(block).toBeDefined();
  await act(async () => block?.click());
  const briefButton = [...m.container.querySelectorAll("button")].find(
    (button) => button.textContent === "Tilo brief me",
  );
  await act(async () => briefButton?.click());
  await act(async () => undefined);
  const card = m.container.querySelector('[aria-label="Event details"]');
  expect(card?.textContent).toContain("Review planning");
  expect(card?.textContent).toContain("Confirm the launch date.");
  expect(getJson).toHaveBeenCalledWith("/v1/meetings/mt_meeting1/brief");
});
