// The sample company's dates follow today (DEMO-TIME-1). The fixtures are written for Thursday 24 September 2026; a
// demo opened on another day would say "Thursday 24 September" on Home, which is a wrong sense of time. `dated` moves
// every date in a sample answer by the number of days between the fixture's day and `today`, and rebuilds the
// pieces that are positional (the Agenda's week, the Ledger's month). Pure: the caller hands in today as a calendar
// date (the app reads its clock in app/context.tsx; this layer reads none), so a test passes any day it likes and a
// fixture Api with no clock stays exactly as written. Only results whose `source` is "fixture" are changed.
import type { Api } from "./index";
import type { Agenda, ApiResult, Ledger, Source } from "./types";

export interface CivilDate {
  readonly y: number;
  /** 1 to 12. */
  readonly m: number;
  readonly d: number;
}

/** The day the fixtures are written for. */
export const SAMPLE_DAY: CivilDate = { y: 2026, m: 9, d: 24 };

const WEEKDAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
] as const;
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

/** Days since 1970-01-01 of a calendar date (Howard Hinnant's civil algorithm). */
export function daysFromCivil({ y, m, d }: CivilDate): number {
  const yy = m <= 2 ? y - 1 : y;
  const era = Math.floor(yy / 400);
  const yoe = yy - era * 400;
  const doy = Math.floor((153 * (m + (m > 2 ? -3 : 9)) + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

export function civilFromDays(n: number): CivilDate {
  const z = n + 719468;
  const era = Math.floor(z / 146097);
  const doe = z - era * 146097;
  const yoe = Math.floor(
    (doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365,
  );
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp < 10 ? mp + 3 : mp - 9;
  return { y: yoe + era * 400 + (m <= 2 ? 1 : 0), m, d };
}

/** 0 = Sunday. */
export const weekdayOf = (n: number): number => (((n + 4) % 7) + 7) % 7;
/** 0 = Monday. */
const mondayFirst = (n: number): number => (weekdayOf(n) + 6) % 7;
export const daysInMonth = (y: number, m: number): number =>
  daysFromCivil({ y: m === 12 ? y + 1 : y, m: m === 12 ? 1 : m + 1, d: 1 }) -
  daysFromCivil({ y, m, d: 1 });

const shortOf = (name: string): string => name.slice(0, 3);
const monthIndex = (word: string): number =>
  MONTHS.findIndex((n) => n.startsWith(word.slice(0, 3)));

/** The month `delta` months from (y, m). */
function addMonths(y: number, m: number, delta: number): { y: number; m: number } {
  const t = y * 12 + (m - 1) + delta;
  return { y: Math.floor(t / 12), m: (((t % 12) + 12) % 12) + 1 };
}

const WEEKDAY =
  "(Monday|Mon|Tuesday|Tue|Wednesday|Wed|Thursday|Thu|Friday|Fri|Saturday|Sat|Sunday|Sun)";
const MONTH_WORD =
  "(January|Jan|February|Feb|March|Mar|April|Apr|June|Jun|July|Jul|August|Aug|September|Sep|October|Oct|November|Nov|December|Dec)";
// One pattern, four shapes, tried left to right at each position:
//   "Thursday 24 September", "Thu 24 Sep", "Mon 21" (no month: the fixture's September), never "Thu 16:00"
//   "24 Sep", "1 October"
//   "September 2026"
//   a bare month the sample uses as a label (the month before, this one, the next)
const ANY_DATE = new RegExp(
  [
    `\\b${WEEKDAY}\\s+(\\d{1,2})(?![:\\d])(?:\\s+${MONTH_WORD}\\b)?`,
    `\\b(\\d{1,2})\\s+${MONTH_WORD}\\b(?!\\s+\\d{4})`,
    `\\b${MONTH_WORD}\\s+(\\d{4})\\b`,
    "\\b(August|September|October)\\b",
  ].join("|"),
  "g",
);

interface Shift {
  /** Days from the fixture's day to today. */
  offset: number;
  /** Months from the fixture's month to today's. */
  months: number;
}

function shiftOf(today: CivilDate): Shift {
  return {
    offset: daysFromCivil(today) - daysFromCivil(SAMPLE_DAY),
    months: today.y * 12 + today.m - (SAMPLE_DAY.y * 12 + SAMPLE_DAY.m),
  };
}

const dateLabel = (n: number, long: boolean, withMonth: boolean, withWeekday: boolean): string => {
  const c = civilFromDays(n);
  const wd = WEEKDAYS[weekdayOf(n)] as string;
  const mo = MONTHS[c.m - 1] as string;
  return [
    withWeekday ? (long ? wd : shortOf(wd)) : "",
    String(c.d),
    withMonth ? (long ? mo : shortOf(mo)) : "",
  ]
    .filter(Boolean)
    .join(" ");
};

/** One sample sentence with every date in it moved. One pass: a date that has been moved is never moved again. */
export function shiftText(text: string, today: CivilDate): string {
  const { offset, months } = shiftOf(today);
  if (offset === 0) return text;
  const moved = (month: number, day: number): number =>
    daysFromCivil({ y: SAMPLE_DAY.y, m: month, d: day }) + offset;
  return text.replace(
    ANY_DATE,
    (
      all: string,
      wd?: string,
      wdDay?: string,
      wdMonth?: string,
      day?: string,
      dayMonth?: string,
      yMonth?: string,
      year?: string,
      label?: string,
    ) => {
      if (wd !== undefined && wdDay !== undefined) {
        const m = wdMonth === undefined ? SAMPLE_DAY.m : monthIndex(wdMonth) + 1;
        return dateLabel(moved(m, Number(wdDay)), wd.length > 3, wdMonth !== undefined, true);
      }
      if (day !== undefined && dayMonth !== undefined) {
        return dateLabel(
          moved(monthIndex(dayMonth) + 1, Number(day)),
          dayMonth.length > 3,
          true,
          false,
        );
      }
      if (yMonth !== undefined && year !== undefined) {
        const at = addMonths(Number(year), monthIndex(yMonth) + 1, months);
        const name = MONTHS[at.m - 1] as string;
        return `${yMonth.length > 3 ? name : shortOf(name)} ${at.y}`;
      }
      if (label !== undefined) {
        const at = addMonths(SAMPLE_DAY.y, monthIndex(label) + 1, months);
        return MONTHS[at.m - 1] as string;
      }
      return all;
    },
  );
}

/** The Agenda's week: Monday to Friday and the weekend of today's week, today's column, and what has passed. */
function shiftAgenda(a: Agenda, today: CivilDate): Agenda {
  const base = walk(a, today) as Agenda;
  const n = daysFromCivil(today);
  const monday = n - mondayFirst(n);
  const col = Math.min(mondayFirst(n), 4); // a weekend shows Friday as the day: the sample has no weekend "now"
  const names = (i: number): string => dateLabel(monday + i, false, false, true);
  const dayName = (d: number): string => shortOf(WEEKDAYS[weekdayOf(monday + d)] as string);
  return {
    ...base,
    days: [0, 1, 2, 3, 4].map(names),
    wkend: [5, 6].map(names),
    today: col,
    events: base.events.map((e) => {
      const past = e.d < col || (e.d === col && e.e <= a.now);
      const { past: _was, ...rest } = e;
      return past ? { ...rest, past: true } : rest;
    }),
    slots: base.slots.map((s) => ({ ...s, l: s.l.replace(/^[A-Z][a-z]{2}\b/, dayName(s.d)) })),
  };
}

/** The Ledger's month: its length, its first weekday, a daily series that stops at today's day of the month, and the
 * weeks the memory chart names. */
function shiftLedger(L: Ledger, today: CivilDate): Ledger {
  const base = walk(L, today) as Ledger;
  const days = daysInMonth(today.y, today.m);
  const day = Math.min(today.d, days);
  const mo = MONTHS[today.m - 1] as string;
  const old = L.daily;
  const cum = [0, ...old.map((_v, i) => old.slice(0, i + 1).reduce((s, v) => s + v, 0))];
  const at = (x: number): number => {
    const i = Math.min(old.length - 1, Math.floor(x));
    return (cum[i] ?? 0) + (old[i] ?? 0) * (x - i);
  };
  // Same total, spread over the days that have passed in the month (more or fewer than the fixture's 24).
  const daily =
    old.length === 0 || old.length === day
      ? old
      : Array.from(
          { length: day },
          (_v, i) => at(((i + 1) * old.length) / day) - at((i * old.length) / day),
        );
  const out: Ledger = { ...base, daily };
  if (L.spike) {
    const sd = Math.min(
      day,
      Math.max(1, Math.ceil(((L.spike.day - 0.5) * day) / Math.max(1, old.length))),
    );
    out.spike = { ...L.spike, day: sd, amount: Math.min(L.spike.amount, daily[sd - 1] ?? 0) };
  }
  if (L.memoryWeeks) {
    // The four weeks that end today, oldest first; the month is named where it changes.
    const n = daysFromCivil(today);
    out.memoryWeeks = L.memoryWeeks.map((_w, i, all) => {
      const to = n - 7 * (all.length - 1 - i);
      const a = civilFromDays(to - 6);
      const b = civilFromDays(to);
      const from = a.m === b.m ? String(a.d) : `${a.d} ${shortOf(MONTHS[a.m - 1] as string)}`;
      return `${from}–${b.d} ${shortOf(MONTHS[b.m - 1] as string)}`;
    });
  }
  const first = daysFromCivil({ y: today.y, m: today.m, d: 1 });
  out.period = {
    month: mo,
    short: shortOf(mo),
    year: today.y,
    days,
    firstWeekday: weekdayOf(first),
    today: dateLabel(daysFromCivil(today), false, true, true),
    day,
  };
  return out;
}

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const isAgenda = (v: unknown): v is Agenda =>
  isRecord(v) && Array.isArray(v.days) && Array.isArray(v.events) && typeof v.today === "number";
const isLedger = (v: unknown): v is Ledger =>
  isRecord(v) && Array.isArray(v.daily) && Array.isArray(v.tx) && typeof v.spent === "number";

function walk(value: unknown, today: CivilDate): unknown {
  if (typeof value === "string") return shiftText(value, today);
  if (Array.isArray(value)) return value.map((v) => walk(v, today));
  if (isRecord(value)) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, walk(v, today)]));
  }
  return value;
}

/** A sample answer with its dates moved to `today`; anything that is not a plain data value passes unchanged. */
export function dated<T>(value: T, today: CivilDate): T {
  if (isAgenda(value)) return shiftAgenda(value, today) as T;
  if (isLedger(value)) return shiftLedger(value, today) as T;
  return walk(value, today) as T;
}

const SAMPLE: Source = "fixture";

/** The same Api, its fixture answers dated to `today()`. Live answers (and rejections) pass untouched. */
export function withToday(api: Api, today: () => CivilDate): Api {
  const wrapped = Object.fromEntries(
    Object.entries(api).map(([name, call]) => [
      name,
      (...args: unknown[]) =>
        (call as (...a: unknown[]) => Promise<ApiResult<unknown>>)(...args).then((r) =>
          r.source === SAMPLE ? { ...r, data: dated(r.data, today()) } : r,
        ),
    ]),
  );
  return wrapped as unknown as Api;
}
