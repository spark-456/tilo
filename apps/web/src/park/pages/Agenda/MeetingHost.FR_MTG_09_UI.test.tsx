// @vitest-environment happy-dom
// FR-MTG-01 / FR-MTG-09 / FR-MTG-10 (ui/MEETING-HOST-UI): host a Tilo-notetaker Meet from the Agenda, send Tilo to it.
// The API is mocked; every state shown is one a reply returned.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { meetingHostApi } from "../../api/live/meetingHost";
import {
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
  it("FR_MTG_09_UI_a_start_must_be_future_length_at_most_45_and_the_notice_ticked", () => {
    expect(hostFormError(form, NOW)).toBeNull();
    expect(hostFormError({ ...form, start: "2026-10-13T09:00" }, NOW)).toMatch(/future/);
    expect(hostFormError({ ...form, start: "" }, NOW)).toMatch(/starts/);
    expect(hostFormError({ ...form, minutes: 90 }, NOW)).toMatch(/15, 30 or 45/);
    expect(hostFormError({ ...form, minutes: 60 }, NOW)).toMatch(/15, 30 or 45/); // the bot leaves at 45
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

const PEOPLE = {
  you: "u_me",
  people: [
    { id: "u_me", display_name: "Me" },
    { id: "u_priya", display_name: "Priya" },
    { id: "u_sam", display_name: "Sam" },
  ],
};
const rig = () => {
  const http = {
    getJson: vi.fn(
      async (path: string): Promise<unknown> =>
        path === "/v1/people"
          ? PEOPLE
          : {
              join_url: "https://meet.google.com/abc-defg-hij",
              expires_at: "2026-10-15T10:01:00.000Z",
            },
    ),
    postJson: vi.fn(
      async (path: string, _body?: unknown, _headers?: Record<string, string>): Promise<unknown> =>
        path === "/v1/meetings"
          ? { id: "mt_new" }
          : path.endsWith("/start")
            ? { world_id: "w_new" }
            : path.endsWith("/attend")
              ? { id: "mt_new", status: "ended", ended_reason: "completed" }
              : { id: "mt_new", world_id: "w_new" },
    ),
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
const hostState = (s: "connected" | "available" | "unknown") => async () => s;
const paths = (http: ReturnType<typeof rig>["http"]) => http.postJson.mock.calls.map((c) => c[0]);
const flush = () => act(async () => undefined);
type Post = (path: string, ...rest: unknown[]) => Promise<unknown>;

describe("MEET_SIMPLE one click to a meeting with Tilo", () => {
  it("MEET_SIMPLE_a_without_a_connected_meeting_host_the_buttons_are_a_link_to_connectors", async () => {
    const { api } = rig();
    const m = mount(<HostMeeting api={api} hostState={hostState("available")} now={() => NOW} />);
    await flush();
    expect(btn(m.container, "Meet with Tilo now")).toBeUndefined();
    const link = m.container.querySelector("a");
    expect(link?.textContent).toBe("Sign in the meeting host first");
    expect(link?.getAttribute("href")).toBe("/connectors");
  });
  it("MEET_SIMPLE_b_one_primary_action_and_no_host_world_attend_words", async () => {
    const { api } = rig();
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await flush();
    const labels = Array.from(m.container.querySelectorAll("button")).map((b) => b.textContent);
    expect(labels).toEqual(["Meet with Tilo now", "Schedule with others"]);
    expect(m.container.textContent).not.toMatch(
      /host a meeting|send for approval|needs you|world/i,
    );
    expect(m.container.textContent).toContain("Tilo leave");
  });
  it("MEET_SIMPLE_c_one_click_invites_only_the_person_then_joins_and_sends_tilo_in", async () => {
    const { api, http } = rig();
    const onChanged = vi.fn();
    const m = mount(
      <HostMeeting
        api={api}
        hostState={hostState("connected")}
        now={() => NOW}
        onChanged={onChanged}
      />,
    );
    await flush();
    await press(m.container, "Meet with Tilo now");
    await flush();
    expect(paths(http)).toEqual([
      "/v1/meetings",
      "/v1/meetings/mt_new/world",
      "/v1/meetings/mt_new/start",
      "/v1/meetings/mt_new/attend",
    ]);
    expect(http.postJson.mock.calls[0]?.[1]).toMatchObject({
      attest: true,
      source: "bot",
      attendees: [],
      title: "Meeting with Tilo",
    });
    const body = http.postJson.mock.calls[0]?.[1] as { scheduled: { start: string; end: string } };
    expect(Date.parse(body.scheduled.start)).toBe(NOW + 2 * 60_000);
    expect(Date.parse(body.scheduled.end) - Date.parse(body.scheduled.start)).toBe(45 * 60_000);
    expect(http.postJson.mock.calls[2]?.[1]).toEqual({ approve: true, invited: ["u_me"] });
    expect(http.getJson).toHaveBeenCalledWith("/v1/meetings/mt_new/join");
    expect(m.container.textContent).toContain("The meeting ended and Tilo left.");
    expect(onChanged).toHaveBeenCalledTimes(1);
  });
  it("MEET_SIMPLE_d_while_the_api_waits_it_says_joining_and_wrap_up_says_how", async () => {
    const { api, http } = rig();
    let finish: (v: unknown) => void = () => undefined;
    const base = http.postJson.getMockImplementation() as Post;
    http.postJson.mockImplementation((path: string, ...rest: unknown[]) =>
      path.endsWith("/attend")
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : base(path, ...rest),
    );
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await flush();
    await press(m.container, "Meet with Tilo now");
    await flush();
    expect(m.container.textContent).toContain("Tilo is joining…");
    expect(btn(m.container, "Meet with Tilo now")?.disabled).toBe(true);
    await press(m.container, "Wrap up");
    expect(m.container.textContent).toContain('type "Tilo leave"');
    // no tab could be opened here: the link is offered instead
    expect(m.container.querySelector("a")?.getAttribute("href")).toBe(
      "https://meet.google.com/abc-defg-hij",
    );
    await act(async () =>
      finish({ id: "mt_new", status: "ended", ended_reason: "left_on_request" }),
    );
    expect(m.container.textContent).toContain("Someone typed Tilo leave, so Tilo left.");
    expect(m.container.textContent).toContain("minutes");
  });
  it("MEET_SIMPLE_e_a_failed_join_says_so_and_a_plain_try_again_asks_only_for_the_join", async () => {
    const { api, http } = rig();
    const base = http.postJson.getMockImplementation() as Post;
    let first = true;
    http.postJson.mockImplementation(async (path: string) => {
      if (path.endsWith("/attend") && first) {
        first = false;
        throw new TiloApiError("x", 503, false, true, undefined, false, "bot_unavailable");
      }
      return base(path);
    });
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await flush();
    await press(m.container, "Meet with Tilo now");
    await flush();
    expect(m.container.querySelector('[role="alert"]')?.textContent).toContain(
      "Tilo could not join the meeting.",
    );
    await press(m.container, "Try again");
    await flush();
    expect(paths(http).filter((p) => p.endsWith("/attend"))).toHaveLength(2);
    expect(paths(http).filter((p) => p === "/v1/meetings")).toHaveLength(1);
    expect(m.container.textContent).toContain("The meeting ended and Tilo left.");
  });
  it("MEET_SIMPLE_f_a_refused_start_is_said_plainly_takes_the_meeting_back_and_sends_nobody_in", async () => {
    const { api, http } = rig();
    const base = http.postJson.getMockImplementation() as Post;
    http.postJson.mockImplementation(async (path: string) => {
      if (path.endsWith("/start"))
        throw new TiloApiError("Unreadable", 422, false, true, undefined, false, "MH-02");
      return base(path);
    });
    const m = mount(<HostMeeting api={api} hostState={hostState("connected")} now={() => NOW} />);
    await flush();
    await press(m.container, "Meet with Tilo now");
    await flush();
    expect(m.container.querySelector('[role="alert"]')?.textContent).toContain(
      "Choose a future meeting time",
    );
    expect(paths(http)).toContain("/v1/meetings/mt_new/delete");
    expect(paths(http).some((p) => p.endsWith("/attend"))).toBe(false);
    expect(btn(m.container, "Meet with Tilo now")?.disabled).toBe(false);
  });
});

describe("MEET_SIMPLE schedule with others", () => {
  const open = async () => {
    const r = rig();
    const m = mount(<HostMeeting api={r.api} hostState={hostState("connected")} now={() => NOW} />);
    await flush();
    await press(m.container, "Schedule with others");
    await flush();
    return { ...r, m };
  };
  const notice = (form: Element) =>
    form.querySelector(":scope > label.park-agenda-hostnotice input") as Element;
  const checks = (form: Element) => form.querySelectorAll('fieldset input[type="checkbox"]');
  it("MEET_SIMPLE_g_the_dialog_lists_the_people_and_names_exactly_who_will_be_invited", async () => {
    const { m } = await open();
    const form = m.container.querySelector(
      'form[aria-label="Schedule with others"]',
    ) as HTMLElement;
    expect(form).not.toBeNull();
    const names = Array.from(form.querySelectorAll("fieldset label")).map((l) => l.textContent);
    expect(names).toEqual(["Priya", "Sam"]); // the person is always in; only the others are picked
    const line = () => m.container.querySelector('[data-testid="host-invite-list"]')?.textContent;
    expect(line()).toBe("Invitations will go to: you. No one else.");
    await act(async () => click(checks(form)[1] as Element));
    expect(line()).toBe("Invitations will go to: you, Sam. No one else.");
  });
  it("MEET_SIMPLE_h_confirm_is_the_approval_nothing_is_sent_before_and_no_card_comes_after", async () => {
    const { m, http } = await open();
    const form = m.container.querySelector("form") as HTMLElement;
    set(form.querySelector('input[name="title"]') as Element, "Q4 plan");
    set(form.querySelector('input[name="start"]') as Element, "2026-10-17T18:00");
    await act(async () => click(checks(form)[0] as Element));
    await press(m.container, "Confirm and send invitations");
    expect(m.container.querySelector('[role="alert"]')?.textContent).toMatch(/notice/);
    expect(paths(http)).toEqual([]); // the notice is not ticked: nothing was created or sent
    await act(async () => click(notice(form)));
    await press(m.container, "Confirm and send invitations");
    await flush();
    expect(paths(http)).toEqual([
      "/v1/meetings",
      "/v1/meetings/mt_new/world",
      "/v1/meetings/mt_new/start",
    ]);
    expect(http.postJson.mock.calls[0]?.[1]).toMatchObject({
      attendees: [{ name: "Priya", person: "u_priya" }],
    });
    expect(http.postJson.mock.calls[2]?.[1]).toEqual({
      approve: true,
      invited: ["u_me", "u_priya"],
    });
    expect(m.container.textContent).toContain("Scheduled. Invitations went to you, Priya.");
    expect(m.container.textContent).not.toMatch(/needs you|approve the invitation/i);
    expect(m.container.querySelector("form")).toBeNull();
  });
  it("MEET_SIMPLE_i_a_refused_confirm_says_nothing_was_sent_and_removes_the_meeting", async () => {
    const { m, http } = await open();
    const base = http.postJson.getMockImplementation() as Post;
    http.postJson.mockImplementation(async (path: string) => {
      if (path.endsWith("/start"))
        throw new TiloApiError("x", 409, false, true, undefined, false, "invitees_changed");
      return base(path);
    });
    const form = m.container.querySelector("form") as HTMLElement;
    set(form.querySelector('input[name="title"]') as Element, "Q4 plan");
    set(form.querySelector('input[name="start"]') as Element, "2026-10-17T18:00");
    await act(async () => click(notice(form)));
    await press(m.container, "Confirm and send invitations");
    await flush();
    expect(m.container.querySelector('[role="alert"]')?.textContent).toContain("Nothing was sent.");
    expect(paths(http)).toContain("/v1/meetings/mt_new/delete");
  });
  it("MEET_SIMPLE_j_cancel_closes_the_dialog_and_sends_nothing", async () => {
    const { m, http } = await open();
    await press(m.container, "Cancel");
    expect(m.container.querySelector("form")).toBeNull();
    expect(paths(http)).toEqual([]);
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
    await press(m.container, "Bring Tilo in");
    expect(http.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/attend", {});
    expect(m.container.textContent).toContain(
      "Tilo is joining… Admit Tilo notetaker in Meet. Keep this tab open.",
    );
    expect(btn(m.container, "Bring Tilo in")).toBeUndefined();
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
    await press(m.container, "Bring Tilo in");
    expect(m.container.querySelector('[role="alert"]')?.textContent).toContain(
      "This meeting cannot be joined right now.",
    );
    expect(http.postJson).toHaveBeenCalledTimes(1);
  });
  it("FR_MTG_10_UI_d_open_meet_reads_the_link_on_the_click_only_and_checks_its_shape", async () => {
    const { api, http } = rig();
    const m = mount(<MeetingAttend id="mt_a" row={row} api={api} now={() => NOW} />);
    expect(http.getJson).not.toHaveBeenCalled();
    await press(m.container, "Open the call");
    expect(http.getJson).toHaveBeenCalledWith("/v1/meetings/mt_a/join");
    const a = m.container.querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://meet.google.com/abc-defg-hij");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer");
    http.getJson.mockResolvedValueOnce({
      join_url: "https://evil.test/abc-defg-hij",
      expires_at: "x",
    });
    await press(m.container, "Open the call");
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
    expect(btn(m.container, "Meet with Tilo now")).toBeDefined();
    expect(
      Array.from(m.container.querySelectorAll("button")).filter(
        (b) => b.textContent === "Bring Tilo in",
      ),
    ).toHaveLength(1);
    expect(calls.some((c) => c.includes("/attend") || c.includes("/join"))).toBe(false);
    await press(m.container, "Bring Tilo in");
    expect(calls.filter((c) => c === "POST /v1/meetings/mt_soon/attend")).toHaveLength(1);
    await act(async () => undefined);
    expect(m.container.textContent).toContain("The meeting ended and Tilo left.");
  });
});
