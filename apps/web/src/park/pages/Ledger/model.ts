import type {
  Dec,
  Decision,
  DecisionFacts,
  DecisionKey,
  Ledger,
  LedgerEntry,
} from "../../api/types";
import {
  decisionOf,
  gbp,
  money,
  sum,
  waitingAmount,
  waitingKey,
  waitingTaken,
} from "../../app/ledgerKpis";
// The Ledger page's arithmetic: a typed port of the renderVals() of
// design_handoff_tilo_web_app/design/Tilo App Ledger.dc.html (user's prototype, ADR-0003a). Pure functions
// of the Ledger fixture and `dec`, so a test can pin every number. No clock, no random, no network.
export {
  CURRENCY_SYMBOL,
  STEP_LEDGER_PRICES,
  currencySymbol,
  gbp,
  kpis,
  money,
  runMoney,
  waitingAmount,
} from "../../app/ledgerKpis";
export type { CurrencyCode, KpiRow } from "../../app/ledgerKpis";

/** The amount a taken decision's row shows: the money its facts name, or a dash when it names none. */
const amountOf = (f: DecisionFacts): string => (f.amount === undefined ? "—" : gbp(f.amount));

/**
 * The button that takes a waiting decision: the label its facts give, else "Approve" with the amount
 * (the facts' own, or the one the ledger's transaction for that decision is waiting on).
 */
const approveLabelOf = (
  L: Ledger,
  key: DecisionKey | undefined,
  facts: DecisionFacts | undefined,
): string => {
  if (facts?.approveLabel) return facts.approveLabel;
  const amt = facts?.amount ?? L.tx.find((t) => t.dec === key)?.amt;
  return amt === undefined ? "Approve" : `Approve ${gbp(amt)}`;
};

/** The lede's "<month> · <n> days left": only when the Ledger holds daily spend for the month so far. */
export const monthLeft = (L: Ledger): string | null =>
  L.daily.length > 0 ? `September 2026 · ${30 - L.daily.length} days left` : null;

/** The spend-over-time chart is drawn only when there is a budget to scale it by and a day to plot. */
export const hasChart = (L: Ledger): boolean => L.budget > 0 && L.daily.length > 0;

// ---- Spend over time (SVG 720x270) ----
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const X = (d: number): number => 48 + (d - 1) * (652 / 29);
const pct = (v: number, of: number): string => `${((v / of) * 100).toFixed(2)}%`;

/** The hovered day (1..) for a pointer at `fx` (0..1 across the chart box). The chart clamps it to 1..24. */
export const dayFromX = (fx: number): number => Math.round((fx * 720 - 48) / (652 / 29)) + 1;

export function chartGeometry(L: Ledger, dec: Dec, hover: number | null) {
  const waiting = waitingAmount(L);
  const taken = waitingTaken(L, dec);
  const Y = (v: number): number => 236 - (v / L.budget) * 206;
  const daily = L.daily.slice();
  if (taken && daily.length) daily[daily.length - 1] = (daily[daily.length - 1] ?? 0) + waiting;
  const cum: number[] = [];
  daily.reduce((a, v, i) => {
    cum[i] = a + v;
    return cum[i] ?? 0;
  }, 0);
  const pts: [number, number][] = cum.map((v, i) => [X(i + 1), Y(v)]);
  const P = (a: [number, number][]): string =>
    a.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const now = pts[pts.length - 1] ?? [48, 236];
  const fcPts: [number, number][] = taken
    ? [now, [X(30), Y(L.forecast)]]
    : [now, [X(25), Y(L.spent + waiting + 70)], [X(30), Y(L.forecast)]];
  const hd = hover != null ? Math.min(24, Math.max(1, hover)) : null;
  const hx = hd != null ? X(hd) : 0;
  const hv = hd != null ? (cum[hd - 1] ?? 0) : 0;
  return {
    grid: [0, 2000, 4000, 6000].map((v) => `M48 ${Y(v).toFixed(1)} H700`).join(" "),
    line: P(pts),
    area: `${P(pts)} L${now[0].toFixed(1)} 236 L48 236 Z`,
    fc: P(fcPts),
    pace: `M${X(1).toFixed(1)} ${Y(0).toFixed(1)} L${X(30).toFixed(1)} ${Y(L.budget).toFixed(1)}`,
    cap: `M48 ${Y(L.budget).toFixed(1)} H700`,
    today: `M${now[0].toFixed(1)} 24 V236`,
    nowX: now[0].toFixed(1),
    nowY: now[1].toFixed(1),
    endX: X(30).toFixed(1),
    endY: Y(L.forecast).toFixed(1),
    yLabels: (
      [
        [0, "£0"],
        [2000, "£2k"],
        [4000, "£4k"],
        [6000, "£6k"],
      ] as const
    ).map(([v, t]) => ({ t, top: pct(Y(v), 270) })),
    xLabels: (
      [
        [1, "1 Sep"],
        [8, "8"],
        [15, "15"],
        [24, "Today"],
        [30, "30 Sep"],
      ] as const
    ).map(([d, t]) => ({ t, left: pct(X(d), 720) })),
    capTop: pct(Y(L.budget), 270),
    spikeLeft: pct(X(21) - 4, 720),
    spikeTop: pct(Y(cum[20] ?? 0), 270),
    fcLeft: pct(X(27.4), 720),
    fcTop: pct(Y(5950), 270),
    fcLabel: taken ? `Forecast ${gbp(L.forecast)}` : `If you approve ${gbp(waiting)}`,
    hOp: hd != null ? "1" : "0",
    hx: hd != null ? hx.toFixed(1) : "0",
    hy: hd != null ? Y(hv).toFixed(1) : "0",
    hLine: hd != null ? `M${hx.toFixed(1)} 24 V236` : "M0 0",
    tipLeft: hd != null ? pct(hx, 720) : "0%",
    tipA: hd != null ? `${DAY_NAMES[(hd + 1) % 7]} ${hd} Sep · ${gbp(daily[hd - 1] ?? 0)}` : "",
    tipB: hd != null ? `Running total ${gbp(hv)}` : "",
  };
}

