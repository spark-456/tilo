// The Park `Ledger` from the tilo-api `GET /costs` report (WIRE-1; PRD 9.4 HR-1..HR-7). Pure and total.
// Only what the report serves is carried: `spent` is totals.usd (US dollars as served, so `currency` is USD), the tool rows come
// from by_profile and the role rows from by_task_type (BQ-WIRE1-1: the PRD has no mapping). Everything the
// report does not serve is empty or zero, never a sample value. No fixture is imported.
import type { Ledger } from "../types";
import { decisionKey } from "./decisionsFromCards";

export interface CostGroupRow {
  usd: number;
  profile?: string | null;
  task_type?: string | null;
}

/** The part of the `cost_report` this mapper reads. */
export interface CostReport {
  totals: { usd: number };
  by_profile: readonly CostGroupRow[];
  by_task_type: readonly CostGroupRow[];
  tasks?: readonly { run_id: string; usd: number; completed: boolean }[];
  approval_waits?: readonly { action_type: string; seconds: number }[];
  activity?: readonly {
    world_id: string;
    run_id: string;
    card_id: string;
    type: string;
    ts: string;
    summary: string;
  }[];
}

const UNLABELLED = "Unlabelled";

const rowsOf = (
  groups: readonly CostGroupRow[],
  label: "profile" | "task_type",
): [string, number][] => groups.map((g) => [g[label] ?? UNLABELLED, g.usd]);

export function ledgerFromCosts(report: CostReport): Ledger {
  const waits = report.approval_waits ?? [];
  const ranges = [60, 300, 3600, Number.POSITIVE_INFINITY];
  const labels = ["Under 1 min", "1–5 min", "5–60 min", "1 hour or more"];
  const types = [...new Set(waits.map((w) => w.action_type))];
  const history = report.activity ?? [];
  const latest = new Set<string>();
  const activity = history.map((e) => {
    const key = decisionKey(e.world_id, e.card_id);
    const pending = !latest.has(key) && e.type === "approval.requested";
    latest.add(key);
    const at = new Date(e.ts).toISOString();
    return {
      day: at.slice(0, 10),
      t: `${at.slice(11, 16)} UTC`,
      world: e.world_id,
      k: pending ? "waiting" : e.type === "approval.requested" ? "request" : "answer",
      ...(pending ? { dec: key } : {}),
      what: e.summary,
      sub: e.run_id,
      amt: "",
      detail: [
        ["Event", e.type],
        ["Recorded at", e.ts],
        ["Run", e.run_id],
      ] as [string, string][],
    };
  });
  return {
    budget: 0,
    spent: report.totals.usd,
    forecast: 0,
    daily: [],
    by: {
      world: { head: "", rows: [] },
      tool: { head: "", rows: rowsOf(report.by_profile, "profile") },
      role: { head: "", rows: rowsOf(report.by_task_type, "task_type") },
    },
    tx: [],
    runs: [],
    recordedRuns: (report.tasks ?? []).map(({ run_id, usd, completed }) => ({
      id: run_id,
      usd,
      completed,
    })),
    waits: {
      buckets: waits.length
        ? labels.map((label, i) => [
            label,
            waits.filter(
              (w) => w.seconds < (ranges[i] ?? 0) && (i === 0 || w.seconds >= (ranges[i - 1] ?? 0)),
            ).length,
          ])
        : [],
      types: types.map((type) => {
        const values = waits.filter((w) => w.action_type === type);
        return [
          type,
          `${(values.reduce((sum, w) => sum + w.seconds, 0) / values.length / 60).toFixed(1)} min`,
          "neutral",
        ];
      }),
    },
    memory: [],
    hours: [],
    activity,
    // The report's amounts are its `usd` fields, so they are shown as dollars, never as pounds.
    currency: "USD",
  };
}
