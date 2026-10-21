// UX-SMOOTH: a started run is not an Api write, so it forgets the cached reads itself: the World page it opens reads
// the world list from the server, not the one read before the run existed.
import { expect, it, vi } from "vitest";
import { createFixtureApi } from "./fixtureApi";
import { forgetReads } from "./readCache";
import { withSwr } from "./swr";

it("UX_SMOOTH_forgetReads_sends_the_next_world_list_read_to_the_server", async () => {
  const api = createFixtureApi();
  const server = vi.fn(async () => ({ data: [], source: "live" as const }));
  api.getWorlds = server;
  const cached = withSwr(
    api,
    () => "owner@example.com",
    () => undefined,
    () => 0,
  );
  await cached.getWorlds({}, []);
  await cached.getWorlds({}, []);
  expect(server, "the second read is answered from the cache").toHaveBeenCalledTimes(1);
  forgetReads();
  await cached.getWorlds({}, []);
  expect(server).toHaveBeenCalledTimes(2);
});
