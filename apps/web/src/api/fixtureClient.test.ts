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

  it("HR_6 clamps an extreme ?speed= to a sane range, so the replay and its badge agree (#43)", () => {
    expect(replaySpeedFromSearch("?speed=1e308")).toBe(1000);
    expect(replaySpeedFromSearch("?speed=1e-300")).toBe(0.1);
  });
});

describe("HR_1 the fixture client knows exactly one world", () => {
  it("answers true for the fixture world and false for any other id", () => {
    const client = new FixtureClient();
    expect(client.hasWorld("w_village_basic")).toBe(true);
    for (const id of ["nope", "", "w_village_basic2", "__proto__", "W_VILLAGE_BASIC"]) {
      expect(client.hasWorld(id), id).toBe(false);
    }
  });
});

describe("FR_WLD_07 the fixture client's Pause all (a stand-in for the server that records world.paused)", () => {
  afterEach(() => vi.useRealTimers());

  it("FR_WLD_07 records one world.paused after the last event, then delivers nothing more", async () => {
    vi.useFakeTimers();
    const seen: Event[] = [];
    const client = new FixtureClient({ speed: 100 });
    client.subscribeEvents("w_village_basic", (e) => seen.push(e));
    await vi.advanceTimersByTimeAsync(500);
    const before = seen.length;
    expect(before).toBeGreaterThan(1);
    expect(before).toBeLessThan(44); // paused mid-run
    const lastSeq = seen[before - 1]?.seq ?? 0;
    await client.pauseWorld("w_village_basic");
    const paused = seen[before];
    expect(paused?.type).toBe("world.paused");
    expect(paused?.seq).toBe(lastSeq + 1);
    expect(paused?.data).toEqual({ reason: "pause_all", channel: "web" });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(seen).toHaveLength(before + 1); // no event after the pause except world.paused
  });

  it("FR_WLD_07 with nothing running there is nothing to pause and nothing is recorded", async () => {
    const seen: Event[] = [];
    const client = new FixtureClient();
    await client.pauseWorld("w_village_basic");
    client.subscribeEvents("w_village_basic", (e) => seen.push(e))();
    expect(seen).toEqual([]);
  });
});

describe("FR-HIL-07 stopAutopilot on the fixture client", () => {
  it("records the call and answers honestly: the fixture holds no rule that runs on its own", async () => {
    const client = new FixtureClient();
    expect(client.stopRequests).toEqual([]);
    expect(await client.stopAutopilot("w_village_basic")).toEqual({
      stopped: 0,
      already_l1: 0,
      confirmations: [],
      pending: 0,
    });
    expect(client.stopRequests).toEqual(["w_village_basic"]);
  });
});

describe("NFR-01 a fixture chunk that does not load is said, not left empty", () => {
  afterEach(() => {
    vi.doUnmock("./fixtures/events");
    vi.resetModules();
  });

  it("getLayout rejects with a ChunkLoadError when the recorded run's chunk is missing", async () => {
    vi.resetModules();
    vi.doMock("./fixtures/events", () => {
      throw new Error("Failed to fetch dynamically imported module");
    });
    const { FixtureClient: Fresh } = await import("./fixtureClient");
    const { ChunkLoadError } = await import("./chunkError");
    await expect(new Fresh().getLayout("w_village_basic")).rejects.toBeInstanceOf(ChunkLoadError);
  });
});
