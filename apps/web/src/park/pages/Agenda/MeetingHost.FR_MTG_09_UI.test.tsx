// @vitest-environment happy-dom
// FR-MTG-01 / FR-MTG-09 / FR-MTG-10 (ui/MEETING-HOST-UI): host a Tilo-notetaker Meet from the Agenda, send Tilo to it.
// The API is mocked; every state shown is one a reply returned.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { meetingHostApi } from "../../api/live/meetingHost";
import {
  NOTICE_TEXT,
  NOTICE_VERSION,
  attendOffered,
  hostFormError,
  meetingBody,
} from "../../shared/hostMeetingRules";
import { HostMeeting, MeetingAttend } from "./MeetingHost";
import { PeopleLists } from "./PeopleLists";

vi.mock("../../../api/ClientProvider", () => ({
  API_URL: "https://api.example.test",
  authToken: async () => "owner-token",
  appCheckToken: async () => "app-check",
  sessionView: { demo: () => false },
}));

afterEach(cleanup);
const NOW = Date.parse("2026-10-15T10:00:00Z");
const form = { title: "Q4 plan", start: "2026-10-17T18:00", minutes: 30, attested: true };

describe("FR_MTG_09_UI form rules", () => {
  it("FR_MTG_09_UI_a_start_must_be_future_length_at_most_60_and_the_notice_ticked", () => {
    expect(hostFormError(form, NOW)).toBeNull();
    expect(hostFormError({ ...form, start: "2026-10-13T09:00" }, NOW)).toMatch(/future/);
    expect(hostFormError({ ...form, start: "" }, NOW)).toMatch(/starts/);
    expect(hostFormError({ ...form, minutes: 90 }, NOW)).toMatch(/15, 30, 45 or 60/);
    expect(hostFormError({ ...form, attested: false }, NOW)).toMatch(/notice/);
    expect(hostFormError({ ...form, title: "  " }, NOW)).toMatch(/title/);
    expect(hostFormError({ ...form, title: "see https://x.test" }, NOW)).toMatch(/links/);
  });
  it("FR_MTG_01_UI_b_body_is_the_contract_shape_with_attest_notice_and_utc_window", () => {
    const body = meetingBody(form);
    expect(Object.keys(body).sort()).toEqual(
      ["attendees", "attest", "notice_version", "scheduled", "source", "title"].sort(),
    );
    expect(body).toMatchObject({
      attest: true,
      notice_version: NOTICE_VERSION,
      source: "bot",
      attendees: [],
    });
    const { start, end } = body.scheduled;
    expect(start).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:00\.000Z$/);
    expect(Date.parse(end) - Date.parse(start)).toBe(30 * 60_000);
  });
  it("FR_MTG_09_UI_c_attend_is_offered_from_10_minutes_before_until_the_end_of_a_scheduled_bot_meeting", () => {
    const row = {
      source: "bot",
      status: "scheduled",
      at: "2026-10-15T11:00:00.000Z",
      end: "2026-10-15T11:30:00.000Z",
    };
    const t = (iso: string) => Date.parse(iso);
    expect(attendOffered(row, t("2026-10-15T10:49:00Z"))).toBe(false);
    expect(attendOffered(row, t("2026-10-15T10:50:00Z"))).toBe(true);
    expect(attendOffered(row, t("2026-10-15T11:30:00Z"))).toBe(true);
    expect(attendOffered(row, t("2026-10-15T11:31:00Z"))).toBe(false);
    expect(attendOffered({ ...row, status: "ended" }, t("2026-10-15T11:00:00Z"))).toBe(false);
    expect(attendOffered({ ...row, source: "upload" }, t("2026-10-15T11:00:00Z"))).toBe(false);
  });
});

const rig = () => {
  const http = {
    getJson: vi.fn(async () => ({
      join_url: "https://meet.google.com/abc-defg-hij",
      expires_at: "2026-10-15T10:01:00.000Z",
    })),
    postJson: vi.fn(
      async (path: string, _body?: unknown, _headers?: Record<string, string>): Promise<unknown> =>
        path === "/v1/meetings" ? { id: "mt_new" } : { id: "mt_new", world_id: "w_new" },
    ),
    hostMeeting: vi.fn(async () => ({ world_id: "w_new" })),
  };
  return { http, api: meetingHostApi(http) };
};
const set = (el: Element, value: string, evt = "input") =>
  act(() => {
    const proto = el instanceof HTMLSelectElement ? HTMLSelectElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, "value")?.set?.call(el, value);
    el.dispatchEvent(new Event(evt, { bubbles: true }));
  });
const btn = (root: HTMLElement, text: string) =>
  Array.from(root.querySelectorAll("button")).find((b) => b.textContent === text);
