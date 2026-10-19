import { expect, it, vi } from "vitest";
import { redirectDirection } from "./redirectDirection";

it("P0_HALL_ASK_active_world_pauses_before_director_rerun", async () => {
  const calls: string[] = [];
  const client = {
    pauseWorld: vi.fn(async () => {
      calls.push("pause");
    }),
    startAgain: vi.fn(async (_world: string, _direction: string) => {
      calls.push("rerun");
      return { world_id: "w_new", task_id: "t_new" };
    }),
  };
  const next = await redirectDirection(client, "w_old", "Focus on the supplier", "working", false);
  expect(calls).toEqual(["pause", "rerun"]);
  expect(client.startAgain).toHaveBeenCalledWith("w_old", "Focus on the supplier");
  expect(next.world_id).toBe("w_new");
});

it("P0_HALL_ASK_finished_world_reruns_without_pause", async () => {
  const client = {
    pauseWorld: vi.fn(async () => {}),
    startAgain: vi.fn(async () => ({ world_id: "w_new", task_id: "t_new" })),
  };
  await redirectDirection(client, "w_old", "Change the summary", "done", false);
  expect(client.pauseWorld).not.toHaveBeenCalled();
  expect(client.startAgain).toHaveBeenCalledWith("w_old", "Change the summary");
});
