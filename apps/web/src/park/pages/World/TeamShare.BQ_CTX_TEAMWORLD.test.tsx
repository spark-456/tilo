// @vitest-environment happy-dom
// BQ-CTX-TEAMWORLD (ADR-0040 decision 10; FR-TEAM-01/02): the owner's "Share with team" dialog. The client is a fake
// fetch; the Api is the fixture one with its team and world list replaced by what the live Api would answer.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { appFor } from "../../../../test-support/park/worldHarness";
import { HttpClient } from "../../../api/http";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { ParkProvider } from "../../app/context";
import { WorldPage } from "./WorldPage";

afterEach(cleanup);

const W = "w_launch";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

interface Server {
  shares: { team: string; in_force: boolean; reason: string | null; granted_at: string }[];
  sharesStatus: number;
  putStatus: number;
}
const newServer = (over: Partial<Server> = {}): Server => ({
  shares: [],
  sharesStatus: 200,
  putStatus: 200,
  ...over,
});

function fakeFetch(s: Server) {
  return vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    const method = init?.method ?? "GET";
    if (path === `/worlds/${W}/team-shares` && method === "GET")
      return s.sharesStatus === 200
        ? json({ world_id: W, shares: s.shares })
        : json({}, s.sharesStatus);
    const team = path.match(/^\/worlds\/[^/]+\/team-shares\/([^/]+)$/)?.[1];
    if (team && (method === "PUT" || method === "DELETE")) {
      if (s.putStatus !== 200) return json({}, s.putStatus);
      s.shares = s.shares.filter((x) => x.team !== team);
      if (method === "PUT")
        s.shares.push({
          team,
          in_force: true,
          reason: null,
          granted_at: "2026-10-10T09:00:00.000Z",
        });
      return json({
        world_id: W,
        team,
        state: method === "PUT" ? "on" : "off",
        in_force: method === "PUT",
      });
    }
    return json({}, 404);
  });
}

const teamOf = (memberships: string[]) => ({
  data: {
    people: [
      {
        id: "u_asha",
        name: "Asha",
        email: null,
        dept: null,
        role: null,
        active: null,
        c: null,
        you: true,
        memberships,
      },
      {
        id: "u_ben",
        name: "Ben",
        email: null,
        dept: null,
        role: null,
        active: null,
        c: null,
        memberships: null,
      },
    ],
    rules: [],
    matrix: [],
    roles: [],
    coverage: [],
  },
  source: "live" as const,
});

/** The fixture Api with a live world list: `own` ids are this person's worlds; the rest are not. */
async function liveApi(
  memberships: string[] = ["tm_launch", "tm_ops"],
  own: string | null = W,
): Promise<Api> {
  const api = createFixtureApi();
  const listed = await api.getWorlds({}, []);
  const first = listed.data[0];
  if (!first) throw new Error("fixture world missing");
  api.getWorlds = async () => ({
    data: own ? [{ ...first, id: own, name: "Launch plan", sample: false }] : [],
    source: "live",
  });
  api.getTeam = async () => teamOf(memberships);
  return api;
}

async function page(server: Server, api: Api, id = W) {
  const fetch = fakeFetch(server);
  const client = new HttpClient({ baseUrl: "https://api.test", fetch });
  const sch = fakeScheduler();
  let m: ReturnType<typeof mount> | undefined;
  await act(async () => {
    m = mount(
      <ParkProvider api={api} worldClient={client} schedule={sch.schedule}>
        <WorldPage app={appFor(id)} />
      </ParkProvider>,
    );
  });
  if (!m) throw new Error("page did not mount");
  return {
    el: m.container,
    fetch,
    calls: () =>
      fetch.mock.calls.map((c) => `${c[1]?.method ?? "GET"} ${new URL(String(c[0])).pathname}`),
  };
}

const buttons = (el: HTMLElement) => [...el.querySelectorAll("button")];
const named = (el: HTMLElement, label: string) =>
  buttons(el).find((b) => b.textContent === label || b.getAttribute("aria-label") === label);
const press = async (b: Element | undefined) => {
  if (!b) throw new Error("button missing");
  await act(async () => {
    (b as HTMLElement).click();
  });
};

