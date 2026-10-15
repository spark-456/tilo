// @vitest-environment happy-dom
// FR-MTG-09 (AGENDA-HOST-STATE): the Agenda's Meetings section reads the meeting host the same way the Connectors page
// does. The live body below is the exact `GET /v1/connectors` row (state_known true), read through the real HttpClient
// and createConnectFlow; only fetch is mocked.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
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

describe("FR_MTG_09_AGENDA_HOST_STATE", () => {
  it("FR_MTG_09_AGENDA_a_available_row_says_sign_in_without_could_not_confirm", async () => {
    wire("available");
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    const gate = m.container.querySelector('[data-testid="host-meeting-gate"]');
    expect(gate?.textContent).toBe("Sign in the meeting host first");
  });
  it("FR_MTG_09_AGENDA_b_connected_row_shows_the_host_button", async () => {
    wire("connected");
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    expect(m.container.textContent).toContain("Host a meeting with Tilo");
  });
  it("FR_MTG_09_AGENDA_c_connectors_page_flow_and_agenda_agree_on_the_same_session", async () => {
    wire("available");
    const flow = liveConnectFlow();
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    expect(await flow?.meetingHost()).toBe("available");
    expect(m.container.querySelector('[data-testid="host-meeting-gate"]')?.textContent).toBe(
      "Sign in the meeting host first",
    );
  });
  it("FR_MTG_09_AGENDA_d_a_failed_first_read_is_read_again_on_Check_again_not_stuck", async () => {
    // The API answers state_known false when one read fails; the Agenda said so once and never looked again.
    const fetcher = wire(["unknown_read", "available", "connected"]);
    const m = mount(<PeopleLists />);
    await act(async () => undefined);
    await act(async () => undefined);
    const gate = () => m.container.querySelector('[data-testid="host-meeting-gate"]');
    expect(gate()?.textContent).toContain("Tilo could not confirm the meeting host.");
    const again = Array.from(m.container.querySelectorAll("button")).find(
      (b) => b.textContent === "Check again",
    );
    expect(again).toBeDefined();
    const reads = () => fetcher.mock.calls.filter((c) => String(c[0]).endsWith("/v1/connectors"));
    expect(reads()).toHaveLength(1);
    await act(async () => click(again as Element));
    await act(async () => undefined);
    expect(reads()).toHaveLength(2);
    expect(gate()?.textContent).toBe("Sign in the meeting host first");
  });
});
