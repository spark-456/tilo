// WIRE-1 (Park wiring, first slice; PRD 9.4 HR-1..HR-7; services/api/tests/API_FR_MTR_10.md): the pure mapper
// from the tilo-api `GET /costs` report (`cost_report`) to the Park `Ledger` type.
// Interface pinned here, for the builder:
// - file `apps/web/src/park/api/live/ledgerFromCosts.ts`, named export `ledgerFromCosts(report): Ledger`.
//   Pure, total on any valid report, never mutates its input, never imports fixtures.
// - served fields only: `spent` = totals.usd (US dollars as served: no currency conversion);
//   profile ids stay internal; work rows use plain labels from `by_task_type`.
//   `by.world.rows` is EMPTY: the report groups by world tier, profile and unit type, never by world.
// - everything the report does not serve is EMPTY or ZERO, never a fixture value: budget 0, forecast 0,
//   daily/tx/runs/memory/hours/activity [], waits {buckets: [], types: []}.
// - each `by.*.head` is a string that is not one of the fixture's sentences (a builder may write "" or a
//   computed sentence; it must not be the prototype's copy).
// The report has no world grouping or model role, so neither is inferred.
import fc from "fast-check";
import { describe, expect, it, vi } from "vitest";
import { ledger as fixtureLedger } from "../fixtures";
import { ledgerFromCosts } from "./ledgerFromCosts";

const REPORT = {
  credit_usd: 0.005,
  totals: {
    tasks: 3,
    completed_tasks: 2,
    credits: 242,
    usd: 1.21,
    credits_saved: 5.5,
    usd_saved: 0.0275,
  },
  tasks: [
    { run_id: "run-a", tier: "outpost", completed: true, credits: 100, usd: 0.5, credits_saved: 0 },
    {
      run_id: "run-b",
      tier: "village",
      completed: true,
      credits: 142,
      usd: 0.71,
      credits_saved: 5.5,
    },
    { run_id: "run-c", tier: null, completed: false, credits: 0, usd: 0, credits_saved: 0 },
  ],
  by_tier: [
    { tier: "outpost", tasks: 1, credits: 100, usd: 0.5, credits_per_task: 100, credits_saved: 0 },
    {
      tier: "village",
      tasks: 1,
      credits: 142,
      usd: 0.71,
      credits_per_task: 142,
      credits_saved: 5.5,
    },
    { tier: null, tasks: 1, credits: 0, usd: 0, credits_per_task: 0, credits_saved: 0 },
  ],
  by_profile: [
    { profile: "fast", tasks: 2, credits: 100, usd: 0.5, credits_per_task: 50 },
    { profile: "deep", tasks: 1, credits: 130, usd: 0.65, credits_per_task: 130 },
    { profile: null, tasks: 1, credits: 12, usd: 0.06, credits_per_task: 12 },
  ],
  by_task_type: [
    { task_type: "research", tasks: 2, credits: 200, usd: 1, credits_per_task: 100 },
    { task_type: "summarise", tasks: 1, credits: 30, usd: 0.15, credits_per_task: 30 },
    { task_type: null, tasks: 1, credits: 12, usd: 0.06, credits_per_task: 12 },
  ],
  by_tier_profile: [
    { tier: "outpost", profile: "fast", tasks: 1, credits: 100, usd: 0.5, credits_per_task: 100 },
  ],
};

const EMPTY_REPORT = {
  credit_usd: 0.005,
  totals: { tasks: 0, completed_tasks: 0, credits: 0, usd: 0, credits_saved: 0, usd_saved: 0 },
  tasks: [],
  by_tier: [],
  by_profile: [],
  by_task_type: [],
  by_tier_profile: [],
};

it("FR_SPD_04_preserves_recorded_run_totals_without_inventing_skill_curves", () => {
  const L = ledgerFromCosts(REPORT);
  expect(L.recordedRuns).toEqual(
    REPORT.tasks.map(({ run_id, usd, completed, credits }) => ({
      id: run_id,
      usd,
      completed,
      credits,
    })),
  );
  expect(L.runs).toEqual([]);
  expect(
    ledgerFromCosts({ totals: { usd: 0 }, by_profile: [], by_task_type: [] }).recordedRuns,
  ).toEqual([]);
});

it("CX_PAGES_ENRICH_LEDGER_uses_plain_language_groups_and_recorded_credits", () => {
  const L = ledgerFromCosts(REPORT);
  expect(L.by.tool.rows).toEqual([]);
  expect(L.by.role.rows).toEqual([
    ["Web search", 1],
    ["Planning and writing", 0.15],
    ["Other work", 0.06],
  ]);
  expect(L.recordedRuns?.[0]?.credits).toBe(100);
  expect(L.totalCredits).toBe(242);
});