// ---- Where it goes ----
const PALETTE = ["#5A3FE0", "#0E7C79", "#F0A500", "#D9588C", "#3F7FE0", "#8C8899"] as const;
export type By = keyof Ledger["by"];

export function donut(L: Ledger, by: By) {
  const B = L.by[by];
  const tot = sum(B.rows.map((r) => r[1]));
  const share = (v: number): number => (tot > 0 ? (v / tot) * 100 : 0);
  let acc = 0;
  const stops = B.rows.map((r, i) => {
    const a = share(acc);
    acc += r[1];
    const b = share(acc);
    return `${PALETTE[i]} ${a.toFixed(2)}% ${(b - 0.5).toFixed(2)}%, transparent ${(b - 0.5).toFixed(2)}% ${b.toFixed(2)}%`;
  });
  return {
    head: B.head,
    // No spend to divide is an empty ring, not a gradient with NaN stops.
    conic:
      tot > 0 ? `conic-gradient(${stops.join(", ")})` : "conic-gradient(transparent, transparent)",
    rows: B.rows.map((r, i) => ({
      name: r[0],
      amt: money(L, r[1]),
      pct: `${Math.round(share(r[1]))}%`,
      c: PALETTE[i] ?? "#8C8899",
    })),
  };
}

/** The groupings that have rows; the Where-it-goes card shows only these. */
export const groupsWithRows = (L: Ledger): By[] =>
  (["world", "tool", "role"] as const).filter((k) => L.by[k].rows.length > 0);

// ---- Cost per run, approval waits, what Tilo gave back ----
export function runCards(L: Ledger) {
  return L.runs.map(([name, v, n, skill]) => {
    const mx = v[0] || 1;
    const line = v
      .map(
        (c, i) =>
          `${i ? "L" : "M"}${((i / Math.max(1, v.length - 1)) * 200).toFixed(1)} ${(6 + (1 - c / mx) * 50).toFixed(1)}`,
      )
      .join(" ");
    const first = v[0] ?? 0;
    const last = v[v.length - 1] ?? 0;
    return {
      name,
      n: String(n),
      skill,
      line,
      area: `${line} L200 60 L0 60 Z`,
      first: `£${first.toFixed(2)}`,
      now: `£${last.toFixed(2)}`,
      drop: `−${first > 0 ? Math.round((1 - last / first) * 100) : 0}%`,
    };
  });
}

/** The approval-waits card is shown only when the Ledger holds waits to show. */
export const hasWaits = (L: Ledger): boolean =>
  L.waits.buckets.length > 0 || L.waits.types.length > 0;

export function waitBuckets(L: Ledger) {
  const bmax = Math.max(1, ...L.waits.buckets.map((b) => b[1]));
  return L.waits.buckets.map(([label, n], i) => ({
    label,
    n: String(n),
    w: `${(n / bmax) * 100}%`,
    c: i < 2 ? "var(--ok)" : i < 3 ? "var(--sch)" : "#F0A500",
  }));
}

export function waitTypes(L: Ledger, backup: unknown) {
  return L.waits.types.map(([name, v, tone]) => ({
    name,
    v: name.startsWith("Sharing") && backup ? "About 20 min with a backup" : v,
    c:
      tone === "ok"
        ? "var(--okInk)"
        : tone === "amber" && !backup
          ? "var(--amberInk)"
          : "var(--ink)",
  }));
}

