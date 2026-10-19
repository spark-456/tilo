// BQ-CTX-TEAMWORLD (ADR-0040 decision 9; FR-TEAM-02, HR-1): the world's sharing line is derived only from the world's
// recorded `world.share_changed` events, the latest per team. Nothing is shown that has no recorded event behind
// it, and an event feed this reader cannot be sure of shows nothing rather than a guess.
import { describe, expect, it, vi } from "vitest";
import { HttpClient } from "../../../api/http";
import { readShareLine, shareLineFromEvents } from "./shareLine";

const W = "w_launch";
const changed = (seq: number, team: string, state: string, over: Record<string, unknown> = {}) => ({
  id: `01JB5VQ00000000000000${String(seq).padStart(5, "0")}`,
  seq,
  world_id: W,
  type: "world.share_changed",
  actor: "u_asha",
  vis: [],
  data: { team, state },
  ...over,
});
const other = (seq: number) => ({
  id: `e${seq}`,
  seq,
  world_id: W,
  type: "world.started",
  data: {},
});

describe("BQ_CTX_TEAMWORLD the sharing line from recorded events", () => {
  it("FR_TEAM_02 takes the latest event of each team by seq, whatever the order of the feed", () => {
    const line = shareLineFromEvents(
      [changed(9, "tm_a", "off"), changed(3, "tm_a", "on"), other(4), changed(5, "tm_b", "on")],
      W,
    );
    expect(line).toEqual({ on: ["tm_b"], off: ["tm_a"] });
  });

  it("FR_TEAM_02 a team turned on again after off is on", () => {
    expect(
      shareLineFromEvents(
        [changed(1, "tm_a", "on"), changed(2, "tm_a", "off"), changed(3, "tm_a", "on")],
        W,
      ),
    ).toEqual({ on: ["tm_a"], off: [] });
  });

  it("FR_TEAM_02 no share event is no line: nothing is shown that was not recorded", () => {
    expect(shareLineFromEvents([other(1), other(2)], W)).toEqual({ on: [], off: [] });
    expect(shareLineFromEvents([], W)).toEqual({ on: [], off: [] });
  });

  it("FR_TEAM_02 a share event this page cannot read well makes the whole line unreadable", () => {
    for (const bad of [
      changed(1, "tm_a", "maybe"),
      changed(1, "", "on"),
      changed(1, "tm_a", "on", { data: null }),
      changed(1, "tm_a", "on", { world_id: "w_other" }),
      changed(1, "tm_a", "on", { seq: "1" }),
    ])
      expect(shareLineFromEvents([changed(0, "tm_b", "on"), bad], W)).toBeNull();
  });

  it("FR_TEAM_02 other events are not read for their meaning, whatever they say", () => {
    const lookalike = { ...other(2), data: { team: "tm_a", state: "on" } };
    expect(shareLineFromEvents([lookalike], W)).toEqual({ on: [], off: [] });
  });
});

describe("BQ_CTX_TEAMWORLD reading the feed", () => {
  const reply = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  const client = (fetch: typeof globalThis.fetch) =>
    new HttpClient({ baseUrl: "https://api.test", fetch });

  it("FR_TEAM_02 reads GET /worlds/{id}/events once and derives the line", async () => {
    const fetch = vi.fn(async () => reply({ events: [changed(1, "tm_a", "on")] }));
    expect(await readShareLine(client(fetch), W)).toEqual({ on: ["tm_a"], off: [] });
    expect(fetch).toHaveBeenCalledTimes(1);
    const first = fetch.mock.calls[0] as unknown as [string];
    expect(new URL(first[0]).pathname).toBe(`/worlds/${W}/events`);
  });

  it("FR_TEAM_02 a feed that is not a list of events, or fails, is unreadable (null), never an error shown", async () => {
    expect(await readShareLine(client(vi.fn(async () => reply({ events: "x" }))), W)).toBeNull();
    expect(await readShareLine(client(vi.fn(async () => reply({}))), W)).toBeNull();
    expect(await readShareLine(client(vi.fn(async () => reply({}, 500))), W)).toBeNull();
    expect(await readShareLine(client(vi.fn(async () => reply({}, 404))), W)).toBeNull();
    expect(
      await readShareLine(
        client(
          vi.fn(async () => {
            throw new Error("offline");
          }),
        ),
        W,
      ),
    ).toBeNull();
  });
});
