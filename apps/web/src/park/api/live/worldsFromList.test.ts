// WIRE-2 (Park wiring, FR-WLD-08 / S-14; PRD 9.4 HR-1..HR-7; services/api/tests/API_S_14_WORLDS_LIST.md): the pure
// mapper from the tilo-api `GET /worlds` items to the Park `World` type.
// Interface pinned here, for the builder:
// - file `apps/web/src/park/api/live/worldsFromList.ts`, named export `worldsFromList(items): World[]` and the
//   exported type `WorldListItem = { world_id: string; title: string | null; status: WorldListStatus;
//   created_at: string | null; last_seq: number }`, `WorldListStatus = "idle"|"started"|"paused"|"completed"|"failed"`.
//   Pure, total, never mutates its input, never imports fixtures. Order is kept (the API sends newest first).
// - served fields map directly: `id` = world_id, `name` = `short` = title, `started` = created_at (ISO string as
//   served; "" when null). Nothing is formatted, truncated or translated.
// - NOT served, so empty, zero or absent, never a sample value: `tool` "", `agents` 0, `spend` "", `spendV` 0,
//   `nextL` "", `nextV` "", `owner` "", and the optionals (`meta`, `prog`, `of`, `budget`, `when`, `isNew`, `plan`,
//   `districts`, `activity`, `row`, `single`, `runs`, `skill`, `out`) absent, null or empty.
// - `tier` is required by the Park type and is not served. Default (BQ-WIRE2-3): "Village", the smallest tier, until
//   the API serves one. A follow-up may make the field optional.
// - null title: the neutral label "Untitled world" (BQ-WIRE2-1), never a scenario name.
// - status (BQ-WIRE2-2): started -> running, completed -> finished (the only exact matches). A world is "needs" only
//   from a recorded open card, which this list does not carry, and "running" only from `world.started`/`resumed`.
//   Everything else is NOT running and NOT needs: idle -> scheduled, paused -> scheduled (stopped, nothing running,
//   no `when` shown), failed -> finished (the run ended; the Park type has no failure state and `out`/`runs` stay empty).
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { worlds as fixtureWorlds } from "../fixtures";
import { type WorldListItem, worldsFromList } from "./worldsFromList";

const item = (over: Partial<WorldListItem> = {}): WorldListItem => ({
  world_id: "w-1",
  title: "Plan the offsite",
  status: "started",
  created_at: "2026-10-07T09:30:00Z",
  last_seq: 12,
  ...over,
});

const STATUSES = ["idle", "started", "paused", "completed", "failed"] as const;
const EXPECTED = {
  idle: "scheduled",
  started: "running",
  paused: "scheduled",
  completed: "finished",
  failed: "finished",
} as const;

const arbItem: fc.Arbitrary<WorldListItem> = fc.record({
  world_id: fc.string({ minLength: 1, maxLength: 12 }),
  title: fc.option(fc.string({ maxLength: 40 }), { nil: null }),
  status: fc.constantFrom(...STATUSES),
  created_at: fc.option(fc.constant("2026-10-07T09:30:00Z"), { nil: null }),
  last_seq: fc.nat(5000),
});

describe("BQ_CTX_TEAMWORLD_worldsFromList: the access marker", () => {
  it("TSW_4b_access_team_is_carried_and_nothing_else_is", () => {
    const [team, own, odd] = worldsFromList([
      item({ world_id: "w-t", access: "team" }),
      item({ world_id: "w-o" }),
      item({ world_id: "w-x", access: "owner" as unknown as "team" }),
    ]);
    expect(team?.access).toBe("team");
    expect(own && "access" in own).toBe(false);
    expect(odd && "access" in odd).toBe(false);
  });
});