export const memoryBars = (L: Ledger) =>
  L.memory.map((v, i) => ({
    v: `£${v}`,
    h: `${(v / 200) * 120}px`,
    c: i === 3 ? "var(--sch)" : "var(--schSoft)",
  }));

export const hourBars = (L: Ledger) =>
  L.hours.map(([name, h, c, what]) => ({ name, h: `${h} h`, w: `${(h / 46) * 100}%`, c, what }));

// ---- Activity ----
/** Kind -> [icon, tile, ink, tag, filter group]. */
const KM: Record<string, readonly [string, string, string, string, string]> = {
  spend: ["coin", "var(--heroSoft)", "var(--heroInk)", "Spend", "spend"],
  approval: ["check", "var(--okSoft)", "var(--ok)", "Approved", "approval"],
  declined: ["lock", "var(--redSoft)", "var(--redInk)", "Declined", "approval"],
  gate: ["flag", "var(--chip)", "var(--ink2)", "Gate passed", "gate"],
  waiting: ["help", "var(--amberTile)", "var(--amberInk)", "Waiting on you", "waiting"],
  waitshare: ["help", "var(--amberTile)", "var(--amberInk)", "Waiting on you", "waiting"],
  share: ["up", "var(--blueSoft)", "var(--blueInk)", "Shared outside", "share"],
  saved: ["vault", "var(--schSoft)", "var(--sch)", "Memory saving", "saved"],
};
const FALLBACK = KM.spend as readonly [string, string, string, string, string];

export const KINDS = [
  ["all", "All"],
  ["waiting", "Waiting"],
  ["spend", "Spend"],
  ["approval", "Approvals"],
  ["gate", "Gates"],
  ["share", "Shared"],
  ["saved", "Savings"],
] as const;
export type Kind = (typeof KINDS)[number][0];

const TODAY = "Today · Thu 24 Sep";

export interface ActivityRow {
  /** Index in the whole feed (the open row is tracked by it, as in the reference). */
  index: number;
  time: string;
  what: string;
  sub: string;
  amt: string;
  tag: string;
  icon: string;
  tile: string;
  ink: string;
  amtColor: string;
  tagColor: string;
  waiting: boolean;
  world: string;
  detail: { k: string; v: string }[];
  decKey: LedgerEntry["dec"];
  approveLabel: string;
}

export function activityGroups(
  L: Ledger,
  dec: Dec,
  kind: Kind,
  decisions: readonly Decision[] = [],
) {
  let E: LedgerEntry[] = L.activity.filter((e) => !(e.dec && dec[e.dec]));
  // A decision taken is recorded as its own row, worded by the decision's `facts`; a decision the Api
  // does not describe adds no row.
  const mail = decisions.find((d) => d.k === "mail");
  const depot = decisions.find((d) => d.k === "depot");
  if (dec.mail && mail?.facts)
    E = [
      {
        day: TODAY,
        t: "Just now",
        k: "share",
        world: mail.world,
        what: mail.facts.activity,
        sub: `${mail.facts.project} · approved by you`,
        amt: amountOf(mail.facts),
        detail: mail.facts.details ?? [],
      },
      ...E,
    ];
  if (dec.depot && depot?.facts)
    E = [
      {
        day: TODAY,
        t: "Just now",
        k: "approval",
        world: depot.world,
        what: depot.facts.activity,
        sub: `${depot.facts.project} · ${depot.facts.approver}`,
        amt: amountOf(depot.facts),
        detail: depot.facts.details ?? [],
      },
      ...E,
    ];
  const waitN = L.activity.filter((e) => e.dec && !dec[e.dec]).length;
  const groups: { day: string; rows: ActivityRow[] }[] = [];
  E.forEach((e, index) => {
    const m = KM[e.k] ?? FALLBACK;
    if (kind !== "all" && m[4] !== kind) return;
    let g = groups.find((x) => x.day === e.day);
    if (!g) {
      g = { day: e.day, rows: [] };
      groups.push(g);
    }
    const isWaiting = !!e.dec;
    g.rows.push({
      index,
      time: e.t,
      what: e.what,
      sub: e.sub,
      amt: e.amt,
      tag: m[3],
      icon: m[0],
      tile: m[1],
      ink: m[2],
      amtColor:
        e.k === "saved"
          ? "var(--okInk)"
          : isWaiting
            ? "var(--amberInk)"
            : e.k === "spend"
              ? "var(--ink)"
              : "var(--ink2)",
      tagColor: isWaiting
        ? "var(--amberInk)"
        : e.k === "declined"
          ? "var(--redInk)"
          : "var(--ink3)",
      waiting: isWaiting,
      world: e.world,
      detail: e.detail.map(([k, v]) => ({ k, v })),
      decKey: e.dec,
      approveLabel: approveLabelOf(L, e.dec, decisionOf(decisions, e.dec)?.facts),
    });
  });
  return { entries: E, groups, waitN };
}
