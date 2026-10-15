// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { meetingBriefApi } from "../../api/live/meetingBrief";
import { MeetingBrief } from "./MeetingBrief";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const doc = {
  v: "1.0",
  meeting_id: "mt_a",
  generated_at: "2026-10-16T02:00:00Z",
  flagged: false,
  agenda_points: [
    {
      title: "Launch date",
      minutes: 15,
      talk_points: [{ text: "Confirm the date", evidence: [{ kind: "agenda", index: 0 }] }],
    },
  ],
  carry_over: [
    {
      text: "Review the vendor contract",
      kind: "open_action",
      from_meeting: "mt_previous",
      item: "ai2",
    },
  ],
};
const http = () => ({
  getJson: vi.fn(async (path: string) =>
    path.endsWith("/brief") ? doc : { id: "mt_a", brief_requested: false, auto_report: false },
  ),
  postJson: vi.fn(async () => doc),
  sendJson: vi.fn(async (_method: string, _path: string, body: unknown) => ({
    id: "mt_a",
    ...(body as object),
  })),
});
const noBrief = () => {
  const client = http();
  client.getJson.mockImplementation(async (path) => {
    if (path.endsWith("/brief"))
      throw new TiloApiError("not_ready", 404, false, false, "not_ready");
    return { id: "mt_a", brief_requested: false, auto_report: false };
  });
  return client;
};
const show = async (client = http()) => {
  const m = mount(<MeetingBrief id="mt_a" api={meetingBriefApi(client)} />);
  await act(async () => undefined);
  return m;
};
const checked = (root: HTMLElement, label: string) =>
  root.querySelector(`[aria-label="${label}"]`)?.getAttribute("aria-checked");
const press = async (root: HTMLElement, name: string) => {
  const button = [...root.querySelectorAll("button")].find((b) => b.textContent?.includes(name));
  if (!button) throw new Error(`Missing button ${name}`);
  await act(async () => button.click());
};

it("MB_T2 renders agenda, cited talk points and carry-over without console errors", async () => {
  const warn = vi.spyOn(console, "error").mockImplementation(() => undefined);
  const m = await show();
  expect(m.container.textContent).toContain("Launch date");
  expect(m.container.textContent).toContain("Confirm the date");
  expect(m.container.textContent).toContain("Agenda point 1");
  expect(m.container.textContent).toContain("Review the vendor contract");
  expect(warn).not.toHaveBeenCalled();
});

it("MB_T2 not_ready is empty until an explicit POST, with no automatic brief promise", async () => {
  const client = noBrief();
  const m = await show(client);
  expect(m.container.textContent).toContain("No brief yet");
  expect(m.container.textContent).toContain("A brief is made only when you ask");
  expect(client.postJson).not.toHaveBeenCalled();
  await press(m.container, "Ask Tilo for a brief");
  expect(client.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/brief", {});
  expect(m.container.textContent).toContain("Confirm the date");
});

it("MB_T2 shows flagged notice and 429/503 generation messages", async () => {
  const client = noBrief();
  client.postJson
    .mockRejectedValueOnce(new TiloApiError("allowance_capped", 429, false))
    .mockRejectedValueOnce(new TiloApiError("try_again", 503, true))
    .mockResolvedValueOnce({
      ...doc,
      flagged: true,
      agenda_points: doc.agenda_points.map((point) => ({ ...point, talk_points: [] })),
    });
  const m = await show(client);
  await press(m.container, "Ask Tilo for a brief");
  expect(m.container.textContent).toContain("allowance");
  await press(m.container, "Ask Tilo for a brief");
  expect(m.container.textContent).toContain("Try again");
  await press(m.container, "Ask Tilo for a brief");
  expect(m.container.textContent).toContain("flagged");
});

it("MB_T2 PATCHes both owner switches and rolls back a failed write", async () => {
  const client = http();
  client.sendJson.mockRejectedValueOnce(new TiloApiError("try_again", 503, true));
  const m = await show(client);
  await press(m.container, "Brief before it starts");
  expect(checked(m.container, "Brief before it starts")).toBe("false");
  expect(m.container.textContent).toContain("could not be saved");
  await press(m.container, "Brief before it starts");
  await press(m.container, "Email me a wrap-up report");
  expect(client.sendJson).toHaveBeenCalledWith("PATCH", "/v1/meetings/mt_a", {
    brief_requested: true,
  });
  expect(client.sendJson).toHaveBeenCalledWith("PATCH", "/v1/meetings/mt_a", { auto_report: true });
  expect(checked(m.container, "Brief before it starts")).toBe("true");
  expect(checked(m.container, "Email me a wrap-up report")).toBe("true");
});
