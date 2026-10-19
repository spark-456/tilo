// @vitest-environment happy-dom
// FR-MTG-09 (AGENDA-HOST-STATE): the Agenda's Meetings section reads the meeting host the same way the Connectors page
// does. The live body below is the exact `GET /v1/connectors` row (state_known true), read through the real HttpClient
// and createConnectFlow; only fetch is mocked.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { liveConnectFlow } from "../../../api/connectEnv";
import { PeopleLists } from "./PeopleLists";

vi.mock("../../../api/ClientProvider", () => ({
  API_URL: "https://api.example.test",
  authToken: async () => "owner-token",
  appCheckToken: async () => "app-check",
  sessionView: { demo: () => false },
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const HOST = {
  id: "meeting_host",
  name: "Tilo meeting host",
  auth: "oauth2",
  state: "available",
  scopes: [],
  expires_at: null,
  state_known: true,
};
const WIRE = (state: string) => ({
  connectors: [
    state === "unknown_read"
      ? { ...HOST, state: "available", state_known: false }
      : { ...HOST, state },
  ],
});

function wire(state: string | string[]) {
  const states = Array.isArray(state) ? [...state] : [state];
  const fetcher = vi.fn(async (url: string | URL | Request) => {
    const u = String(url);
    if (u.endsWith("/v1/connectors"))
      return new Response(
        JSON.stringify(WIRE(states.length > 1 ? (states.shift() ?? "") : (states[0] ?? ""))),
        {
          headers: { "content-type": "application/json" },
        },
      );
    if (u.endsWith("/v1/meetings")) return new Response(JSON.stringify({ meetings: [] }));
    if (u.endsWith("/v1/pinboards") || u.includes("/v1/pinboards"))
      return new Response(JSON.stringify({ items: [] }));
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

// MEET-GUEST: whatever the meeting host's state, nobody is asked to sign it in; the guest join is always offered and
// "Meet with Tilo now" (a meeting Tilo hosts) appears only with a connected host.
const guestForm = (root: HTMLElement) =>
  Array.from(root.querySelectorAll("button")).some((b) => b.textContent === "Send Tilo to my call");
const signInLink = (root: HTMLElement) =>
  Array.from(root.querySelectorAll("a")).some((a) =>
    /sign in the meeting host/i.test(a.textContent ?? ""),
  );

describe("FR_MTG_09_AGENDA_HOST_STATE", () => {
  it("FR_MTG_09_AGENDA_a_available_row_offers_the_guest_join_and_no_sign_in", async () => {
    wire("available");
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    expect(guestForm(m.container)).toBe(true);
    expect(signInLink(m.container)).toBe(false);
    expect(m.container.textContent).not.toContain("Meet with Tilo now");
  });
  it("FR_MTG_09_AGENDA_b_connected_row_shows_the_host_button", async () => {
    wire("connected");
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    expect(m.container.textContent).toContain("Meet with Tilo now");
    expect(guestForm(m.container)).toBe(true);
  });
  it("FR_MTG_09_AGENDA_c_connectors_page_flow_and_agenda_agree_on_the_same_session", async () => {
    wire("available");
    const flow = liveConnectFlow();
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    expect(await flow?.meetingHost()).toBe("available");
    expect(guestForm(m.container)).toBe(true);
  });
  it("FR_MTG_09_AGENDA_d_an_unknown_host_read_still_offers_the_guest_join", async () => {
    wire("unknown_read");
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    expect(guestForm(m.container)).toBe(true);
    expect(signInLink(m.container)).toBe(false);
    expect(m.container.textContent).not.toContain("could not confirm the meeting host");
  });
});
