// The Agenda's view-model, ported from renderVals in design_handoff_tilo_web_app/design/Tilo App Agenda.dc.html
// (user's prototype, ADR-0003a): pure functions from the typed Agenda fixture, `dec` and the page's own
// UI state. No clock, no random: a new pin's id comes from a counter the page keeps.
//
// Generic by rule ("No scenario-specific code"): every designed value (a world, a label, a date, a time, an
// amount, a meeting's id) is read from the fixture/Api: `Agenda.rules` and `Decision.facts`.
import type {
  Agenda,
  AgendaDetail,
  AgendaEvent,
  AgendaPin,
  AgendaSlot,
  Dec,
  Decision,
  DecisionKey,
  SuggestionRule,
} from "../../api/types";
import type { AgentSpec } from "../../engines/types";

export type CalKey = AgendaEvent["cal"] | "booked";
export type Ev = Omit<AgendaEvent, "cal"> & { cal: CalKey };
export type BoardKey = AgendaPin["board"];
/** The decisions by key, as the Api serves them (`world` and `facts` are read from here). */
export type DecisionIndex = Partial<Record<DecisionKey, Decision>>;

export const indexDecisions = (list: readonly Decision[]): DecisionIndex =>
  Object.fromEntries(list.map((d) => [d.k, d]));

/** The line under a board's title: the Agenda's own, else the page's generic one. */
export const boardSub = (A: Agenda, b: { key: BoardKey; sub: string }): string =>
  A.rules?.boardSubs?.[b.key] ?? b.sub;

/** A suggestion whose kind has no rule: it is accepted as it stands. */
export const DEFAULT_RULE: SuggestionRule = {
  label: "Accept",
  action: "accept",
  toast: "Accepted",
};
/** What accepting this suggested pin does, by its `kind`. */
export const ruleOf = (A: Agenda, p: AgendaPin): SuggestionRule =>
  (p.kind ? A.rules?.suggestions[p.kind] : undefined) ?? DEFAULT_RULE;
/** The rule that opens the time finder, if the Agenda has one. */
export const findRuleOf = (A: Agenda): SuggestionRule | undefined =>
  Object.values(A.rules?.suggestions ?? {}).find((r) => r.action === "find" && r.find);
/** The meeting the page opens with: the first one that has a brief. */
export const defaultEventId = (A: Agenda): string =>
  (A.events.find((e) => e.brief) ?? A.events[0])?.id ?? "";

export const PX = 52;
export const PAPER: Record<string, string> = {
  yellow: "#FFF1A8",
  pink: "#FCD9E6",
  blue: "#D7E7FC",
  green: "#DDF1D2",
  lilac: "#E6DEFC",
  amber: "#FFDD85",
  white: "#FFFFFF",
};
export const ACCENT: Record<string, string> = {
  yellow: "#E5C33A",
  pink: "#D9588C",
  blue: "#3F7FE0",
  green: "#76A035",
  lilac: "#8A74F0",
  amber: "#F0A500",
  white: "#5A3FE0",
};
export const PERSON: Record<string, string> = {
  AM: "#E6E1F8",
  PS: "#D9F0EE",
  JP: "#FBE4EE",
  TR: "#FDEBDD",
  SO: "#E2ECFB",
  NL: "#EDEBE4",
};
const ROTS = ["-2deg", "1.5deg", "-1deg", "2.2deg", "-1.6deg", "1deg", "-2.4deg", "1.8deg"];
/** [label, bar, background, text] of each calendar. */
export const CAL: Record<CalKey, [string, string, string, string]> = {
  work: ["Work", "var(--hero)", "var(--heroSoft)", "var(--ink)"],
  personal: ["Personal", "var(--ok)", "var(--okSoft)", "var(--ink)"],
  tilo: ["Tilo", "var(--sch)", "var(--schSoft)", "var(--ink)"],
  booked: ["Booked by Tilo", "var(--heroInk)", "var(--hero)", "#FFFFFF"],
};
export const BOARDS: {
  key: BoardKey;
  title: string;
  sub: string;
  iconBg: string;
  agent: AgentSpec;
}[] = [
  {
    key: "team",
    title: "Team board",
    sub: "Everyone on the team and Tilo",
    iconBg: "var(--heroSoft)",
    agent: { rank: "director", expr: "neutral" },
  },
  {
    key: "me",
    title: "My board",
    sub: "Only you and Tilo can see this",
    iconBg: "var(--schSoft)",
    agent: { role: "research", expr: "delighted" },
  },
];

