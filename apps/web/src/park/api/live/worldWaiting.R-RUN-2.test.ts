import { describe, expect, it } from "vitest";
import { worldFromIntake } from "./worldFromIntake";
import { worldsFromList } from "./worldsFromList";

describe("R-RUN-2 waiting worlds", () => {
  it("R_RUN_2_a_new_skill_tagged_world_needs_approval_instead_of_claiming_a_schedule", () => {
    const world = worldFromIntake(
      "workspace",
      { task_id: "t_youtube", brief: { goal: "@youtubeskills" } },
      "@youtubeskills",
    );
    expect(world.st).toBe("needs");
    expect(world.nextV).toBe("Waiting for your approval");
  });

  it("R_RUN_2_idle_and_paused_worlds_never_claim_a_schedule_without_schedule_data", () => {
    const base = {
      title: "Help me with Youtube skill",
      created_at: "2026-10-18T08:00:00Z",
      last_seq: 2,
    };
    const worlds = worldsFromList([
      { ...base, world_id: "w_idle", status: "idle" },
      { ...base, world_id: "w_paused", status: "paused" },
    ]);
    expect(worlds.map((world) => world.st)).toEqual(["needs", "needs"]);
    expect(worlds.some((world) => world.st === "scheduled")).toBe(false);
  });
});