const press = async (root: HTMLElement, text: string) => {
  const b = btn(root, text);
  if (!b) throw new Error(`Missing button: ${text}`);
  await act(async () => click(b));
};
const fill = (root: HTMLElement, f = form) => {
  set(root.querySelector('input[name="title"]') as Element, f.title);
  set(root.querySelector('input[name="start"]') as Element, f.start);
  set(root.querySelector("select") as Element, String(f.minutes), "change");
  if (f.attested) click(root.querySelector('input[type="checkbox"]') as Element);
};
const hostState = (s: "connected" | "available" | "unknown") => async () => s;

describe("FR_MTG_09_UI host a meeting", () => {
  it("FR_MTG_09_UI_d_without_a_connected_meeting_host_the_button_is_a_link_to_connectors", async () => {
    const { api } = rig();
    const m = mount(<HostMeeting api={api} hostState={hostState("available")} now={() => NOW} />);
    await act(async () => undefined);
    expect(btn(m.container, "Host a meeting with Tilo")).toBeUndefined();
    const link = m.container.querySelector("a");
    expect(link?.textContent).toBe("Sign in the meeting host first");
    expect(link?.getAttribute("href")).toBe("/connectors");
  });
  it("FR_MTG_09_UI_e_the_form_needs_the_notice_and_sends_nothing_until_valid", async () => {
    const { api, http } = rig();
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await act(async () => undefined);
    await press(m.container, "Host a meeting with Tilo");
    expect(m.container.textContent).toContain(NOTICE_TEXT);
    fill(m.container, { ...form, attested: false });
    await press(m.container, "Send for approval");
    expect(m.container.querySelector('[role="alert"]')?.textContent).toMatch(/notice/);
    expect(http.postJson).not.toHaveBeenCalled();
    const options = Array.from(m.container.querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["15", "30", "45", "60"]);
  });
  it("FR_MTG_09_UI_f_submit_is_create_then_world_then_host_and_points_to_needs_you", async () => {
    const { api, http } = rig();
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await act(async () => undefined);
    await press(m.container, "Host a meeting with Tilo");
    fill(m.container);
    await press(m.container, "Send for approval");
    expect(http.postJson.mock.calls.map((c) => c[0])).toEqual([
      "/v1/meetings",
      "/v1/meetings/mt_new/world",
    ]);
    expect(http.postJson.mock.calls[0]?.[1]).toMatchObject({
      attest: true,
      notice_version: NOTICE_VERSION,
      source: "bot",
      attendees: [],
    });
    expect(
      (http.postJson.mock.calls[0]?.[2] as Record<string, string>)["Idempotency-Key"],
    ).toBeTruthy();
    expect(http.hostMeeting).toHaveBeenCalledWith("mt_new");
    expect(m.container.textContent).toContain("Approve the invitation in Needs you");
    expect(m.container.querySelector('a[href="/needs-you"]')).not.toBeNull();
  });
  it("FR_MTG_09_UI_g_a_refused_step_is_said_plainly_and_a_retry_resumes_there_not_at_create", async () => {
    const { api, http } = rig();
    http.hostMeeting.mockRejectedValueOnce(
      new TiloApiError("Unreadable", 422, false, true, undefined, false, "MH-02"),
    );
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await act(async () => undefined);
    await press(m.container, "Host a meeting with Tilo");
    fill(m.container);
    await press(m.container, "Send for approval");
    const alert = m.container.querySelector('[role="alert"]')?.textContent ?? "";
    expect(alert).toContain("Choose a future meeting time within the allowed duration.");
    expect(alert).toContain("was created but not hosted");
    expect(m.container.textContent).not.toContain("Approve the invitation");
    expect(http.hostMeeting).toHaveBeenCalledTimes(1); // never retried by itself
    await press(m.container, "Try again");
    expect(http.hostMeeting).toHaveBeenCalledTimes(2);
    expect(http.postJson.mock.calls.filter((c) => c[0] === "/v1/meetings")).toHaveLength(1);
    expect(m.container.textContent).toContain("Approve the invitation in Needs you");
  });
  it("FR_MTG_09_UI_h_a_failed_create_says_nothing_was_created", async () => {
    const { api, http } = rig();
    http.postJson.mockRejectedValueOnce(new TiloApiError("Bad", 422, false, true));
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await act(async () => undefined);
    await press(m.container, "Host a meeting with Tilo");
    fill(m.container);
    await press(m.container, "Send for approval");
    expect(m.container.querySelector('[role="alert"]')?.textContent).toContain(
      "Nothing was created",
    );
    expect(http.hostMeeting).not.toHaveBeenCalled();
  });
});