it("FR_SPD_05_07_maps_recorded_waits_and_history_without_assuming_approval", () => {
  const L = ledgerFromCosts({
    ...EMPTY_REPORT,
    approval_waits: [{ action_type: "send_email", seconds: 120 }],
    activity: [
      {
        world_id: "world-a",
        card_id: "card-a",
        run_id: "run-a",
        type: "approval.resolved",
        ts: "2026-10-11T09:02:00Z",
        summary: "Held for edits",
      },
    ],
  });
  expect(L.waits.buckets).toEqual([
    ["Under 1 min", 0],
    ["1–5 min", 1],
    ["5–60 min", 0],
    ["1 hour or more", 0],
  ]);
  expect(L.waits.types).toEqual([["send_email", "2.0 min", "neutral"]]);
  expect(L.activity[0]).toMatchObject({
    day: "2026-10-11",
    t: "09:02 UTC",
    k: "answer",
    what: "Held for edits",
  });
  expect(L.activity[0]?.dec).toBeUndefined();
});

it("FR_SPD_07 recorded timestamps are independent of the injected fixed clock", () => {
  const ts = "2026-10-11T14:32:00+05:30";
  const report = {
    ...EMPTY_REPORT,
    activity: [
      {
        world_id: "world-a",
        card_id: "card-a",
        run_id: "run-a",
        type: "approval.requested",
        ts,
        summary: "Recorded request",
      },
    ],
  };
  vi.useFakeTimers({ now: new Date("2020-01-01T00:00:00Z") });
  try {
    const first = ledgerFromCosts(report);
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
    expect(ledgerFromCosts(report)).toEqual(first);
    expect(first.activity[0]).toMatchObject({
      day: "2026-10-11",
      t: "09:02 UTC",
      k: "waiting",
      what: "Recorded request",
      detail: [
        ["Event", "approval.requested"],
        ["Recorded at", ts],
      ],
    });
  } finally {
    vi.useRealTimers();
  }
});

/** Every number anywhere in `v`. */
function numbers(v: unknown): number[] {
  if (typeof v === "number") return [v];
  if (Array.isArray(v)) return v.flatMap(numbers);
  if (v && typeof v === "object") return Object.values(v).flatMap(numbers);
  return [];
}

function deepFreeze<T>(v: T): T {
  if (v && typeof v === "object") {
    for (const x of Object.values(v)) deepFreeze(x);
    Object.freeze(v);
  }
  return v;
}

describe("WIRE_1_ledgerFromCosts: what the report carries", () => {
  it("WIRE_1_ledgerFromCosts_spent_is_the_report_total_in_usd", () => {
    expect(ledgerFromCosts(REPORT).spent).toBeCloseTo(1.21, 10);
  });

  it("CX_PAGES_ENRICH_LEDGER_hides_profile_ids", () => {
    const rows = ledgerFromCosts(REPORT).by.tool.rows;
    expect(rows).toEqual([]);
  });

  it("CX_PAGES_ENRICH_LEDGER_work_rows_use_person_facing_labels", () => {
    const rows = ledgerFromCosts(REPORT).by.role.rows;
    expect(rows.map((r) => r[0])).toEqual(["Web search", "Planning and writing", "Other work"]);
    expect(rows.map((r) => r[1])).toEqual([1, 0.15, 0.06]);
  });

  it("WIRE_1_ledgerFromCosts_by_world_is_empty_the_report_has_no_per_world_group", () => {
    // A world tier (outpost, village, ...) is a size class, not a world: showing it as one would mislabel it.
    expect(ledgerFromCosts(REPORT).by.world.rows).toEqual([]);
  });

  it("WIRE_1_ledgerFromCosts_heads_are_strings_and_never_the_prototype_sentences", () => {
    const { by } = ledgerFromCosts(REPORT);
    const sample = [
      fixtureLedger.by.world.head,
      fixtureLedger.by.tool.head,
      fixtureLedger.by.role.head,
    ];
    for (const k of ["world", "tool", "role"] as const) {
      expect(typeof by[k].head, `by.${k}.head`).toBe("string");
      expect(sample, `by.${k}.head is a fixture sentence`).not.toContain(by[k].head);
    }
  });
});

