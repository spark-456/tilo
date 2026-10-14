// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { HttpClient, TiloApiError } from "../../../api/http";
import { meetingMinutesApi } from "../../api/live/meetingMinutes";
import { MeetingMinutes } from "./MeetingMinutes";
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
const doc = {
  meeting_id: "mt_a",
  summary: [{ text: "Agreed scope" }],
  decisions: [{ text: "Proceed" }],
  action_items: [{ text: "Check dates" }],
};
const stamp = { user: "u_owner", at: "2026-10-14T00:00:00Z" };
const attendees = [
  { user: "u_alex", name: "Alex" },
  { user: null, name: "Unresolved guest" },
];
const mockHttp = () => ({
  hasPostRoute: vi.fn().mockResolvedValue(true),
  getJson: vi.fn(async (path: string) =>
    path.endsWith("/minutes") ? doc : { id: "mt_a", minutes_confirmed_by: null, attendees },
  ),
  postJson: vi.fn(async (path: string) =>
    path.endsWith("/confirm")
      ? { id: "mt_a", minutes_confirmed_by: stamp }
      : path.endsWith("/draft-followup")
        ? {
            card_id: "card_a",
            subject: "Meeting follow-up",
            body: "Please check dates",
            to: ["a@example.test"],
            tier: "T3",
          }
        : { id: "mt_a" },
  ),
});
const button = (root: HTMLElement, text: string) =>
  Array.from(root.querySelectorAll("button")).find((b) => b.textContent === text);
const press = async (root: HTMLElement, text: string) => {
  const target = button(root, text);
  if (!target) throw new Error(`Missing button: ${text}`);
  await act(async () => click(target));
};

