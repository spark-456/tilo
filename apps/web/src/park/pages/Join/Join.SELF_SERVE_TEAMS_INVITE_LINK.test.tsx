// @vitest-environment happy-dom
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { type TeamsClient, installTeamsTransport, teamsClient } from "../../api/selfServeTeams";
import { isParkPath, parseParkPath } from "../../app/router";
import { JoinPage } from "./JoinPage";
import { JOIN_TOKEN_KEY, captureJoinToken } from "./joinToken";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null = null;
let host: HTMLElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  sessionStorage.clear();
  document.querySelector('meta[name="referrer"]')?.remove();
  root = host = null;
});
const token = "v1.key_a.til_aaaaaaaaaaaaaaaaaaaaaaaa.nonce.signature";
function client() {
  return {
    ensurePerson: vi.fn(async () => undefined),
    acceptLink: vi.fn(async () => ({ team: "tm_a", state: "member" })),
    roster: vi.fn(async () => [{ id: "u_lead", name: "Lena", lead: true }]),
  } as unknown as TeamsClient & {
    ensurePerson: ReturnType<typeof vi.fn>;
    acceptLink: ReturnType<typeof vi.fn>;
    roster: ReturnType<typeof vi.fn>;
  };
}
async function mount(api = client()) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => root?.render(<JoinPage client={api} />));
  await act(async () => {
    for (let i = 0; i < 15; i++) await Promise.resolve();
  });
  return { api, page: host };
}
function join() {
  const button = host?.querySelector<HTMLButtonElement>("button");
  if (!button) throw new Error("Join button missing");
  button.click();
}

it("SELF_SERVE_TEAMS_INVITE_LINK_join_drops_the_fragment_before_any_request_and_shows_no_team", async () => {
  history.replaceState({}, "", `/join#${token}`);
  const api = client();
  captureJoinToken();
  expect(location.hash).toBe("");
  expect(sessionStorage.getItem(JOIN_TOKEN_KEY)).toBe(token);
  const { page } = await mount(api);
  expect(page.textContent).toContain("You've been invited to join a team on Tilo.");
  expect(page.textContent).not.toContain("Lena");
  expect(api.acceptLink).not.toHaveBeenCalled();
});

it("SELF_SERVE_TEAMS_INVITE_LINK_join_posts_only_after_the_click_and_only_in_the_body", async () => {
  history.replaceState({}, "", `/join#${token}`);
  const { api } = await mount();
  expect(api.acceptLink).not.toHaveBeenCalled();
  await act(async () => join());
  expect(api.acceptLink).toHaveBeenCalledWith(token);
  expect(api.ensurePerson.mock.invocationCallOrder[0]).toBeLessThan(
    api.acceptLink.mock.invocationCallOrder[0] ?? 0,
  );
  expect(location.href).not.toContain(token);
});

it("SELF_SERVE_TEAMS_INVITE_LINK_transport_sends_the_token_only_in_a_post_body", async () => {
  const calls: [string, unknown][] = [];
  installTeamsTransport({
    getJson: vi.fn(async () => {
      throw new Error("No GET expected");
    }),
    postJson: vi.fn(async (path: string, body: unknown) => {
      calls.push([path, body]);
      return { team: "tm_a", state: "member" };
    }),
  });
  const log = vi.spyOn(console, "log");
  try {
    await teamsClient()?.acceptLink(token);
    expect(calls).toEqual([["/v1/team-invite-links/accept", { token }]]);
    expect(JSON.stringify(calls[0]?.[0])).not.toContain(token);
    expect(log.mock.calls.flat().join(" ")).not.toContain(token);
  } finally {
    log.mockRestore();
    installTeamsTransport(null);
  }
});

it("SELF_SERVE_TEAMS_INVITE_LINK_token_survives_a_sign_in_redirect_and_is_deleted_after_the_answer", async () => {
  history.replaceState({}, "", `/join#${token}`);
  captureJoinToken();
  const { api } = await mount();
  expect(sessionStorage.getItem(JOIN_TOKEN_KEY)).toBe(token);
  expect(api.ensurePerson).toHaveBeenCalled();
  await act(async () => join());
  expect(sessionStorage.getItem(JOIN_TOKEN_KEY)).toBeNull();
});

it("SELF_SERVE_TEAMS_INVITE_LINK_each_answer_shows_its_message", async () => {
  for (const [status, message] of [
    [200, "You joined Lena's team"],
    [404, "This invite link can't be used."],
    [409, "You're already in 8 teams."],
    [503, "Invite links are not available right now."],
  ] as const) {
    sessionStorage.setItem(JOIN_TOKEN_KEY, token);
    const api = client();
    if (status !== 200) api.acceptLink.mockRejectedValueOnce({ status });
    const { page } = await mount(api);
    await act(async () => join());
    expect(page.textContent).toContain(message);
    expect(sessionStorage.getItem(JOIN_TOKEN_KEY) === token).toBe(status === 409);
    act(() => root?.unmount());
    host?.remove();
    root = host = null;
  }
});

it("SELF_SERVE_TEAMS_INVITE_LINK_join_sets_no_referrer", async () => {
  await mount();
  expect(document.querySelector('meta[name="referrer"]')?.getAttribute("content")).toBe(
    "no-referrer",
  );
});

it("SELF_SERVE_TEAMS_INVITE_LINK_join_has_a_park_route", () => {
  expect(isParkPath("/join")).toBe(true);
  expect(parseParkPath("/join", "")).toEqual({ page: "join", params: {} });
});

it("SELF_SERVE_TEAMS_INVITE_LINK_join_fits_a_phone", async () => {
  const { page } = await mount();
  expect(page.querySelector("[data-testid='join-card']")).not.toBeNull();
  expect(page.querySelector<HTMLElement>("[data-testid='join-card']")?.style.maxWidth).toBe(
    "390px",
  );
});
