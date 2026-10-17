// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { MeetingBrief } from "./MeetingBrief";

afterEach(cleanup);

it("CX_PAGES_ENRICH_AGENDA_shows_only_a_recorded_meeting_brief", async () => {
  const getJson = vi.fn(async () => ({
    meeting_id: "mt_a",
    agenda_points: [{ title: "Launch date", talk_points: [{ text: "Confirm the date." }] }],
    carry_over: [{ text: "Check the vendor contract." }],
  }));
  const m = mount(<MeetingBrief id="mt_a" getJson={getJson} />);
  await act(async () => undefined);
  expect(getJson).toHaveBeenCalledWith("/v1/meetings/mt_a/brief");
  expect(m.container.textContent).toContain("Confirm the date.");
  expect(m.container.textContent).toContain("Check the vendor contract.");
});

it("CX_PAGES_ENRICH_AGENDA_hides_an_unready_meeting_brief", async () => {
  const m = mount(
    <MeetingBrief id="mt_a" getJson={async () => Promise.reject(new Error("not_ready"))} />,
  );
  await act(async () => undefined);
  expect(m.container.textContent).toBe("");
});

it("test_FT_SUP_3_hides_a_brief_when_api_answers_brief_null", async () => {
  const getJson = vi.fn(async () => ({ brief: null }));
  const m = mount(<MeetingBrief id="mt_a" getJson={getJson} />);
  await act(async () => undefined);
  expect(getJson).toHaveBeenCalledWith("/v1/meetings/mt_a/brief");
  expect(m.container.textContent).toBe("");
});
