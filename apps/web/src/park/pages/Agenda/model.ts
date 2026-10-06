// The Agenda's view-model, ported from renderVals in design_handoff_tilo_web_app/design/Tilo App Agenda.dc.html
// (user's prototype, ADR-0003a): pure functions from the typed Agenda fixture, `dec` and the page's own
// UI state. No clock, no random: a new pin's id comes from a counter the page keeps.
import type {
  Agenda,
  AgendaDetail,
  AgendaEvent,
  AgendaPin,
  AgendaSlot,
  Dec,
} from "../../api/types";
import type { AgentSpec } from "../../engines/types";

export type CalKey = AgendaEvent["cal"] | "booked";
export type Ev = Omit<AgendaEvent, "cal"> & { cal: CalKey };
export type BoardKey = AgendaPin["board"];

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
    sub: "Northwind Ops · 5 people and Tilo",
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

export function pinVm(p: AgendaPin, i: number, dec: Dec, doneMap: Record<string, boolean>): PinVm {
  const done = isDone(p, dec, doneMap);
  const tilo = p.by === "tilo";
  const expr = done ? "delighted" : "neutral";
  const avatar = !tilo
    ? null
    : p.role === "director"
      ? { rank: "director", expr }
      : { role: p.role ?? "research", expr };
  const world = p.dec && !dec[p.dec] ? "k1" : p.go && !done ? p.go : null;
  return {
    pin: p,
    done,
    waiting: p.group === "waiting" && !done,
    tilo,
    note: p.dec && dec[p.dec] ? "Approved · £3,420 · K1 electric scooter" : p.note,
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

/** Accepting Tilo's focus-time suggestion turns that pin into a blocked one. */
export const blockFocus = (pins: AgendaPin[], id: string): AgendaPin[] =>
  pins.map((q) => {
    if (q.id !== id) return q;
    const { suggested: _s, ...rest } = q;
    return {
      ...rest,
      title: "Focus time · Mon 28 Sep",
      note: "09:30–11:30, added to your Google Calendar",
      due: "Blocked by Tilo",
      color: "lilac",
      group: "week",
      by: "tilo",
    };
  });

/** Booking the gate review: a new pin on top, the suggestion to book it gone. */
export const bookedPins = (pins: AgendaPin[], s: AgendaSlot): AgendaPin[] => [
  {
    id: "tg",
    board: "team",
    title: "K1 gate review booked",
    note: `${s.l}. Invites sent to Jin, Priya and Tom.`,
    by: "tilo",
    role: "research",
    due: "Tilo booked · just now",
    color: "lilac",
    group: "week",
  },
  ...pins.filter((q) => q.id !== "t0"),
];

export interface Flags {
  [key: string]: boolean | undefined;
}

export function eventsOf(A: Agenda, booked: AgendaSlot | null): Ev[] {
  const base: Ev[] = A.events;
  return booked
    ? [
        ...base,
        {
          id: "gate",
          d: booked.d,
          s: booked.s,
          e: booked.e,
          t: "K1 gate review",
          cal: "booked",
          joins: true,
        },
      ]
    : base;
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
  const e = EV.find((x) => x.id === sel) ?? EV.find((x) => x.id === "sync") ?? EV[0];
  if (!e) throw new Error("the Agenda has no events");
  const det: AgendaDetail = A.details[e.id] ??
    (e.id.startsWith("su") ? A.details.su : undefined) ?? { people: ["AM"] };
  const days = A.days.concat(A.wkend);
  const wasBriefed = !!briefed[e.id];
  const flag = (k: string, def: boolean) => flags[`${e.id}:${k}`] ?? def;
  let brief = det.brief ?? [
    "Tilo will gather the latest emails, docs and notes for this meeting.",
    "You’ll get it 15 minutes before it starts.",
  ];
  if (e.id === "gate" && dec.depot)
    brief = brief.map((x) =>
      x.startsWith("Laptop Depot") ? "Laptop Depot budget was approved today." : x,
    );
  return {
    e,
    det,
    when: `${days[e.d]} Sep · ${fmt(e.s)}–${fmt(e.e)}${e.cal === "booked" ? " · booked by Tilo" : ""}`,
    calLabel: CAL[e.cal][0] + (e.cal === "tilo" || e.cal === "booked" ? "" : " · Google Calendar"),
    hasBrief: !e.past && (!!det.brief || wasBriefed),
    brief,
    briefMeta: det.briefMeta ?? "Queued · arrives 15 min before",
    needsBrief: !e.past && !det.brief && !wasBriefed && !e.tiloOnly,
    past: !!e.past && !!det.notes,
    empty: !!e.past && !det.notes,
    upcoming: !e.past && !e.tiloOnly,
    toggles: [
      [
        "Tilo joins and takes notes",
        "Shares notes with attendees after",
        joinsOf(e, flags),
        "join",
      ],
      [
        "Turn action items into pins",
        "Pinned to the Team board with owners",
        flag("pins", true),
        "pins",
      ],
      [
        "Brief before it starts",
        "15 minutes ahead, in your inbox",
        flag("brief", !!det.brief || wasBriefed),
        "brief",
      ],
    ],
  };
}
