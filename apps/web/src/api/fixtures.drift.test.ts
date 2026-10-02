// PRD-18.3 flow: the typed fixture modules are copies of contracts/fixtures. The JSON is read
// here, in the test only, never at runtime.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { BRIEF_SUPPLIER_COMPARISON } from "./fixtures/brief";
import { CARDS_VALID } from "./fixtures/cards";
import {
  FIXTURE_APPROACHES,
  FIXTURE_DELIVERY,
  FIXTURE_QUESTIONS,
  FIXTURE_WORLD_ID,
} from "./fixtures/derived";
import { EVENTS_VILLAGE_BASIC } from "./fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "./fixtures/layout";
import { PLAN_TWO_APPROACHES } from "./fixtures/plan";

const root = fileURLToPath(new URL("../../../../contracts/fixtures/", import.meta.url));
const text = (path: string): string => readFileSync(`${root}${path}`, "utf8");
const json = (path: string): unknown => JSON.parse(text(path));

describe("PRD-18.3 flow: fixture modules deep-equal their contracts/fixtures source", () => {
  it("brief", () => {
    expect(BRIEF_SUPPLIER_COMPARISON).toEqual(json("brief/valid/supplier_comparison.json"));
  });
  it("plan", () => {
    expect(PLAN_TWO_APPROACHES).toEqual(json("plan/valid/two_approaches_email_send_gated.json"));
  });
  it("layout", () => {
    expect(LAYOUT_VILLAGE_BASIC).toEqual(json("layout/valid/village_basic.json"));
  });
  it("cards, every valid fixture in the directory, in file-name order", () => {
    // Read from the directory, not a fixed list, so a new card/valid fixture cannot go unnoticed.
    const files = readdirSync(`${root}card/valid`)
      .filter((f) => f.endsWith(".json"))
      .sort();
    expect(files.length).toBeGreaterThan(0);
    expect(CARDS_VALID).toEqual(files.map((f) => json(`card/valid/${f}`)));
  });
  it("events, the full 44-event stream in file order", () => {
    const lines = text("streams/village-basic.jsonl")
      .split("\n")
      .filter((l) => l.trim());
    expect(lines).toHaveLength(44);
    expect(EVENTS_VILLAGE_BASIC).toEqual(lines.map((l) => JSON.parse(l)));
    expect(EVENTS_VILLAGE_BASIC.map((e) => e.seq)).toEqual(lines.map((_, i) => i + 1));
  });
});

describe("PRD-18.3 flow: derived fixture values match the contract fixtures they come from", () => {
  const stream = EVENTS_VILLAGE_BASIC;

  it("the world id is the stream's and the layout's", () => {
    expect(new Set(stream.map((e) => e.world_id))).toEqual(new Set([FIXTURE_WORLD_ID]));
    expect(LAYOUT_VILLAGE_BASIC.world_id).toBe(FIXTURE_WORLD_ID);
  });

  it("the recommendation and the credit rate come from the plan and config/prices.yaml", () => {
    expect(FIXTURE_APPROACHES.recommended).toBe(PLAN_TWO_APPROACHES.chosen_approach);
    expect(FIXTURE_APPROACHES.approaches).toEqual(PLAN_TWO_APPROACHES.approaches);
    const rate = /^credit_usd:\s*([0-9.]+)/m.exec(
      readFileSync(`${root}../../config/prices.yaml`, "utf8"),
    );
    expect(FIXTURE_APPROACHES.credit_usd).toBe(Number(rate?.[1]));
  });

  it("the questions are the brief's skipped-question assumptions", () => {
    expect(FIXTURE_QUESTIONS).toEqual([
      {
        field: "assumptions",
        text: "Should shipping costs be included?",
        suggested_answers: ["Shipping is included in each total"],
      },
    ]);
  });

  it("the delivery is the stream's delivered artifact, credits used and the meter's estimate", () => {
    const created = stream.find(
      (e) => e.type === "artifact.created" && e.item?.artifact_id === "art_triage_list",
    );
    const delivered = stream.find((e) => e.type === "artifact.delivered");
    const completed = stream.find((e) => e.type === "world.completed");
    const [only] = FIXTURE_DELIVERY.artifacts;
    expect(only?.id).toBe(delivered?.item?.artifact_id);
    expect(only?.title).toBe(created?.item?.label);
    expect(only?.kind).toBe(created?.item?.kind);
    expect(FIXTURE_DELIVERY.credits_used).toBe(
      (completed?.data as { credits_used: number }).credits_used,
    );
    const meter = json("meter/valid/live_run.json") as {
      time_saved: { low: number; high: number };
    };
    expect(FIXTURE_DELIVERY.time_saved).toEqual({
      low_min: meter.time_saved.low,
      high_min: meter.time_saved.high,
    });
  });
});