describe("BQ_CTX_TEAMWORLD the owner's Share with team dialog", () => {
  it("FR_TEAM_01 states what sharing does before anything changes, then lists each team's live state", async () => {
    const server = newServer({
      shares: [
        { team: "tm_launch", in_force: true, reason: null, granted_at: "2026-10-10T09:00:00.000Z" },
      ],
    });
    const { el, calls } = await page(server, await liveApi());
    await press(named(el, "Share with team"));
    const dialog = el.querySelector('[role="dialog"]');
    const text = dialog?.textContent ?? "";
    expect(text).toContain("whole world");
    expect(text).toContain("Story, Trace, runs and artifacts, past and future");
    expect(text).toContain("except lines only you can see");
    expect(text).toContain("added in this world from now on are visible");
    expect(text).toContain("They cannot answer, approve, pause or share it");
    const rows = [...(dialog?.querySelectorAll("li") ?? [])].map((li) => li.textContent ?? "");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain("tm_launch");
    expect(rows[0]).toContain("Shared. Every member of this team can read this world.");
    expect(rows[1]).toContain("tm_ops");
    expect(rows[1]).toContain("Not shared.");
    expect(named(el, "Stop sharing with tm_launch")).toBeDefined();
    expect(named(el, "Share this world with tm_ops")).toBeDefined();
    expect(calls().some((c) => c.startsWith("PUT") || c.startsWith("DELETE"))).toBe(false);
  });

  it("FR_TEAM_01 says Shared only from the server's list after the change", async () => {
    const server = newServer();
    const { el, calls } = await page(server, await liveApi());
    await press(named(el, "Share with team"));
    await press(named(el, "Share this world with tm_ops"));
    expect(calls().slice(-3)).toEqual([
      `GET /worlds/${W}/team-shares`,
      "PUT /worlds/w_launch/team-shares/tm_ops",
      `GET /worlds/${W}/team-shares`,
    ]);
    const row = [...el.querySelectorAll('[role="dialog"] li')].find((li) =>
      li.textContent?.includes("tm_ops"),
    );
    expect(row?.textContent).toContain("Shared. Every member");
    expect(named(el, "Stop sharing with tm_ops")).toBeDefined();
  });

  it("FR_TEAM_01 a refused grant says so, shows no Shared row and changes nothing", async () => {
    const server = newServer({ putStatus: 403 });
    const { el } = await page(server, await liveApi());
    await press(named(el, "Share with team"));
    await press(named(el, "Share this world with tm_ops"));
    const dialog = el.querySelector('[role="dialog"]');
    expect(dialog?.querySelector('[role="alert"]')?.textContent).toContain(
      "Could not share with tm_ops",
    );
    expect(dialog?.textContent).not.toContain("Shared. Every member");
    expect(server.shares).toEqual([]);
  });

  it("FR_TEAM_02 Stop sharing sends a DELETE and the row goes back to Not shared", async () => {
    const server = newServer({
      shares: [
        { team: "tm_launch", in_force: true, reason: null, granted_at: "2026-10-10T09:00:00.000Z" },
      ],
    });
    const { el, calls } = await page(server, await liveApi());
    await press(named(el, "Share with team"));
    await press(named(el, "Stop sharing with tm_launch"));
    expect(calls()).toContain("DELETE /worlds/w_launch/team-shares/tm_launch");
    const row = [...el.querySelectorAll('[role="dialog"] li')].find((li) =>
      li.textContent?.includes("tm_launch"),
    );
    expect(row?.textContent).toContain("Not shared.");
  });

  it("FR_TEAM_02 a share that lapsed says why in words and offers a fresh share", async () => {
    const server = newServer({
      shares: [
        {
          team: "tm_launch",
          in_force: false,
          reason: "owner_left_team",
          granted_at: "2026-10-10T09:00:00.000Z",
        },
      ],
    });
    const { el } = await page(server, await liveApi());
    await press(named(el, "Share with team"));
    const row = el.querySelector('[role="dialog"] li');
    expect(row?.textContent).toContain("Not in force. You left this team, so this share stopped.");
    expect(named(el, "Share this world with tm_launch")).toBeDefined();
  });

  it("FR_TEAM_01 a read that fails says so and offers Try again; 401 and 404 are said plainly", async () => {
    const server = newServer({ sharesStatus: 500 });
    const { el } = await page(server, await liveApi());
    await press(named(el, "Share with team"));
    expect(el.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain(
      "problem on its side",
    );
    server.sharesStatus = 200;
    await press(named(el, "Try again"));
    expect(el.querySelector('[role="dialog"] li')?.textContent).toContain("tm_launch");

    const unsigned = await page(newServer({ sharesStatus: 401 }), await liveApi());
    await press(named(unsigned.el, "Share with team"));
    expect(unsigned.el.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain(
      "sign in",
    );

    const missing = await page(newServer({ sharesStatus: 404 }), await liveApi());
    await press(named(missing.el, "Share with team"));
    expect(missing.el.querySelector('[role="dialog"] [role="alert"]')?.textContent).toContain(
      "Only its owner can share it",
    );
    expect(named(missing.el, "Try again")).toBeUndefined();
  });

  it("FR_TEAM_01 a person in no team is told there is nobody to share with", async () => {
    const { el } = await page(newServer(), await liveApi([]));
    await press(named(el, "Share with team"));
    expect(el.querySelector('[role="dialog"]')?.textContent).toContain("You are not in a team yet");
  });

  it("FR_TEAM_01 the demo's fixture world offers no sharing and asks nothing of the team routes", async () => {
    const api = createFixtureApi();
    const fixture = (await api.getWorlds({}, [])).data[0];
    const { el, calls } = await page(newServer(), api, fixture?.id);
    expect(named(el, "Share with team")).toBeUndefined();
    expect(calls()).toEqual([]);
  });
});
