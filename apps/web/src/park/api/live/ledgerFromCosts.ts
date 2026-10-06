// The Park `Ledger` from the tilo-api `GET /costs` report (WIRE-1; PRD 9.4 HR-1..HR-7). Pure and total.
// Only what the report serves is carried: `spent` is totals.usd (US dollars as served), the tool rows come
// from by_profile and the role rows from by_task_type (BQ-WIRE1-1: the PRD has no mapping). Everything the
// report does not serve is empty or zero, never a sample value. No fixture is imported.
import type { Ledger } from "../types";

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
}

const UNLABELLED = "Unlabelled";

const rowsOf = (
  groups: readonly CostGroupRow[],
  label: "profile" | "task_type",
): [string, number][] => groups.map((g) => [g[label] ?? UNLABELLED, g.usd]);

export function ledgerFromCosts(report: CostReport): Ledger {
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
    waits: { buckets: [], types: [] },
    memory: [],
    hours: [],
    activity: [],
  };
}