describe("WIRE_2_worldsFromList: served fields map directly", () => {
  it("WIRE_2_mapper_id_name_short_come_from_world_id_and_title", () => {
    const [w] = worldsFromList([item({ world_id: "w-9", title: "Quarterly report" })]);
    expect(w?.id).toBe("w-9");
    expect(w?.name).toBe("Quarterly report");
    expect(w?.short).toBe("Quarterly report");
  });

  it("WIRE_2_mapper_a_long_title_is_not_truncated_or_edited", () => {
    const title = `  ${"very long title ".repeat(12)}end `;
    const [w] = worldsFromList([item({ title })]);
    expect(w?.name).toBe(title);
    expect(w?.short).toBe(title);
  });

  it("WIRE_2_mapper_a_null_title_gets_the_neutral_label_Untitled_world", () => {
    const [w] = worldsFromList([item({ title: null })]);
    expect(w?.name).toBe("Untitled world");
    expect(w?.short).toBe("Untitled world");
  });

  it("WIRE_2_mapper_started_is_created_at_as_served_and_empty_when_null", () => {
    const [a, b] = worldsFromList([
      item({ created_at: "2026-10-07T09:30:00Z" }),
      item({ world_id: "w-2", created_at: null }),
    ]);
    expect(a?.started).toBe("2026-10-07T09:30:00Z");
    expect(b?.started).toBe("");
  });

  it("WIRE_2_mapper_keeps_the_order_the_api_sent_and_maps_one_to_one", () => {
    const items = ["c", "a", "b"].map((id) => item({ world_id: id }));
    expect(worldsFromList(items).map((w) => w.id)).toEqual(["c", "a", "b"]);
    expect(worldsFromList([])).toEqual([]);
  });
});

describe("WIRE_2_worldsFromList: status is honest (HR-1, HR-5)", () => {
  it.each(STATUSES)("WIRE_2_mapper_status_%s_maps_to_the_pinned_state", (status) => {
    const [w] = worldsFromList([item({ status })]);
    expect(w?.st).toBe(EXPECTED[status]);
  });

  it("WIRE_2_mapper_property_only_started_is_running_and_needs_is_never_produced", () => {
    fc.assert(
      fc.property(fc.array(arbItem, { maxLength: 20 }), (items) => {
        worldsFromList(items).forEach((w, i) => {
          expect(w.st).not.toBe("needs");
          expect(w.st === "running").toBe(items[i]?.status === "started");
        });
      }),
      { numRuns: 100 },
    );
  });
});

describe("WIRE_2_worldsFromList: nothing is invented (HR-1..HR-7)", () => {
  it("WIRE_2_mapper_fields_the_api_does_not_serve_are_empty_zero_or_absent", () => {
    const [w] = worldsFromList([item()]);
    expect(w).toBeDefined();
    if (!w) return;
    expect(w.tool).toBe("");
    expect(w.agents).toBe(0);
    expect(w.spend).toBe("");
    expect(w.spendV).toBe(0);
    expect(w.nextL).toBe("");
    expect(w.nextV).toBe("");
    expect(w.owner).toBe("");
    for (const key of [
      "meta",
      "prog",
      "of",
      "budget",
      "when",
      "isNew",
      "plan",
      "districts",
      "row",
      "single",
      "runs",
      "skill",
      "out",
    ] as const) {
      expect(w[key] ?? null, `${key} is not served`).toBeNull();
    }
    expect(w.activity ?? []).toEqual([]);
  });

  it("WIRE_2_mapper_tier_is_the_smallest_tier_Village_because_the_type_needs_one", () => {
    expect(worldsFromList([item()])[0]?.tier).toBe("Village");
  });

  it("WIRE_2_mapper_no_world_shares_a_text_or_number_with_the_fixture_worlds", () => {
    const sample = fixtureWorlds({}, []);
    const mapped = worldsFromList(
      STATUSES.map((status, i) => item({ world_id: `w-${i}`, title: null, status })),
    );
    const sampleNames = new Set(sample.flatMap((w) => [w.name, w.short, w.owner, w.spend]));
    for (const w of mapped) {
      expect(sampleNames.has(w.name)).toBe(false);
      expect(w.owner).toBe("");
      expect(w.spend).toBe("");
    }
  });

  it("WIRE_2_mapper_is_pure_it_does_not_mutate_its_input", () => {
    const items = [item(), item({ world_id: "w-2", title: null, status: "failed" })];
    const before = JSON.stringify(items);
    worldsFromList(items);
    expect(JSON.stringify(items)).toBe(before);
  });

  it("WIRE_2_mapper_property_total_one_world_per_item_with_the_item_id", () => {
    fc.assert(
      fc.property(fc.array(arbItem, { maxLength: 30 }), (items) => {
        const out = worldsFromList(items);
        expect(out.map((w) => w.id)).toEqual(items.map((i) => i.world_id));
        for (const w of out) {
          expect(w.name.length).toBeGreaterThan(0);
          expect(["running", "finished", "scheduled"]).toContain(w.st);
        }
      }),
      { numRuns: 100 },
    );
  });

  it("WIRE_2_mapper_is_deterministic", () => {
    fc.assert(
      fc.property(fc.array(arbItem, { maxLength: 20 }), (items) => {
        expect(worldsFromList(items)).toEqual(worldsFromList(items));
      }),
      { numRuns: 50 },
    );
  });
});
