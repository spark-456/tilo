// @vitest-environment happy-dom
// BQ-CTX-TEAMWORLD (ADR-0040 decisions 6, 9 and 10; FR-TEAM-02/04/05): the add-a-work-item form on a world page and
// the world's sharing line. The client is a fake fetch; the Api is the fixture one with its world list replaced by
// what the live Api would answer. The line comes only from recorded `world.share_changed` events (HR-1).
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
  events: Record<string, unknown>[] | number;
  items: Record<string, unknown>[];
  /** The status the create answers with; 201 stores the item and answers with it. */
  postStatus: number;
  /** When set, the create waits for this to resolve (the loading state). */
  hold: Promise<void> | null;
  posts: { body: Record<string, unknown>; key: string | null }[];
  world: Record<string, unknown>;
}
const newServer = (over: Partial<Server> = {}): Server => ({
  events: [],
  items: [],
  postStatus: 201,
  hold: null,
  posts: [],
  world: {
    world_id: W,
    districts: [{ id: "D1", name: "Design", summary: "Mock-ups" }],
    has_hidden_districts: false,
  },
  ...over,
});
const shareEvent = (seq: number, team: string, state: "on" | "off") => ({
  id: `01JB5VQ00000000000000${String(seq).padStart(5, "0")}`,
  seq,
  world_id: W,
  type: "world.share_changed",
  actor: "u_asha",
  vis: [],
  data: { team, state },
});

function fakeFetch(s: Server) {
  return vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    const method = init?.method ?? "GET";
    if (path === "/v1/work-items" && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      s.posts.push({ body, key: new Headers(init?.headers).get("idempotency-key") });
      if (s.hold) await s.hold;
      if (s.postStatus !== 201) return json({ detail: "invalid_body" }, s.postStatus);
      const row = {
        id: `wi_${s.posts.length}`,
        title: body.title,
        status: "open",
        due: null,
        owner: "u_asha",
        world_id: body.world_id ?? null,
      };
      if (body.world_id) s.items.push(row);
      return json({ ...row, source: { kind: "manual", ref: null } }, 201);
    }
    if (path === `/worlds/${W}/events`)
      return typeof s.events === "number" ? json({}, s.events) : json({ events: s.events });
    if (path === `/worlds/${W}/work-items`)
      return json({ world_id: W, items: s.items, truncated: false });
    if (path === `/worlds/${W}`) return json(s.world);
    return json({}, 404);
  });
}

const people = {
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
        memberships: ["tm_launch"],
      },
    ],
    rules: [],
    matrix: [],
    roles: [],
    coverage: [],
  },
  source: "live" as const,
};

