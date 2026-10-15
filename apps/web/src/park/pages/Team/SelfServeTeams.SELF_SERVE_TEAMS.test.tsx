// @vitest-environment happy-dom
// SELF-SERVE-TEAMS (ADR-0044): the own-teams panel creates a team, invites by email to a team the person leads,
// accepts an invitation, and shows only what the server answered; the setup line is no "ask the owner" dead end.
import { act, createElement } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ORGANISATION_SETUP } from "../../api/organisationSetup";
import type { MyTeam, RosterMember, TeamsClient } from "../../api/selfServeTeams";
import { INVITE_SENT, SelfServeTeams } from "./SelfServeTeams";
import { settle } from "./testApp";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null = null;
let host: HTMLElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = host = null;
});

function fakeClient(teams: MyTeam[], rosters: Record<string, RosterMember[]> = {}) {
  const state = { teams: [...teams] };
  const client = {
    mine: vi.fn(async () => ({ teams: state.teams, you: "u_me" })),
    roster: vi.fn(async (team: string) => rosters[team] ?? []),
    create: vi.fn(async () => {
      state.teams = [
        ...state.teams,
        { team: "tm_new", lead: true, state: "member", invitedBy: null },
      ];
      rosters.tm_new = [{ id: "u_me", name: "Me", lead: true }];
    }),
    invite: vi.fn(async () => undefined),
    accept: vi.fn(async (team: string) => {
      state.teams = state.teams.map((t) =>
        t.team === team ? { ...t, state: "member" as const } : t,
      );
    }),
    leave: vi.fn(async () => undefined),
  } satisfies TeamsClient;
  return client;
}

async function mount(client: TeamsClient | null) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => root?.render(createElement(SelfServeTeams, { client })));
  await settle();
  return host;
}

const button = (el: HTMLElement, name: string) => {
  const found = [...el.querySelectorAll("button")].find((b) => b.textContent === name);
  if (!found) throw new Error(`no button ${name}`);
  return found;
};

it("SELF_SERVE_TEAMS the setup line is no dead end that sends people to the organisation owner", () => {
  expect(ORGANISATION_SETUP).not.toMatch(/ask the organisation owner|Set up your organisation/i);
  expect(ORGANISATION_SETUP).toMatch(/join/i);
});

it("SELF_SERVE_TEAMS without a live client nothing renders and nothing is sent", async () => {
  const el = await mount(null);
  expect(el.innerHTML).toBe("");
});

it("SELF_SERVE_TEAMS Create a team asks the server and shows the team only from the re-read", async () => {
  const client = fakeClient([]);
  const el = await mount(client);
  expect(el.textContent).toContain("You are not in a team yet.");
  await act(async () => button(el, "Create a team").click());
  await settle();
  expect(client.create).toHaveBeenCalledTimes(1);
  expect(client.mine).toHaveBeenCalledTimes(2);
  expect(el.textContent).toContain("Me's team · You lead it");
  expect(el.querySelector('input[aria-label="Invite to your team by email"]')).not.toBeNull();
});

it("SELF_SERVE_TEAMS a lead invites by email and gets the one uniform answer", async () => {
  const client = fakeClient([{ team: "tm_a", lead: true, state: "member", invitedBy: null }], {
    tm_a: [{ id: "u_me", name: "Me", lead: true }],
  });
  const el = await mount(client);
  const input = el.querySelector<HTMLInputElement>(
    'input[aria-label="Invite to your team by email"]',
  );
  if (!input) throw new Error("no invite field");
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, "ben@example.com");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button(el, "Invite").click());
  await settle();
  expect(client.invite).toHaveBeenCalledWith("tm_a", "ben@example.com");
  expect(el.textContent).toContain(INVITE_SENT);
});

it("SELF_SERVE_TEAMS a member who does not lead gets no invite field", async () => {
  const client = fakeClient([{ team: "tm_a", lead: false, state: "member", invitedBy: null }], {
    tm_a: [
      { id: "u_lead", name: "Lena", lead: true },
      { id: "u_me", name: "Me", lead: false },
    ],
  });
  const el = await mount(client);
  expect(el.textContent).toContain("Lena's team");
  expect(el.querySelector('input[aria-label="Invite to your team by email"]')).toBeNull();
});

it("SELF_SERVE_TEAMS an invitation is accepted by the invited person", async () => {
  const client = fakeClient([{ team: "tm_a", lead: false, state: "pending", invitedBy: "Lena" }], {
    tm_a: [
      { id: "u_lead", name: "Lena", lead: true },
      { id: "u_me", name: "Me", lead: false },
    ],
  });
  const el = await mount(client);
  expect(el.textContent).toContain("Lena invited you to their team.");
  await act(async () => button(el, "Accept").click());
  await settle();
  expect(client.accept).toHaveBeenCalledWith("tm_a");
  expect(el.textContent).toContain("Lena's team");
  expect(el.textContent).toContain("You joined the team.");
});

it("SELF_SERVE_TEAMS a refused write says nothing changed", async () => {
  const client = fakeClient([]);
  client.create.mockRejectedValueOnce(new Error("403"));
  const el = await mount(client);
  await act(async () => button(el, "Create a team").click());
  await settle();
  expect(el.textContent).toContain("That did not go through. Nothing was changed.");
});
