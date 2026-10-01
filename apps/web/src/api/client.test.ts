import type { Event } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import type { TiloClient } from "./client";
import { FixtureClient } from "./fixtureClient";

describe("PRD-18.3 flow: the fixture client returns contract-typed brief, approaches, cards and layout", () => {
  it("returns contract-typed data", async () => {
    const client: TiloClient = new FixtureClient({ delayMs: 0 });
    const taskId = "task-1";
    const worldId = "w_village_basic";

    const intake = await client.submitIntake("Triage inbox", []);
    expect(intake.taskId).toBe("task-1");
    expect(intake.brief.goal).toBe("Triage inbox");
    expect(intake.questions.length).toBeGreaterThan(0);

    const answered = await client.answerQuestions(taskId, { q_slot: "Thursday 15:00" });
    expect(answered.brief.goal).toBe("Triage inbox");

    const approaches = await client.getApproaches(taskId);
    expect(approaches.approaches.length).toBeGreaterThanOrEqual(2);
    expect(approaches.recommendedId).toBe("quick");

    const approved = await client.approve(taskId, "quick", 40);
    expect(approved.worldId).toBe(worldId);

    const cards = await client.listCards(worldId);
    expect(cards.length).toBe(1);

    const layout = await client.getLayout(worldId);
    expect(layout.world_id).toBe(worldId);
    expect(layout.semantic.levels.length).toBeGreaterThan(0);

    const delivery = await client.getDelivery(worldId);
    expect(delivery.artifacts.length).toBeGreaterThan(0);
  });
});

describe("PRD-18.3 flow: the fixture client replays events in seq order and stops after unsubscribe", () => {
  it("replays events in seq order and stops after unsubscribe", async () => {
    const client = new FixtureClient({ delayMs: 0, intervalMs: 5 });
    const events: Event[] = [];
    let unsub!: () => void;

    await new Promise<void>((resolve) => {
      unsub = client.subscribeEvents("w_village_basic", (e) => {
        events.push(e);
        if (events.length >= 3) {
          unsub();
          resolve();
        }
      });
    });

    expect(events.length).toBe(3);
    expect(events[0]?.seq).toBeLessThan(events[1]?.seq ?? 0);
    expect(events[1]?.seq).toBeLessThan(events[2]?.seq ?? 0);

    const countBefore = events.length;
    await new Promise((r) => setTimeout(r, 30));
    expect(events.length).toBe(countBefore);
  });
});
