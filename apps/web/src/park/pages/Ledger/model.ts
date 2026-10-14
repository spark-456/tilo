import type {
  Dec,
  Decision,
  DecisionFacts,
  DecisionKey,
  Ledger,
  LedgerEntry,
  LedgerPeriod,
} from "../../api/types";
import {
  decisionOf,
  gbp,
  money,
  sign,
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
  sign,
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

/** The month the ledger shows: the sample company's follows today (`period`); without one it is the fixture's September. */
const SEPTEMBER: LedgerPeriod = {
  month: "September",
  short: "Sep",
  year: 2026,
  days: 30,
  firstWeekday: 2,
  today: "Thu 24 Sep",
  day: 24,
};
export const periodOf = (L: Ledger): LedgerPeriod => L.period ?? SEPTEMBER;

/** The lede's "<month> · <n> days left": only when the Ledger holds daily spend for the month so far. */
export const monthLeft = (L: Ledger): string | null => {
  const p = periodOf(L);
  return L.daily.length > 0 ? `${p.month} ${p.year} · ${p.days - L.daily.length} days left` : null;
};

/** The spend-over-time chart is drawn only when there is a budget to scale it by and a day to plot. */
export const hasChart = (L: Ledger): boolean => L.budget > 0 && L.daily.length > 0;

// ---- Spend over time (SVG 720x270) ----
const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;
const dayX = (d: number, days = 30): number => 48 + (d - 1) * (652 / (days - 1));
const pct = (v: number, of: number): string => `${((v / of) * 100).toFixed(2)}%`;

/** The hovered day (1..) for a pointer at `fx` (0..1 across the chart box). The chart clamps it to 1..24. */
export const dayFromX = (fx: number, days = 30): number =>
  Math.round((fx * 720 - 48) / (652 / (days - 1))) + 1;

export function chartGeometry(L: Ledger, dec: Dec, hover: number | null) {
  const waiting = waitingAmount(L);
  const taken = waitingTaken(L, dec);
  const per = periodOf(L);
  const X = (d: number): number => dayX(d, per.days);
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
    ? [now, [X(per.days), Y(L.forecast)]]
    : [
        now,
        [X(Math.round((25 * per.days) / 30)), Y(L.spent + waiting + 70)],
        [X(per.days), Y(L.forecast)],
      ];
  // "Today" is the last day the ledger holds spend for; the pointer is clamped to the days it holds.
  const today = Math.max(1, daily.length);
  const hd = hover != null ? Math.min(today, Math.max(1, hover)) : null;
  const spike = L.spike;
  const spikeShown =
    spike !== undefined &&
    spike.day >= 1 &&
    spike.day <= daily.length &&
    spike.amount <= (L.daily[spike.day - 1] ?? 0);
  const s = sign(L);
  const hx = hd != null ? X(hd) : 0;
  const hv = hd != null ? (cum[hd - 1] ?? 0) : 0;
  return {
    grid: [0, 2000, 4000, 6000].map((v) => `M48 ${Y(v).toFixed(1)} H700`).join(" "),
    line: P(pts),
    area: `${P(pts)} L${now[0].toFixed(1)} 236 L48 236 Z`,
    fc: P(fcPts),
    pace: `M${X(1).toFixed(1)} ${Y(0).toFixed(1)} L${X(per.days).toFixed(1)} ${Y(L.budget).toFixed(1)}`,
    cap: `M48 ${Y(L.budget).toFixed(1)} H700`,
    today: `M${now[0].toFixed(1)} 24 V236`,
    nowX: now[0].toFixed(1),
    nowY: now[1].toFixed(1),
    endX: X(per.days).toFixed(1),
    endY: Y(L.forecast).toFixed(1),
    yLabels: (
      [
        [0, "0"],
        [2000, "2k"],
        [4000, "4k"],
        [6000, "6k"],
      ] as const
    ).map(([v, t]) => ({ t: `${s}${t}`, top: pct(Y(v), 270) })),
    xLabels: (
      [
        [1, `1 ${per.short}`],
        [8, "8"],
        [15, "15"],
        [today, "Today"],
        [per.days, `${per.days} ${per.short}`],
      ] as const
    )
      // an early-month "Today" would sit on top of the "8": a day label within two days of it is left out
      .filter(([d, t]) => t === "Today" || Math.abs(d - today) >= 3)
      .map(([d, t]) => ({ t, left: pct(X(d), 720) })),
    capTop: pct(Y(L.budget), 270),
    spike:
      spike && spikeShown
        ? {
            left: pct(X(spike.day) - 4, 720),
            top: pct(Y(cum[spike.day - 1] ?? 0), 270),
            text: `${spike.label} ${money(L, spike.amount)}`,
          }
        : null,
    fcLeft: pct(X((27.4 * per.days) / 30), 720),
    // The note sits a fixed distance (350 on the budget scale) below the end of the forecast.
    fcTop: pct(Y(L.forecast) + (350 / L.budget) * 206, 270),
    fcLabel:
      taken || waiting === 0
        ? `Forecast ${money(L, L.forecast)}`
        : `If you approve ${money(L, waiting)}`,
    hOp: hd != null ? "1" : "0",
    hx: hd != null ? hx.toFixed(1) : "0",
    hy: hd != null ? Y(hv).toFixed(1) : "0",
    hLine: hd != null ? `M${hx.toFixed(1)} 24 V236` : "M0 0",
    tipLeft: hd != null ? pct(hx, 720) : "0%",
    tipA:
      hd != null
        ? `${DAY_NAMES[(per.firstWeekday + hd - 1) % 7]} ${hd} ${per.short} · ${money(L, daily[hd - 1] ?? 0)}`
        : "",
    tipB: hd != null ? `Running total ${money(L, hv)}` : "",
  };
}

/** The chart's headline: the forecast against the budget, as the ledger holds them. */
export const chartHeadline = (L: Ledger): string =>
  L.forecast > L.budget
    ? `Forecast to finish ${money(L, L.forecast - L.budget)} over budget`
    : `On track to finish ${money(L, L.budget - L.forecast)} under budget`;

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
    // The ring's total is what its own legend adds up to: one figure for every view of a consistent ledger.
    total: money(L, tot),
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
    // Percent cheaper than the first run; negative when the cost rose.
    const dropPct = first > 0 ? Math.round((1 - last / first) * 100) : 0;
    return {
      name,
      n: String(n),
      skill,
      line,
      area: `${line} L200 60 L0 60 Z`,
      first: `${sign(L)}${first.toFixed(2)}`,
      now: `${sign(L)}${last.toFixed(2)}`,
      dropPct,
      drop: dropPct >= 0 ? `−${dropPct}%` : `+${-dropPct}%`,
    };
  });
}