describe("WIRE_1_ledgerFromCosts: what the report does not carry stays empty (HR-1..HR-7)", () => {
  it("WIRE_1_ledgerFromCosts_unserved_fields_are_empty_or_zero", () => {
    const L = ledgerFromCosts(REPORT);
    expect(L.budget).toBe(0);
    expect(L.forecast).toBe(0);
    expect(L.daily).toEqual([]);
    expect(L.tx).toEqual([]);
    expect(L.runs).toEqual([]);
    expect(L.waits).toEqual({ buckets: [], types: [] });
    expect(L.memory).toEqual([]);
    expect(L.hours).toEqual([]);
    expect(L.activity).toEqual([]);
  });

  it("WIRE_1_ledgerFromCosts_no_fixture_value_appears_in_the_result", () => {
    const text = JSON.stringify(ledgerFromCosts(REPORT));
    for (const row of fixtureLedger.by.world.rows) expect(text).not.toContain(row[0]);
    for (const row of fixtureLedger.by.tool.rows) expect(text).not.toContain(row[0]);
    for (const row of fixtureLedger.by.role.rows) expect(text).not.toContain(row[0]);
    expect(text).not.toContain(fixtureLedger.by.world.head);
    expect(ledgerFromCosts(REPORT)).not.toEqual(fixtureLedger);
    expect(ledgerFromCosts(EMPTY_REPORT).spent).not.toBe(fixtureLedger.spent);
  });

  it("WIRE_1_ledgerFromCosts_an_empty_report_is_all_zero_and_empty_and_finite", () => {
    const L = ledgerFromCosts(EMPTY_REPORT);
    expect(L.spent).toBe(0);
    expect(L.budget).toBe(0);
    expect(L.forecast).toBe(0);
    for (const k of ["world", "tool", "role"] as const) expect(L.by[k].rows).toEqual([]);
    expect(numbers(L).every(Number.isFinite)).toBe(true);
    expect(JSON.stringify(L)).not.toMatch(/NaN|Infinity/);
  });

  it("WIRE_1_ledgerFromCosts_does_not_change_its_input", () => {
    const frozen = deepFreeze(structuredClone(REPORT));
    expect(() => ledgerFromCosts(frozen)).not.toThrow();
    expect(frozen).toEqual(REPORT);
  });
});

describe("WIRE_1_ledgerFromCosts: property", () => {
  const usd = fc.double({ min: 0, max: 1e6, noNaN: true, noDefaultInfinity: true });
  const label = fc.option(fc.stringMatching(/^[a-z][a-z0-9-]{0,15}$/), { nil: null });
  const reports = fc.record({
    credit_usd: fc.constant(0.005),
    totals: usd.map((u) => ({
      tasks: 1,
      completed_tasks: 1,
      credits: u / 0.005,
      usd: u,
      credits_saved: 0,
      usd_saved: 0,
    })),
    tasks: fc.constant([]),
    by_tier: fc.constant([]),
    by_profile: fc.array(
      fc.record({
        profile: label,
        tasks: fc.constant(1),
        credits: usd,
        usd,
        credits_per_task: usd,
      }),
      { maxLength: 6 },
    ),
    by_task_type: fc.array(
      fc.record({
        task_type: label,
        tasks: fc.constant(1),
        credits: usd,
        usd,
        credits_per_task: usd,
      }),
      { maxLength: 6 },
    ),
    by_tier_profile: fc.constant([]),
  });

  it("WIRE_1_ledgerFromCosts_property_finite_spent_equals_total_one_row_per_group_unserved_empty", () => {
    fc.assert(
      fc.property(reports, (report) => {
        const L = ledgerFromCosts(report);
        expect(L.spent).toBe(report.totals.usd);
        expect(L.by.tool.rows).toEqual([]);
        expect(L.by.role.rows.length).toBeLessThanOrEqual(report.by_task_type.length);
        expect(L.by.world.rows).toEqual([]);
        expect([L.budget, L.forecast]).toEqual([0, 0]);
        expect(
          [L.daily, L.tx, L.runs, L.memory, L.hours, L.activity].every((a) => a.length === 0),
        ).toBe(true);
        expect(numbers(L).every(Number.isFinite)).toBe(true);
      }),
      { numRuns: 100 },
    );
  });
});

describe("WIRE_1_ledgerFromCosts: currency", () => {
  it("WIRE_1_ledgerFromCosts_amounts_are_marked_usd_as_the_report_serves_them", () => {
    expect(ledgerFromCosts(REPORT).currency).toBe("USD");
    expect(ledgerFromCosts(EMPTY_REPORT).currency).toBe("USD");
  });
});
