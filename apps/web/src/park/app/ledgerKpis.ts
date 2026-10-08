// The Ledger's five KPI tiles and the money rules under them (FR-SPD-01), shared by the Ledger and Home pages so
// both read one function of the ledger they were given. Typed port of the renderVals() of
// design_handoff_tilo_web_app/design/Tilo App Ledger.dc.html (user's prototype, ADR-0003a). Pure: no clock,
// no random, no network.
import type { Dec, Decision, DecisionKey, Ledger } from "../api/types";
import type { KpiTone } from "../components";

const amount = (v: number): string =>
  v < 100 && v % 1 ? v.toFixed(2) : Math.round(v).toLocaleString("en-GB");
export const gbp = (v: number): string => `£${amount(v)}`;
/** An amount in the Ledger's own currency: a live Ledger served in dollars is never shown as pounds. */
export const money = (L: Ledger, v: number): string =>
  L.currency === "USD" ? `$${amount(v)}` : gbp(v);

/** The decision the ledger is waiting on: the one its pending transaction is tied to. */
export const waitingKey = (L: Ledger): DecisionKey | undefined => L.tx.find((t) => t.dec)?.dec;

/** The amount that pending transaction is waiting on. */
export const waitingAmount = (L: Ledger): number => L.tx.find((t) => t.dec)?.amt ?? 0;

/** Whether the person has taken the decision the ledger was waiting on. */
export const waitingTaken = (L: Ledger, dec: Dec): boolean => {
  const k = waitingKey(L);
  return k !== undefined && !!dec[k];
};

/** The decision for `key` from the Api: its `world` to open and its `facts` (the words) come from there. */
export const decisionOf = (decisions: readonly Decision[], key: DecisionKey | undefined) =>
  decisions.find((d) => d.k === key);

// ---- KPI tiles ----
export interface KpiRow {
  label: string;
  value: string;
  sub: string;
  tone?: KpiTone;
  /** The amber tile opens the world that is waiting. */
  opensWorld?: string;
}

export const sum = (xs: readonly number[]): number => xs.reduce((a, v) => a + v, 0);

/**
 * "Up £120 on August": only from the comparison the ledger itself holds (`memoryUp`), and only while it still
 * describes the series being shown (its `total` is the sum of `memory`). Otherwise the tile has no sub line:
 * a figure the ledger does not hold is never typed in (HR-1).
 */
const memoryUpSub = (L: Ledger): string => {
  const up = L.memoryUp;
  if (!up || up.total !== sum(L.memory)) return "";
  return `${up.amount < 0 ? "Down" : "Up"} ${money(L, Math.abs(up.amount))} on ${up.since}`;
};

export function kpis(L: Ledger, dec: Dec, decisions: readonly Decision[] = []): KpiRow[] {
  const waiting = waitingAmount(L);
  const taken = waitingTaken(L, dec);
  const pending = decisionOf(decisions, waitingKey(L));
  const spent = taken ? L.spent + waiting : L.spent;
  const hours = sum(L.hours.map((h) => h[1]));
  // A tile the Ledger holds no data for is left out, not shown as zero (HR-1..HR-7): no budget gives no
  // share of it, no forecast no month-end tile, no waiting transaction no "Waiting on you", and so on.
  const rows: (KpiRow | null)[] = [
    {
      label: "Spent so far",
      value: money(L, spent),
      sub: L.budget > 0 ? `${Math.round((spent / L.budget) * 100)}% of ${money(L, L.budget)}` : "",
    },
    L.forecast > 0 && L.budget > 0
      ? {
          label: "Month-end forecast",
          value: money(L, L.forecast),
          sub: `${money(L, L.budget - L.forecast)} under budget`,
        }
      : null,
    waitingKey(L) === undefined
      ? null
      : taken
        ? {
            label: "Waiting on you",
            value: money(L, 0),
            sub: pending?.facts?.decided ?? "Approved today",
            tone: "ok",
          }
        : {
            label: "Waiting on you",
            value: money(L, waiting),
            sub: pending?.facts?.waiting ?? "Needs your sign-off",
            tone: "amber",
            ...(pending ? { opensWorld: pending.world } : {}),
          },
    L.memory.length
      ? {
          label: "Saved by memory",
          value: money(L, sum(L.memory)),
          sub: memoryUpSub(L),
          tone: "sch",
        }
      : null,
    L.hours.length
      ? {
          label: "Hours handed back",
          value: `${hours} h`,
          sub: `About ${Math.round(hours / 8)} working days`,
          tone: "hero",
        }
      : null,
  ];
  return rows.filter((r): r is KpiRow => r !== null);
}
