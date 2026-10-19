// OLD-UI-OUT wave 3: the Library reads delivered artifacts from the API's own delivery records, one request per
// completed world, and never invents a row (HR-1).
import { describe, expect, it } from "vitest";
import { TiloApiError } from "../../../api/http";
import { MAX_WORLDS, libraryApi } from "./library";

const world = (id: string, status = "completed", extra: object = {}) => ({
  world_id: id,
  status,
  title: `World ${id}`,
  created_at: "2026-10-14T00:00:00Z",
  ...extra,
});
const delivery = (id: string, n: number) => ({
  world_id: id,
  credits_used: 10,
  artifacts: Array.from({ length: n }, (_, i) => ({
    id: `art_${id}_${i}`,
    title: `Report ${id}-${i}`,
    kind: "pdf",
    version: 1,
  })),
});

function fakeHttp(routes: Record<string, unknown>) {
  const asked: string[] = [];
  return {
    asked,
    http: {
      getJson: async (path: string) => {
        asked.push(path);
        const hit = routes[path];
        if (hit instanceof Error) throw hit;
        if (hit === undefined) throw new Error(`unexpected ${path}`);
        return hit;
      },
    },
  };
}

describe("OLD_UI_OUT_3_library: the deliverables of completed worlds", () => {
  it("OLD_UI_OUT_3_library_asks_only_completed_non_sample_worlds_and_lists_their_artifacts", async () => {
    const { http, asked } = fakeHttp({
      "/worlds?limit=100": {
        worlds: [
          world("w1"),
          world("w2", "started"),
          world("w3", "completed", { sample: true }),
          world("w4"),
        ],
        next_cursor: null,
      },
      "/worlds/w1/delivery": delivery("w1", 2),
      "/worlds/w4/delivery": delivery("w4", 1),
    });
    const library = await libraryApi(http).getLibrary();
    expect(asked).toEqual(["/worlds?limit=100", "/worlds/w1/delivery", "/worlds/w4/delivery"]);
    expect(library.items.map((i) => [i.worldId, i.title])).toEqual([
      ["w1", "Report w1-0"],
      ["w1", "Report w1-1"],
      ["w4", "Report w4-0"],
    ]);
    expect(library.unreadable).toBe(0);
    expect(library.truncated).toBe(false);
    expect(library.credits).toBe(20);
  });

  it("OLD_UI_OUT_3_library_counts_a_world_it_could_not_read_and_keeps_the_rest", async () => {
    const { http } = fakeHttp({
      "/worlds?limit=100": { worlds: [world("w1"), world("w2")], next_cursor: null },
      "/worlds/w1/delivery": new TiloApiError("Not found", 404, false),
      "/worlds/w2/delivery": delivery("w2", 1),
    });
    const library = await libraryApi(http).getLibrary();
    expect(library.items).toHaveLength(1);
    expect(library.unreadable).toBe(1);
  });

  it("OLD_UI_OUT_3_library_reads_a_bounded_number_of_worlds_and_says_when_there_are_more", async () => {
    const worlds = Array.from({ length: MAX_WORLDS + 3 }, (_, i) => world(`w${i}`));
    const routes: Record<string, unknown> = { "/worlds?limit=100": { worlds, next_cursor: null } };
    for (const w of worlds) routes[`/worlds/${w.world_id}/delivery`] = delivery(w.world_id, 1);
    const { http, asked } = fakeHttp(routes);
    const library = await libraryApi(http).getLibrary();
    expect(asked).toHaveLength(1 + MAX_WORLDS);
    expect(library.truncated).toBe(true);
  });

  it("OLD_UI_OUT_3_library_a_reply_of_the_wrong_shape_is_an_error_never_rows", async () => {
    const { http } = fakeHttp({ "/worlds?limit=100": { worlds: "nope" } });
    await expect(libraryApi(http).getLibrary()).rejects.toBeInstanceOf(TiloApiError);
  });
});