describe("FR_MTG_03_08 Park minutes owner flow", () => {
  it.each([404, 405])(
    "Agenda hides absent routes and exposes registered routes (%s) without a write",
    async (routeStatus) => {
      const fetcher = vi.fn(async (url: string, init: RequestInit) => {
        if (init.method === "OPTIONS") return new Response("{}", { status: routeStatus });
        return new Response(
          JSON.stringify({
            items: url.endsWith("/meetings")
              ? [
                  {
                    id: "mt_a",
                    title: "Review call",
                    status: "ended",
                    scheduled: null,
                    created_at: "2026-10-14T00:00:00Z",
                  },
                ]
              : [],
            truncated: false,
          }),
        );
      });
      vi.stubGlobal("fetch", fetcher);
      const m = mount(<PeopleLists />);
      await act(async () => undefined);
      expect(m.container.textContent).toContain("Review call");
      expect(Boolean(button(m.container, "Analyze minutes"))).toBe(routeStatus === 405);
      expect(
        fetcher.mock.calls.every(([, init]) => !init.method || init.method === "OPTIONS"),
      ).toBe(true);
    },
  );
  it("does not analyze or draft on mount; requires review and explicit confirmation before drafting", async () => {
    const http = mockHttp();
    const m = mount(<MeetingMinutes id="mt_a" status="ended" api={meetingMinutesApi(http)} />);
    expect(http.postJson).not.toHaveBeenCalled();
    await press(m.container, "Analyze minutes");
    expect(http.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/analyze-minutes", {});
    expect(m.container.textContent).toContain("Agreed scope");
    expect(m.container.textContent).toContain("Check dates");
    expect(button(m.container, "Draft follow-up")).toBeUndefined();
    http.getJson.mockImplementation(async (p) =>
      p.endsWith("/minutes")
        ? doc
        : ({ id: "mt_a", minutes_confirmed_by: stamp, attendees } as never),
    );
    await press(m.container, "Confirm these minutes");
    expect(http.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/confirm", {});
    const input = m.container.querySelector("input");
    if (!input) throw new Error("Missing recipients input");
    await act(async () => {
      click(input);
    });
    await press(m.container, "Draft follow-up");
    expect(http.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/draft-followup", {
      recipients: ["u_alex"],
    });
    expect(m.container.querySelector('[aria-label="T3 approval card"]')?.textContent).toContain(
      "Needs your approval · nothing sent",
    );
    expect(
      http.postJson.mock.calls.some(([p]) => p.includes("send") || p.includes("approve")),
    ).toBe(false);
  });
  it("reviews existing minutes without another provider call", async () => {
    const http = mockHttp();
    const m = mount(<MeetingMinutes id="mt_a" status="minuted" api={meetingMinutesApi(http)} />);
    await press(m.container, "Review minutes");
    expect(http.postJson).not.toHaveBeenCalled();
  });
  it("hides controls when a route disappears; a denied owner never sees minutes", async () => {
    const http = mockHttp();
    http.postJson.mockRejectedValue(new TiloApiError("Missing", 404, false));
    const m = mount(<MeetingMinutes id="mt_a" status="ended" api={meetingMinutesApi(http)} />);
    await press(m.container, "Analyze minutes");
    expect(m.container.textContent).toBe("");
    expect(http.getJson).not.toHaveBeenCalled();
  });
  it("does not offer work on a scheduled or deleted meeting", () => {
    for (const status of ["scheduled", "live", "deleted", "discarded"]) {
      const m = mount(
        <MeetingMinutes id="mt_a" status={status} api={meetingMinutesApi(mockHttp())} />,
      );
      expect(m.container.textContent).toBe("");
    }
  });
  it("keeps failed confirmation from enabling follow-up", async () => {
    const http = mockHttp();
    const m = mount(<MeetingMinutes id="mt_a" status="minuted" api={meetingMinutesApi(http)} />);
    await press(m.container, "Review minutes");
    http.postJson.mockRejectedValue(new TiloApiError("Conflict", 409, false));
    await press(m.container, "Confirm these minutes");
    expect(m.container.querySelector('[role="alert"]')).not.toBeNull();
    expect(button(m.container, "Draft follow-up")).toBeUndefined();
  });
  it("discovers both routes without OpenAPI, providers or writes; absent route stays off", async () => {
    const http = mockHttp();
    http.hasPostRoute.mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    expect(await meetingMinutesApi(http).available()).toBe(false);
    expect(http.getJson).not.toHaveBeenCalled();
    expect(http.postJson).not.toHaveBeenCalled();
  });
  it("route discovery uses existing authentication and App Check with OPTIONS", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response('{"detail":"Method Not Allowed"}', { status: 405 }));
    const http = new HttpClient({
      baseUrl: "https://api.example.test",
      fetch: fetcher,
      authToken: async () => "owner-token",
      appCheckToken: async () => "app-check",
    });
    expect(await http.hasPostRoute("/v1/meetings/mt_probe/analyze-minutes")).toBe(true);
    const init = fetcher.mock.calls[0][1];
    expect(init.method).toBe("OPTIONS");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer owner-token");
    expect(new Headers(init.headers).get("X-Firebase-AppCheck")).toBe("app-check");
  });
  it.each([404, 401, 403, 503])("route discovery fails closed for %s", async (status) => {
    const http = new HttpClient({
      baseUrl: "https://api.example.test",
      fetch: vi.fn().mockResolvedValue(new Response("{}", { status })),
    });
    expect(await http.hasPostRoute("/v1/meetings/mt_probe/analyze-minutes")).toBe(false);
  });
  it("refuses malformed or duplicate recipients before writing", async () => {
    const http = mockHttp();
    const api = meetingMinutesApi(http);
    for (const recipients of [[], ["mail@example.test"], ["u_a", "u_a"]])
      await expect(api.draft("mt_a", recipients)).rejects.toThrow();
    expect(http.postJson).not.toHaveBeenCalled();
  });
  it("rejects a non-T3 preview and another meeting's minutes", async () => {
    const http = mockHttp();
    http.postJson.mockResolvedValue({
      card_id: "c",
      subject: "Bad",
      body: "No",
      to: [],
      tier: "T2",
    } as never);
    await expect(meetingMinutesApi(http).draft("mt_a", ["u_a"])).rejects.toThrow();
    http.getJson.mockResolvedValue({ ...doc, meeting_id: "mt_other" } as never);
    await expect(meetingMinutesApi(http).read("mt_a")).rejects.toThrow();
  });
});
