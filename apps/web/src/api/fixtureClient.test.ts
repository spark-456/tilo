import type { Event } from "@tilo/contracts";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TiloClient } from "./client";
import { FixtureClient, replaySpeedFromSearch } from "./fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "./fixtures/events";

describe("PRD-18.3 flow: the fixture client returns contract-typed brief, approaches, cards and layout", () => {
  it("answers every request from the contract fixtures", async () => {
    const client: TiloClient = new FixtureClient();

    const intake = await client.submitIntake("Compare the quotes", [
      new File(["x"], "quote_a.pdf"),
    ]);
    expect(intake.brief.goal).toBe(
      "Compare three suppliers' quotes for 500 scooter battery packs and recommend one.",
    );
    expect(intake.files).toEqual([
      { name: "quote_a.pdf", status: "ok", safety_flagged: false, reason: null },
    ]);
    expect(intake.questions[0]?.suggested_answers[0]).toBe("Shipping is included in each total");

    const answered = await client.answerQuestions(intake.task_id, [], { audience: "Finance" });
    expect(answered.brief.audience).toBe("Finance");

    const approaches = await client.getApproaches(intake.task_id);
    expect(approaches.task_id).toBe(intake.task_id);
    expect(approaches.approaches.map((a) => a.id)).toEqual(["quick", "thorough"]);
    expect(approaches.recommended).toBe("quick");
    expect(approaches.credit_usd).toBe(0.005);

    const { world_id } = await client.approve(intake.task_id, {
      approach_id: "quick",
      budget_cap: 45,
    });
    expect(world_id).toBe("w_village_basic");
    expect((await client.getLayout(world_id)).world_id).toBe(world_id);

    const cards = await client.listCards(world_id);
    expect(cards).toHaveLength(6);
    expect(cards.every((c) => c.world_id === world_id)).toBe(true);
    const first = cards[0];
    if (!first) throw new Error("no card");
    await client.answerCard(first.id, { option_id: "approve" });
    expect(await client.listCards(world_id)).toHaveLength(5);

    const delivery = await client.getDelivery(world_id);
    expect(delivery.world_id).toBe(world_id);
    expect(delivery.artifacts[0]?.id).toBe("art_triage_list");
  });

  it("adds the configured latency to requests", async () => {
    vi.useFakeTimers();
    const client = new FixtureClient({ delayMs: 300 });
    let done = false;
    void client.getApproaches("t").then(() => {
      done = true;
    });
    await vi.advanceTimersByTimeAsync(299);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(done).toBe(true);
  });
});

describe("PRD-18.3 flow: the fixture client replays events in seq order and stops after unsubscribe", () => {
  afterEach(() => vi.useRealTimers());

  it("replays all 44 events in seq order, on the recorded ts gaps divided by speed", async () => {
    vi.useFakeTimers();
    const seen: Event[] = [];
    new FixtureClient({ speed: 10 }).subscribeEvents("w_village_basic", (e) => seen.push(e));
    await vi.advanceTimersByTimeAsync(0);
    expect(seen.map((e) => e.seq)).toEqual([1]);

    const gap =
      Date.parse(EVENTS_VILLAGE_BASIC[1]?.ts ?? "") - Date.parse(EVENTS_VILLAGE_BASIC[0]?.ts ?? "");
    await vi.advanceTimersByTimeAsync(gap / 10 - 1);
    expect(seen).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(seen).toHaveLength(2);

    await vi.runAllTimersAsync();
    expect(seen).toHaveLength(44);
    expect(seen.map((e) => e.seq)).toEqual([...seen.map((e) => e.seq)].sort((a, b) => a - b));
  });

  it("stops after unsubscribe", async () => {
    vi.useFakeTimers();
    const seen: Event[] = [];
    const stop = new FixtureClient({ speed: 1000 }).subscribeEvents("w", (e) => seen.push(e));
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    const count = seen.length;
    expect(count).toBeGreaterThan(0);
    stop();
    await vi.runAllTimersAsync();
    expect(seen).toHaveLength(count);
  });

  it("reads the speed from ?speed= like the world replay does", () => {
    expect(replaySpeedFromSearch("?speed=8")).toBe(8);
    for (const bad of ["", "?speed=0", "?speed=-2", "?speed=x"]) {
      expect(replaySpeedFromSearch(bad)).toBe(1);
    }
  });
});
