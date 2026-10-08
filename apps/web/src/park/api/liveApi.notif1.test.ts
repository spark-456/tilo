// NOTIF-1 (FR-HIL-01; BQ-NOTIF-1; HR-1..HR-7): `getNotifications` reads `GET {base}/notifications?limit=100` and maps
// the owner's bell. Served fields only: the API's fixed title, no subtitle, no warn kind, no sample.
import { afterEach, describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { NotBuilt, createLiveApi } from "./liveApi";
import { decisionKey } from "./live/decisionsFromCards";

afterEach(() => {
  vi.unstubAllGlobals();
});

const BASE = "https://api.test/v1";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const row = (over: Record<string, unknown> = {}) => ({
  id: "c:card1",
  kind: "needs",
  created_at: "2026-10-08T09:30:00Z",
  world_id: "w1",
  title: "A decision is waiting",
  card_id: "card1",
  artifact_id: null,
  ...over,
});
const apiWith = (make: () => Response) => {
  const spy = vi.fn(async () => make());
  return { spy, api: createLiveApi({ baseUrl: BASE, fetch: spy as unknown as typeof fetch }) };
};

describe("NOTIF_1 live getNotifications", () => {
  it("NOTIF_1 one GET, rows mapped from served fields only, newest first as served", async () => {
    const { api, spy } = apiWith(() =>
      json({
        notifications: [
          row(),
          row({
            id: "e:7",
            kind: "done",
            card_id: null,
            artifact_id: "a1",
            title: "A file is ready",
          }),
        ],
        count: 2,
      }),
    );
    const r = await api.getNotifications();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(String((spy.mock.calls[0] as unknown[])[0])).toBe(`${BASE}/notifications?limit=100`);
    expect(r.source).toBe("live");
    expect(r.data.map((n) => [n.id, n.kind, n.title, n.sub, n.go])).toEqual([
      ["c:card1", "needs", "A decision is waiting", "", ["world", "w1"]],
      ["e:7", "done", "A file is ready", "", ["world", "w1"]],
    ]);
    expect(r.data[0]?.dec).toBe(decisionKey("w1", "card1"));
    expect(r.data[1]?.dec).toBeUndefined();
  });

  it("NOTIF_1 an empty bell is an empty list, not a sample", async () => {
    const { api } = apiWith(() => json({ notifications: [], count: 0 }));
    expect((await api.getNotifications()).data).toEqual([]);
  });

  it("NOTIF_1 an unreadable body rejects TiloApiError and never maps", async () => {
    for (const body of [
      {},
      { notifications: "x" },
      { notifications: [row({ kind: "warn" })] },
      { notifications: [row({ world_id: "" })] },
      { notifications: [row({ title: 3 })] },
    ]) {
      const { api } = apiWith(() => json(body));
      await expect(api.getNotifications()).rejects.toBeInstanceOf(TiloApiError);
    }
  });

  it("NOTIF_1 with no baseUrl it stays NotBuilt and fetches nothing", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    await expect(createLiveApi().getNotifications()).rejects.toBeInstanceOf(NotBuilt);
    expect(spy).not.toHaveBeenCalled();
  });
});