const row = {
  source: "bot",
  status: "scheduled",
  at: "2026-10-15T10:05:00.000Z",
  end: "2026-10-15T10:35:00.000Z",
};
describe("FR_MTG_10_UI send Tilo to the meeting", () => {
  it("FR_MTG_10_UI_a_no_button_before_the_window_or_for_other_meetings", () => {
    const { api } = rig();
    const early = { ...row, at: "2026-10-15T12:00:00.000Z", end: "2026-10-15T12:30:00.000Z" };
    const m = mount(<MeetingAttend id="mt_a" row={early} api={api} now={() => NOW} />);
    expect(m.container.textContent).toBe("");
  });
  it("FR_MTG_10_UI_b_one_held_request_shows_the_ask_to_join_line_then_the_outcome", async () => {
    const { api, http } = rig();
    let finish: (v: unknown) => void = () => undefined;
    http.postJson.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const onChanged = vi.fn();
    const m = mount(
      <MeetingAttend id="mt_a" row={row} api={api} now={() => NOW} onChanged={onChanged} />,
    );
    await press(m.container, "Send Tilo to the meeting");
    expect(http.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/attend", {});
    expect(m.container.textContent).toContain(
      "Tilo is asking to join as Tilo notetaker. Admit it in Meet. Keep this tab open.",
    );
    expect(btn(m.container, "Send Tilo to the meeting")).toBeUndefined();
    await act(async () => finish({ id: "mt_a", status: "ended", ended_reason: "left_on_request" }));
    expect(m.container.textContent).toContain("Someone typed Tilo leave, so Tilo left.");
    expect(onChanged).toHaveBeenCalledTimes(1);
    expect(http.postJson).toHaveBeenCalledTimes(1);
  });
  it("FR_MTG_10_UI_c_a_refusal_is_said_in_plain_words_and_never_retried", async () => {
    const { api, http } = rig();
    http.postJson.mockRejectedValue(
      new TiloApiError("x", 409, false, true, undefined, false, "not_joinable"),
    );
    const m = mount(<MeetingAttend id="mt_a" row={row} api={api} now={() => NOW} />);
    await press(m.container, "Send Tilo to the meeting");
    expect(m.container.querySelector('[role="alert"]')?.textContent).toContain(
      "This meeting cannot be joined right now.",
    );
    expect(http.postJson).toHaveBeenCalledTimes(1);
  });
  it("FR_MTG_10_UI_d_open_meet_reads_the_link_on_the_click_only_and_checks_its_shape", async () => {
    const { api, http } = rig();
    const m = mount(<MeetingAttend id="mt_a" row={row} api={api} now={() => NOW} />);
    expect(http.getJson).not.toHaveBeenCalled();
    await press(m.container, "Open Meet");
    expect(http.getJson).toHaveBeenCalledWith("/v1/meetings/mt_a/join");
    const a = m.container.querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://meet.google.com/abc-defg-hij");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer");
    http.getJson.mockResolvedValueOnce({
      join_url: "https://evil.test/abc-defg-hij",
      expires_at: "x",
    });
    await press(m.container, "Open Meet");
    expect(m.container.querySelector('[role="alert"]')).not.toBeNull();
  });
});

describe("FR_MTG_09_UI the Agenda's Meetings list", () => {
  it("FR_MTG_09_UI_e_list_offers_host_when_connected_and_send_only_inside_the_window_and_keeps_the_outcome", async () => {
    const now = Date.now();
    const iso = (ms: number) => new Date(ms).toISOString();
    const meeting = (id: string, startOffset: number) => ({
      id,
      title: id,
      status: "scheduled",
      source: "bot",
      scheduled: { start: iso(now + startOffset), end: iso(now + startOffset + 30 * 60_000) },
      created_at: "2026-10-14T00:00:00.000Z",
    });
    const calls: string[] = [];
    const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url).pathname;
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if (path === "/v1/connectors")
        return new Response(
          JSON.stringify({
            connectors: [
              {
                id: "meeting_host",
                name: "Meeting host",
                state: "connected",
                state_known: true,
                scopes: [],
                expires_at: null,
              },
            ],
          }),
        );
      if (path === "/v1/meetings" && !init?.method)
        return new Response(
          JSON.stringify({
            items: [meeting("mt_soon", 5 * 60_000), meeting("mt_later", 3 * 3_600_000)],
            truncated: false,
          }),
        );
      if (path === "/v1/pinboards")
        return new Response(JSON.stringify({ items: [], truncated: false }));
      if (path.endsWith("/attend"))
        return new Response(
          JSON.stringify({ id: "mt_soon", status: "ended", ended_reason: "completed" }),
        );
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetcher);
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    expect(btn(m.container, "Host a meeting with Tilo")).toBeDefined();
    expect(
      Array.from(m.container.querySelectorAll("button")).filter(
        (b) => b.textContent === "Send Tilo to the meeting",
      ),
    ).toHaveLength(1);
    expect(calls.some((c) => c.includes("/attend") || c.includes("/join"))).toBe(false);
    await press(m.container, "Send Tilo to the meeting");
    expect(calls.filter((c) => c === "POST /v1/meetings/mt_soon/attend")).toHaveLength(1);
    await act(async () => undefined);
    expect(m.container.textContent).toContain("The meeting ended and Tilo left.");
  });
});
