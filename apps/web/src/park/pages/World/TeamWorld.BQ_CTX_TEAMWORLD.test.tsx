// @vitest-environment happy-dom
// BQ-CTX-TEAMWORLD (ADR-0040 decisions 4, 6 and 8; FR-TEAM-03/05): a teammate's read-only world page and the team
// work-items list. The client is a fake fetch; the Api is the fixture
// one with its team and world list replaced by what the live Api would answer.
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
  items: Record<string, unknown>[];
  world: Record<string, unknown> | number;
  sharesStatus: number;
  putStatus: number;
}
const newServer = (over: Partial<Server> = {}): Server => ({
  shares: [],
  items: [],
  world: {
    world_id: W,
    districts: [{ id: "D1", name: "Design", summary: "Mock-ups" }],
    has_hidden_districts: false,
  },
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
    if (path === `/worlds/${W}/work-items`)
      return json({ world_id: W, items: s.items, truncated: false });
    if (path === `/worlds/${W}`)
      return typeof s.world === "number" ? json({}, s.world) : json(s.world);
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

/** The fixture Api with a live world list as `GET /worlds` serves it: `own` is this person's world, or, with
 * `null`, the list carries `W` as a teammate's (`access: "team"`, TSW-4b) and nothing of their own. */
async function liveApi(
  memberships: string[] = ["tm_launch", "tm_ops"],
  own: string | null = W,
): Promise<Api> {
  const api = createFixtureApi();
  const listed = await api.getWorlds({}, []);
  const first = listed.data[0];
  if (!first) throw new Error("fixture world missing");
  api.getWorlds = async () => ({
    data: own
      ? [{ ...first, id: own, name: "Launch plan", sample: false }]
      : [{ ...first, id: W, name: "Launch plan", sample: false, access: "team" as const }],
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

describe("BQ_CTX_TEAMWORLD a teammate's read-only world", () => {
  const item = (over: Record<string, unknown> = {}) => ({
    id: "wi_1",
    title: "Book the venue",
    status: "open",
    due: "2026-10-20",
    owner: "u_ben",
    world_id: W,
    ...over,
  });

  it("FR_TEAM_03 shows the districts and read lenses and no control that writes", async () => {
    const server = newServer({
      items: [item(), item({ id: "wi_2", owner: "u_zed", status: "done", due: null })],
    });
    const { el } = await page(server, await liveApi(["tm_launch"], null));
    const text = el.textContent ?? "";
    expect(text).toContain("Shared world");
    expect(text).toContain("You can read this world. Only its owner can change it.");
    expect(text).toContain("Design");
    expect(text).toContain("Mock-ups");
    const links = [...el.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(links).toEqual(
      expect.arrayContaining([`/world/${W}/story`, `/world/${W}/trace`, `/world/${W}/delivery`]),
    );
    expect(links.some((h) => h?.endsWith("/stage"))).toBe(false);
    for (const word of [
      "Pause",
      "Resume",
      "Share",
      "Share with team",
      "Share to Slack",
      "Approve",
      "Answer",
    ])
      expect(named(el, word), word).toBeUndefined();
    expect(el.querySelector('[role="dialog"]')).toBeNull();
  });

  it("FR_TEAM_05 lists the team's items as rows: owner by directory name, no link, no button", async () => {
    const server = newServer({
      items: [item(), item({ id: "wi_2", owner: "u_zed", status: "done", due: null })],
    });
    const { el } = await page(server, await liveApi(["tm_launch"], null));
    const rows = [...el.querySelectorAll('ul[aria-label="Team work items"] li')];
    expect(rows.map((r) => r.textContent)).toEqual([
      "Book the venueBen · Open · due 2026-10-20",
      "Book the venueA teammate · Done",
    ]);
    for (const r of rows) expect(r.querySelector("a, button")).toBeNull();
  });

  it("FR_TEAM_05 an empty list says no items yet and that items added before sharing stay personal", async () => {
    const server = newServer();
    const { el } = await page(server, await liveApi(["tm_launch"], null));
    expect(el.textContent).toContain("No work items have been added in this world yet");
    expect(el.textContent).toContain("Items added before it was shared stay personal");
  });

  it("FR_TEAM_03 a world the list does not carry is an ordinary missing world, with no request", async () => {
    const { el, calls } = await page(newServer(), await liveApi(["tm_launch"], null), "w_nobody");
    expect(el.textContent).toContain("World not found");
    expect(el.textContent).toContain("Tilo could not find that world.");
    expect(buttons(el)).toHaveLength(0);
    expect(calls()).toEqual([]);
  });

  it("FR_TEAM_03 a team world whose share lapsed since the list is the same missing world", async () => {
    const { el } = await page(newServer({ world: 404 }), await liveApi(["tm_launch"], null));
    expect(el.textContent).toContain("World not found");
    expect(el.textContent).not.toContain("Shared world");
    expect(buttons(el)).toHaveLength(0);
  });

  it("FR_TEAM_03 a world listed as the person's own is not opened as a teammate's", async () => {
    const own = await page(newServer(), await liveApi(["tm_launch"], W));
    expect(own.el.textContent).not.toContain("Shared world");
    expect(own.calls().some((c) => c === `GET /worlds/${W}`)).toBe(false);
  });

  it("FR_TEAM_03 a read that fails shows the failure and retries; nothing is invented", async () => {
    const server = newServer({ world: 500 });
    const { el } = await page(server, await liveApi(["tm_launch"], null));
    expect(el.querySelector('[role="alert"]')?.textContent).toContain("problem on its side");
    expect(el.textContent).not.toContain("Shared world");
    server.world = { world_id: W, districts: [], has_hidden_districts: true };
    await press(named(el, "Try again"));
    expect(el.textContent).toContain("Shared world");
    expect(el.textContent).toContain("Some districts are not shown to you");
  });
});

describe("BQ_CTX_TEAMWORLD the owner's own page", () => {
  it("FR_TEAM_05 reads the team's items only when asked, never on opening", async () => {
    const server = newServer({
      items: [
        {
          id: "wi_1",
          title: "Book the venue",
          status: "open",
          due: null,
          owner: "u_ben",
          world_id: W,
        },
      ],
    });
    const { el, calls } = await page(server, await liveApi());
    expect(calls().some((c) => c.endsWith("/work-items"))).toBe(false);
    await press(named(el, "Show team work items"));
    expect(calls().some((c) => c.endsWith("/work-items"))).toBe(true);
    expect(el.textContent).toContain("Book the venue");
  });
});
