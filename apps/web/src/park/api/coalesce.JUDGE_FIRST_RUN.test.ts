// JUDGE-FIRST-RUN F6: a page load asks for the worlds list and the cards more than once at the same moment; the server is
// asked once while a read is out, and every asker gets that answer. Nothing is kept once it has settled.
import { describe, expect, it, vi } from "vitest";
import { coalesce } from "./coalesce";
import { createLiveApi } from "./liveApi";

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

describe("JUDGE_FIRST_RUN_F6 coalesce", () => {
  it("shares one read between askers that overlap and reads again after it settled", async () => {
    let release: (n: number) => void = () => undefined;
    const read = vi.fn(
      (_key: string) =>
        new Promise<number>((resolve) => {
          release = resolve;
        }),
    );
    const get = coalesce(read);
    const a = get("k");
    const b = get("k");
    expect(read).toHaveBeenCalledTimes(1);
    release(7);
    expect(await Promise.all([a, b])).toEqual([7, 7]);
    const c = get("k");
    expect(read).toHaveBeenCalledTimes(2); // nothing is remembered: the next ask is a fresh read
    release(8);
    expect(await c).toBe(8);
  });

  it("keeps different keys apart and does not remember a failure", async () => {
    const read = vi
      .fn<(key: string) => Promise<string>>()
      .mockRejectedValueOnce(new Error("down"))
      .mockImplementation(async (key) => key);
    const get = coalesce(read);
    await expect(get("a")).rejects.toThrow("down");
    expect(await get("a")).toBe("a");
    expect(await Promise.all([get("x"), get("y")])).toEqual(["x", "y"]);
  });
});

describe("JUDGE_FIRST_RUN_F6 live Api", () => {
  it("asks the server once for the worlds list and once for the cards when two callers overlap", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      calls.push(new URL(url).pathname);
      if (url.includes("/worlds")) return json({ worlds: [], next_cursor: null });
      if (url.includes("/cards")) return json({ cards: [], next_cursor: null, count: 0 });
      return json({});
    });
    const api = createLiveApi({
      baseUrl: "https://api.example.test",
      fetch: fetchMock as unknown as typeof fetch,
    });
    const [w1, w2, w3, d1, d2] = await Promise.all([
      api.getWorlds({}, []),
      api.getWorlds({}, []),
      api.getWorlds({}, []),
      api.getDecisions(),
      api.getDecisions(),
    ]);
    expect(calls.filter((p) => p === "/worlds")).toHaveLength(1);
    expect(calls.filter((p) => p === "/cards")).toHaveLength(1);
    expect([w1.data, w2.data, w3.data]).toEqual([[], [], []]);
    expect([d1.data, d2.data]).toEqual([[], []]);
    await api.getWorlds({}, []); // a later ask is a new read
    expect(calls.filter((p) => p === "/worlds")).toHaveLength(2);
  });
});