async function liveApi(own: string | null = W): Promise<Api> {
  const api = createFixtureApi();
  const first = (await api.getWorlds({}, [])).data[0];
  if (!first) throw new Error("fixture world missing");
  api.getWorlds = async () => ({
    data: own ? [{ ...first, id: own, name: "Launch plan", sample: false }] : [],
    source: "live",
  });
  api.getTeam = async () => people;
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
const form = (el: HTMLElement) => el.querySelector<HTMLElement>('[aria-label="Add a work item"]');
const type = async (el: HTMLElement, label: string, value: string) => {
  const input = form(el)?.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
  if (!input) throw new Error(`field ${label} missing`);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
const choose = async (el: HTMLElement, label: string) =>
  press(form(el)?.querySelector(`input[aria-label="${label}"]`) ?? undefined);
const add = (el: HTMLElement) => press(named(form(el) ?? el, "Add item"));
const status = (el: HTMLElement) => form(el)?.querySelector("output")?.textContent ?? "";
const alertOf = (el: HTMLElement) => form(el)?.querySelector('[role="alert"]')?.textContent ?? "";
const line = (el: HTMLElement) =>
  el.querySelector('[data-testid="park-world-share-line"]')?.textContent ?? null;

describe("BQ_CTX_TEAMWORLD the add-a-work-item form", () => {
  it("FR_TEAM_04 is offered on the owner's own world and on a teammate's world, defaulting to a personal item", async () => {
    for (const own of [W, null]) {
      const { el } = await page(newServer(), await liveApi(own));
      const f = form(el);
      expect(f, `own=${own}`).not.toBeNull();
      expect(f?.querySelector<HTMLInputElement>('input[aria-label="Only me"]')?.checked).toBe(true);
      expect(
        f?.querySelector<HTMLInputElement>('input[aria-label="This world’s team"]')?.checked,
      ).toBe(false);
      cleanup();
    }
  });

  it("FR_TEAM_04 says plainly that a world item is visible to the team's members, before anything is sent", async () => {
    const { el, calls } = await page(newServer(), await liveApi());
    const text = form(el)?.textContent ?? "";
    expect(text).toContain("Every member of the team this world is shared with can see");
    expect(text).toContain("title, status and due date");
    expect(text).toContain("If this world is not shared with a team, only you can see it");
    expect(calls().some((c) => c.startsWith("POST"))).toBe(false);
  });

  it("FR_TEAM_04 a personal item posts no world_id; the personal answer says it is on the person's own list", async () => {
    const server = newServer();
    const { el } = await page(server, await liveApi());
    await type(el, "Title", "Call the caterer");
    await add(el);
    expect(server.posts).toHaveLength(1);
    expect(server.posts[0]?.body).toEqual({
      title: "Call the caterer",
      source: { kind: "manual", ref: null },
    });
    expect(status(el)).toContain("Added “Call the caterer” to your own list");
    expect(server.items).toEqual([]);
  });

  it("FR_TEAM_04 a world item posts the page's world_id with the due phrase and then shows in the team list", async () => {
    const server = newServer();
    const { el } = await page(server, await liveApi());
    await press(named(el, "Show team work items"));
    expect(el.textContent).toContain("No work items have been added in this world yet");
    await type(el, "Title", "Book the venue");
    await type(el, "Due (optional)", "next friday");
    await choose(el, "This world’s team");
    await add(el);
    expect(server.posts[0]?.body).toEqual({
      title: "Book the venue",
      due_text: "next friday",
      source: { kind: "manual", ref: null },
      world_id: W,
    });
    expect(status(el)).toContain("Added “Book the venue” to this world’s work items");
    const rows = [...el.querySelectorAll('ul[aria-label="Team work items"] li')];
    expect(rows.map((r) => r.textContent)).toEqual(["Book the venueAsha · Open"]);
  });

  it("FR_TEAM_04 says Adding… while waiting and 'Added' only after the live answer", async () => {
    let release: () => void = () => undefined;
    const server = newServer({
      hold: new Promise<void>((resolve) => {
        release = resolve;
      }),
    });
    const { el } = await page(server, await liveApi());
    await type(el, "Title", "Book the venue");
    await add(el);
    expect(status(el)).toContain("Adding the item");
    expect(form(el)?.textContent).not.toContain("Added “");
    expect(named(el, "Add item")?.disabled).toBe(true);
    await act(async () => {
      release();
    });
    expect(status(el)).toContain("Added “Book the venue”");
  });

  it("FR_TEAM_04 a failure says so and Try again resends the same attempt key, with the same text", async () => {
    const server = newServer({ postStatus: 500 });
    const { el } = await page(server, await liveApi());
    await type(el, "Title", "Book the venue");
    await choose(el, "This world’s team");
    await add(el);
    expect(alertOf(el)).toContain("may not have been added");
    expect(form(el)?.textContent).not.toContain("Added “");
    server.postStatus = 201;
    await press(named(el, "Try again"));
    expect(server.posts).toHaveLength(2);
    expect(server.posts[1]?.body).toEqual(server.posts[0]?.body);
    if (server.posts[0]?.key) expect(server.posts[1]?.key).toBe(server.posts[0].key);
    expect(status(el)).toContain("Added “Book the venue”");
    expect(alertOf(el)).toBe("");
  });

  it("FR_TEAM_04 401 says to sign in, 403 says whose worlds, 422 says to check the text; no Try again for them", async () => {
    for (const [code, words] of [
      [401, "sign in"],
      [403, "a world you own or one shared with your team"],
      [422, "title or due date"],
    ] as const) {
      const { el } = await page(newServer({ postStatus: code }), await liveApi());
      await type(el, "Title", "Book the venue");
      await add(el);
      expect(alertOf(el), String(code)).toContain(words);
      expect(named(el, "Try again"), String(code)).toBeUndefined();
      expect(form(el)?.textContent).not.toContain("Added “");
      cleanup();
    }
  });

  it("FR_TEAM_04 an empty title is refused in the form and sends nothing", async () => {
    const server = newServer();
    const { el } = await page(server, await liveApi());
    await type(el, "Title", "   ");
    await add(el);
    expect(alertOf(el)).toContain("Give the item a title");
    expect(server.posts).toEqual([]);
  });

  it("FR_TEAM_04 is not offered on a recorded sample world, nor for a world that is missing", async () => {
    const sample = await page(newServer(), createFixtureApi(), "w_sample_village_basic");
    expect(form(sample.el)).toBeNull();
    cleanup();
    const server = newServer();
    server.world = {};
    const missing = await page(server, await liveApi(null), "w_nobody");
    expect(form(missing.el)).toBeNull();
  });
});

describe("BQ_CTX_TEAMWORLD the world's sharing line", () => {
  it("FR_TEAM_02 names the teams whose latest recorded event is on", async () => {
    const server = newServer({
      events: [
        shareEvent(2, "tm_launch", "on"),
        shareEvent(3, "tm_ops", "on"),
        shareEvent(4, "tm_ops", "off"),
      ],
    });
    const { el } = await page(server, await liveApi());
    expect(line(el)).toContain("Shared with team tm_launch");
    expect(line(el)).toContain("Turned off for tm_ops");
  });

  it("FR_TEAM_02 says sharing is off when every recorded team state is off", async () => {
    const { el } = await page(
      newServer({ events: [shareEvent(2, "tm_launch", "off")] }),
      await liveApi(),
    );
    expect(line(el)).toContain("Team sharing is off");
  });

  it("FR_TEAM_02 shows nothing without a recorded event, and nothing when the events cannot be read", async () => {
    const none = await page(newServer({ events: [] }), await liveApi());
    expect(line(none.el)).toBeNull();
    cleanup();
    const failed = await page(newServer({ events: 500 }), await liveApi());
    expect(line(failed.el)).toBeNull();
    expect(failed.el.textContent).not.toContain("Team sharing");
    const alerts = [...failed.el.querySelectorAll('[role="alert"]')].map((a) => a.textContent);
    expect(alerts.join(" ")).not.toMatch(/shar|events/i); // no error is made of an unreadable feed
  });

  it("FR_TEAM_02 a teammate's page shows the line when its feed carries the event, nothing when it does not", async () => {
    const shown = await page(
      newServer({ events: [shareEvent(2, "tm_launch", "on")] }),
      await liveApi(null),
    );
    expect(line(shown.el)).toContain("Shared with team tm_launch");
    cleanup();
    const hidden = await page(newServer({ events: [] }), await liveApi(null));
    expect(line(hidden.el)).toBeNull();
  });

  it("FR_TEAM_02 the line is plain text with no motion and no control", async () => {
    const server = newServer({ events: [shareEvent(2, "tm_launch", "on")] });
    const { el } = await page(server, await liveApi());
    const node = el.querySelector('[data-testid="park-world-share-line"]');
    expect(node?.querySelector("button, a, input")).toBeNull();
    expect(node?.getAttribute("style") ?? "").not.toMatch(/animation|transition/);
  });
});
