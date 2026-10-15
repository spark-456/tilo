// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { HttpClient } from "../../../api/http";
import { meetingMinutesApi } from "../../api/live/meetingMinutes";
import { MeetingMinutes } from "./MeetingMinutes";

afterEach(cleanup);
const doc = {
  meeting_id: "mt_wrap",
  summary: [{ text: "The returned summary" }],
  decisions: [{ text: "Proceed" }],
  action_items: [{ text: "Check dates", state: "proposed" }],
};
const http = () => ({
  getJson: vi.fn(async (path: string) =>
    path.endsWith("/minutes") ? doc : { id: "mt_wrap", attendees: [], minutes_confirmed_by: null },
  ),
  postJson: vi.fn(async (_path: string, _body: unknown) => ({
    id: "mt_wrap",
    status: "minuted",
    minutes: "artifact-ref",
  })),
});
const wrap = (root: HTMLElement) =>
  Array.from(root.querySelectorAll("button")).find((button) => button.textContent === "Wrap up");
const requiredWrap = (root: HTMLElement) => {
  const button = wrap(root);
  if (!button) throw new Error("Missing Wrap up button");
  return button;
};

it("test_FR_MTG_06_wrap_up_click_reads_minutes_and_keeps_confirm_explicit", async () => {
  const client = http();
  const mounted = mount(
    <MeetingMinutes id="mt_wrap" status="ended" api={meetingMinutesApi(client)} />,
  );
  expect(mounted.container.querySelectorAll("button")).toHaveLength(1);
  expect(wrap(mounted.container)).toBeDefined();
  expect(client.postJson).not.toHaveBeenCalled();
  expect(client.getJson).not.toHaveBeenCalled();
  await act(async () => click(requiredWrap(mounted.container)));
  expect(client.postJson.mock.calls).toEqual([["/v1/meetings/mt_wrap/analyze-minutes", {}]]);
  expect(client.getJson.mock.calls).toEqual([
    ["/v1/meetings/mt_wrap"],
    ["/v1/meetings/mt_wrap/minutes"],
  ]);
  expect(mounted.container.textContent).toContain("The returned summary");
  expect(mounted.container.textContent).toContain("Check dates (proposed)");
  expect(mounted.container.textContent).toContain("Confirm these minutes");
  expect(mounted.container.textContent).not.toContain("Draft follow-up");
  expect(wrap(mounted.container)).toBeUndefined();
});

it("test_FR_MTG_06_wrap_up_busy_disables_repeat_click_until_minutes_are_read", async () => {
  const client = http();
  let finish!: (reply: { id: string; status: string; minutes: string }) => void;
  client.postJson.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const mounted = mount(
    <MeetingMinutes id="mt_wrap" status="ended" api={meetingMinutesApi(client)} />,
  );
  const button = requiredWrap(mounted.container);
  click(button);
  expect(button.disabled).toBe(true);
  expect(button.textContent).toBe("Writing the minutes...");
  click(button);
  expect(client.postJson).toHaveBeenCalledTimes(1);
  await act(async () => finish({ id: "mt_wrap", status: "minuted", minutes: "artifact-ref" }));
  expect(mounted.container.textContent).not.toContain("Writing the minutes...");
  expect(mounted.container.textContent).toContain("The returned summary");
});

it.each([403, 404, 409])("test_FR_MTG_06_wrap_up_flag_off_%i_is_visible", async (status) => {
  const fetcher = vi.fn(
    async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ code: "not_found" }), { status }),
  );
  const client = new HttpClient({
    baseUrl: "https://api.example.test",
    authToken: async () => "owner",
    fetch: fetcher,
  });
  const mounted = mount(
    <MeetingMinutes id="mt_wrap" status="ended" api={meetingMinutesApi(client)} />,
  );
  expect(fetcher).not.toHaveBeenCalled();
  await act(async () => click(requiredWrap(mounted.container)));
  expect(mounted.container.querySelector('[role="alert"]')?.textContent).toBe(
    "Meeting minutes are switched off",
  );
  expect(mounted.container.querySelectorAll("button")).toHaveLength(1);
  expect(wrap(mounted.container)?.disabled).toBe(false);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("test_FR_MTG_06_wrap_up_other_errors_show_client_message_without_read_or_send", async () => {
  const fetcher = vi.fn(
    async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ code: "allowance_capped" }), { status: 429 }),
  );
  const client = new HttpClient({
    baseUrl: "https://api.example.test",
    authToken: async () => "owner",
    fetch: fetcher,
  });
  const mounted = mount(
    <MeetingMinutes id="mt_wrap" status="ended" api={meetingMinutesApi(client)} />,
  );
  await act(async () => click(requiredWrap(mounted.container)));
  expect(mounted.container.querySelector('[role="alert"]')?.textContent).toBe(
    "Your allowance is used up. Try again when it resets.",
  );
  expect(mounted.container.textContent).not.toContain("Confirm these minutes");
  expect(fetcher.mock.calls.every(([, init]) => init?.method === "POST")).toBe(true);
});

it("test_FR_MTG_06_wrap_up_status_changes_never_start_analysis", () => {
  const client = http();
  const api = meetingMinutesApi(client);
  const mounted = mount(<MeetingMinutes id="mt_wrap" status="live" api={api} />);
  expect(mounted.container.textContent).toBe("");
  mounted.render(<MeetingMinutes id="mt_wrap" status="ended" api={api} />);
  expect(wrap(mounted.container)).toBeDefined();
  mounted.render(<MeetingMinutes id="mt_wrap" status="minuted" api={api} />);
  expect(wrap(mounted.container)).toBeUndefined();
  expect(mounted.container.textContent).toContain("Review minutes");
  expect(client.getJson).not.toHaveBeenCalled();
  expect(client.postJson).not.toHaveBeenCalled();
});