export const fmt = (t: number): string => {
  const hh = Math.floor(t);
  const mm = Math.round((t - hh) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
};

export const isDone = (p: AgendaPin, dec: Dec, done: Record<string, boolean>): boolean =>
  p.dec ? !!dec[p.dec] : (done[p.id] ?? !!p.done);

export interface PinVm {
  pin: AgendaPin;
  done: boolean;
  waiting: boolean;
  tilo: boolean;
  note: string;
  due: string;
  paper: string;
  rot: string;
  accent: string;
  avatar: AgentSpec | null;
  /** The act button: the world to open, or none. */
  act: { label: string; world: string } | null;
  checkLabel: string;
}

export function pinVm(
  p: AgendaPin,
  i: number,
  dec: Dec,
  doneMap: Record<string, boolean>,
  decisions: DecisionIndex = {},
): PinVm {
  const done = isDone(p, dec, doneMap);
  const tilo = p.by === "tilo";
  const expr = done ? "delighted" : "neutral";
  const avatar = !tilo
    ? null
    : p.role === "director"
      ? { rank: "director", expr }
      : { role: p.role ?? "research", expr };
  const decision = p.dec ? decisions[p.dec] : undefined;
  const world = p.dec && !dec[p.dec] ? (decision?.world ?? null) : p.go && !done ? p.go : null;
  return {
    pin: p,
    done,
    waiting: p.group === "waiting" && !done,
    tilo,
    note: p.dec && dec[p.dec] ? (decision?.facts?.approvedNote ?? p.note) : p.note,
    due: done ? "Done" : (p.due ?? ""),
    paper: PAPER[p.color] ?? "#FFF1A8",
    rot: ROTS[i % ROTS.length] ?? "0deg",
    accent: ACCENT[p.color] ?? "#E5C33A",
    avatar,
    act: world ? { label: p.dec ? "Review and approve" : "Open", world } : null,
    checkLabel: done ? "Mark as not done" : "Mark as done",
  };
}

export const GROUPS: [string, (v: PinVm) => boolean][] = [
  ["TILO SUGGESTS", (v) => !!v.pin.suggested],
  ["NEEDS SOMEONE", (v) => !v.pin.suggested && !v.done && v.pin.group === "waiting"],
  ["THIS WEEK", (v) => !v.pin.suggested && !v.done && v.pin.group === "week"],
  ["DONE", (v) => !v.pin.suggested && v.done],
];

/** How many pins each board draws while `drawn` pins have been drawn in all (FR-UX-12: the boards are drawn one
 * after the other, top to bottom, a few pins per task). `null` is a board not started yet: it only holds its cell
 * in the grid, so nothing already drawn moves. A board starts when the ones before it are complete. */
export function boardLimits(counts: readonly number[], drawn: number): (number | null)[] {
  let before = 0;
  return counts.map((n) => {
    const left = drawn - before;
    before += n;
    return left < 0 ? null : Math.min(n, left);
  });
}

/** A new pin lands after the board's suggestions, before everything else. */
export function addPin(pins: AgendaPin[], board: BoardKey, title: string, id: string): AgendaPin[] {
  const fresh: AgendaPin = {
    id,
    board,
    title,
    note: "Added just now",
    by: "AM",
    due: "Alex · just now",
    color: board === "team" ? "yellow" : "blue",
    group: "week",
  };
  const mine = (q: AgendaPin) => q.board === board && q.suggested;
  return [...pins.filter(mine), fresh, ...pins.filter((q) => !mine(q))];
}

/** Accepting a suggestion: the pin drops its flag and takes on what the rule's `accepted` says. */
export const acceptPin = (pins: AgendaPin[], id: string, rule: SuggestionRule): AgendaPin[] =>
  pins.map((q) => {
    if (q.id !== id) return q;
    const { suggested: _s, ...rest } = q;
    return { ...rest, ...rule.accepted };
  });

/** Booking a slot: a new pin on top, the suggestions to find a time gone. */
export function bookedPins(pins: AgendaPin[], s: AgendaSlot, A: Agenda): AgendaPin[] {
  const f = findRuleOf(A)?.find;
  if (!f) return pins;
  const finders = pins.filter((q) => q.suggested && ruleOf(A, q).action === "find");
  const { noteAfter, ...pin } = f.pin;
  return [
    {
      ...pin,
      board: finders[0]?.board ?? "team",
      note: `${s.l}. ${noteAfter}`,
      by: "tilo",
      group: "week",
    },
    ...pins.filter((q) => !finders.includes(q)),
  ];
}

export interface Flags {
  [key: string]: boolean | undefined;
}

export function eventsOf(A: Agenda, booked: AgendaSlot | null): Ev[] {
  const base: Ev[] = A.events;
  const f = findRuleOf(A)?.find;
  return booked && f
    ? [
        ...base,
        {
          id: f.event.id,
          d: booked.d,
          s: booked.s,
          e: booked.e,
          t: f.event.title,
          cal: "booked",
          joins: true,
        },
      ]
    : base;
}

/** "21–25" from the day labels ("Mon 21" ... "Fri 25"), with the weekend when shown. */
export function weekRange(A: Agenda, weekend: boolean): string {
  const nums = A.days.concat(weekend ? A.wkend : []).map((l) => l.split(" ")[1] ?? "");
  return `${nums[0] ?? ""}–${nums[nums.length - 1] ?? ""}`;
}
export const joinsOf = (e: Ev, flags: Flags): boolean => flags[`${e.id}:join`] ?? !!e.joins;

export interface DayVm {
  name: string;
  num: string;
  today: boolean;
  weekend: boolean;
  load: string;
  events: Ev[];
  slots: AgendaSlot[];
}

export function dayColumns(
  A: Agenda,
  EV: Ev[],
  cals: Record<string, boolean>,
  weekend: boolean,
  finding: boolean,
): DayVm[] {
  return A.days
    .concat(A.wkend)
    .slice(0, weekend ? 7 : 5)
    .map((label, d) => {
      const [name = "", num = ""] = label.split(" ");
      const meet = EV.filter((e) => e.d === d && !e.tiloOnly && e.cal !== "tilo");
      const hrs = meet.reduce((a, e) => a + (e.e - e.s), 0);
      return {
        name: name.toUpperCase(),
        num,
        today: d === A.today,
        weekend: d > 4,
        load: meet.length
          ? `${meet.length}${meet.length === 1 ? " event · " : " events · "}${Math.round(hrs * 10) / 10} h`
          : "Free",
        events: EV.filter((e) => e.d === d && (e.cal === "booked" || cals[e.cal])),
        slots: finding ? A.slots.filter((s) => s.d === d) : [],
      };
    });
}

export interface DetailVm {
  e: Ev;
  det: AgendaDetail;
  when: string;
  calLabel: string;
  hasBrief: boolean;
  brief: string[];
  briefMeta: string;
  needsBrief: boolean;
  past: boolean;
  empty: boolean;
  upcoming: boolean;
  toggles: [string, string, boolean, "join" | "pins" | "brief"][];
}

export function detailOf(
  A: Agenda,
  EV: Ev[],
  sel: string,
  flags: Flags,
  briefed: Record<string, boolean>,
  dec: Dec,
): DetailVm {
  const e = EV.find((x) => x.id === sel) ?? EV.find((x) => x.brief) ?? EV[0];
  if (!e) throw new Error("the Agenda has no events");
  // A series ("su1", "su2" ...) shares the detail keyed by its stem ("su").
  const stem = Object.keys(A.details).find(
    (k) => e.id.startsWith(k) && /^\d+$/.test(e.id.slice(k.length)),
  );
  const det: AgendaDetail = A.details[e.id] ??
    (stem ? A.details[stem] : undefined) ?? {
      people: ["AM"],
    };
  const days = A.days.concat(A.wkend);
  const wasBriefed = !!briefed[e.id];
  const flag = (k: string, def: boolean) => flags[`${e.id}:${k}`] ?? def;
  // The brief switch decides whether a brief is claimed: off, there is none to show and none is queued.
  const briefOn = flag("brief", !!det.brief || wasBriefed);
  const joins = joinsOf(e, flags);
  let brief = det.brief ?? [
    "Tilo will gather the latest emails, docs and notes for this meeting.",
    "You’ll get it 15 minutes before it starts.",
  ];
  for (const r of A.rules?.briefRewrites ?? [])
    if (r.event === e.id && dec[r.dec])
      brief = brief.map((x) => (x.startsWith(r.startsWith) ? r.text : x));
  const month = A.rules?.month.slice(0, 3);
  return {
    e,
    det,
    when: `${days[e.d]}${month ? ` ${month}` : ""} · ${fmt(e.s)}–${fmt(e.e)}${e.cal === "booked" ? " · booked by Tilo" : ""}`,
    calLabel: CAL[e.cal][0] + (e.cal === "tilo" || e.cal === "booked" ? "" : " · Google Calendar"),
    hasBrief: !e.past && briefOn,
    brief,
    briefMeta: det.briefMeta ?? "Queued · arrives 15 min before",
    needsBrief: !e.past && !briefOn && !e.tiloOnly,
    past: !!e.past && !!det.notes,
    empty: !!e.past && !det.notes,
    upcoming: !e.past && !e.tiloOnly,
    toggles: [
      // Notes need Tilo in the meeting, and action items need notes: a switch that is off claims neither.
      [
        "Tilo joins and takes notes",
        joins ? "Shares notes with attendees after" : "Tilo stays out, so no notes are taken",
        joins,
        "join",
      ],
      [
        "Turn action items into pins",
        joins ? "Pinned to the Team board with owners" : "No notes, so nothing to pin",
        flag("pins", true),
        "pins",
      ],
      ["Brief before it starts", "15 minutes ahead, in your inbox", briefOn, "brief"],
    ],
  };
}
