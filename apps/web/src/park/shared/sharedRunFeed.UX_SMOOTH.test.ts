// UX-SMOOTH: the World page and the live stage read one shared events subscription per world, so a run is polled
// once, and a second reader gets what the first already holds at once instead of downloading the stream again.
import { expect, it, vi } from "vitest";
import { watchWorldEvents } from "./sharedRunFeed";

interface Ev {
  seq: number;
  type: string;
}

it("UX_SMOOTH_two_readers_of_one_world_share_one_subscription", () => {
  let push: ((e: Ev) => void) | undefined;
  const stop = vi.fn();
  const client = {
    subscribeEvents: vi.fn((_id: string, onEvent: (e: Ev) => void) => {
      push = onEvent;
      return stop;
    }),
  };
  const page: Ev[] = [];
  const stage: Ev[] = [];
  const releasePage = watchWorldEvents<Ev>(client, "w_shared", (e) => page.push(e));
  push?.({ seq: 1, type: "world.started" });
  const releaseStage = watchWorldEvents<Ev>(client, "w_shared", (e) => stage.push(e));
  expect(client.subscribeEvents, "one poll loop for the world").toHaveBeenCalledTimes(1);
  expect(
    stage.map((e) => e.seq),
    "the second reader starts from what is held",
  ).toEqual([1]);
  push?.({ seq: 2, type: "agent.spawned" });
  push?.({ seq: 2, type: "agent.spawned" }); // a repeat is ignored
  expect(page.map((e) => e.seq)).toEqual([1, 2]);
  expect(stage.map((e) => e.seq)).toEqual([1, 2]);
  releasePage();
  releaseStage();
});