/** The cost-per-run headline: the biggest drop since the first run the ledger holds, or a plain title when none fell. */
export function runsHeadline(L: Ledger): string {
  let best: ReturnType<typeof runCards>[number] | undefined;
  for (const c of runCards(L)) if (!best || c.dropPct > best.dropPct) best = c;
  return best && best.dropPct > 0
    ? `Repeat work gets cheaper. ${L.runLabels?.[best.skill] ?? best.name} now costs ${best.dropPct}% less.`
    : "Cost per run, by skill.";
}

/** The approval-waits headline: the one the ledger states; otherwise a plain title. */
export const waitsHeadline = (L: Ledger): string => L.waits.summary ?? "How long approvals wait";

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

/** A type's wait: the ledger's own; with a backup approver, the wait the ledger holds for that case (else unchanged). */
export function waitTypes(L: Ledger, backup: unknown) {
  return L.waits.types.map(([name, v, tone]) => {
    const withBackup = backup ? L.waits.withBackup?.[name] : undefined;
    return {
      name,
      v: withBackup ?? v,
      c:
        tone === "ok"
          ? "var(--okInk)"
          : tone === "amber" && withBackup === undefined
            ? "var(--amberInk)"
            : "var(--ink)",
    };
  });
}

/** The weekly bars scale to the largest week the ledger holds; the latest week is highlighted. */
export const memoryBars = (L: Ledger) => {
  const top = Math.max(1, ...L.memory);
  return L.memory.map((v, i) => ({
    v: money(L, v),
    h: `${(v / top) * 120}px`,
    c: i === L.memory.length - 1 ? "var(--sch)" : "var(--schSoft)",
  }));
};

/** Week names, only when the ledger names exactly one per bar. */
export const memoryWeeks = (L: Ledger): string[] =>
  L.memoryWeeks?.length === L.memory.length ? L.memoryWeeks : [];

export const hourBars = (L: Ledger) => {
  const total = Math.max(1, sum(L.hours.map((h) => h[1])));
  return L.hours.map(([name, h, c, what]) => ({
    name,
    h: `${h} h`,
    w: `${(h / total) * 100}%`,
    c,
    what,
  }));
};

/**
 * How the two "gave back" figures are counted: the one-sentence methods of PRD 14.3 (credits saved) and 14.2
 * (time saved). Both are shown as estimates and link to their method (FR-SPD-06).
 */
export const METHODS = {
  memory:
    "When Tilo reuses a result, we credit what that result actually cost the first time, minus the cost of the lookup.",
  hours:
    "We count the units of work the agents finished, multiply by the minutes a person took for the same unit in our timing study, and subtract the minutes you spent steering and reviewing.",
} as const;

// ---- Activity ----
/** Kind -> [icon, tile, ink, tag, filter group]. */
const KM: Record<string, readonly [string, string, string, string, string]> = {
  request: ["help", "var(--chip)", "var(--ink2)", "Approval requested", "approval"],
  answer: ["check", "var(--chip)", "var(--ink2)", "Approval answered", "approval"],
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
  const TODAY = `Today · ${periodOf(L).today}`;
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
