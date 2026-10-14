// Home page data rules, written out from the reference (design_handoff_tilo_web_app/design/
// Tilo App Home.dc.html, its renderVals, and tilo-app.js). Pure functions over what the Api returned:
// nothing here reads a fixture, the clock or the address bar.
import type {
  Agenda,
  AgendaEvent,
  Ledger,
  QuickCost,
  SwitchReason,
  TierKey,
  World,
} from "../../api/types";

/** The composer's copy per size of job (the reference reads it from `D.TIERS`; the Api has no tier call). */
export interface Mode {
  readonly key: TierKey;
  readonly label: string;
  readonly tier: string;
  readonly word: string;
  readonly example: string;
  /** The example in few words, for a phone's input, which cannot wrap its placeholder. */
  readonly short: string;
  readonly start: string;
  readonly hint: string;
  readonly chips: readonly string[];
  readonly agents: string;
  readonly cost: string;
  readonly eta: string;
  readonly confirm: string;
  readonly steps: readonly string[];
}

export const MODES: readonly [Mode, Mode, Mode] = [
  {
    key: "quick",
    label: "Quick task",
    tier: "Village",
    word: "village",
    example: "Summarise this week’s customer feedback",
    short: "Summarise this week’s feedback",
    start: "Start task",
    hint: "You see the plan and the cost before any agent starts.",
    chips: ["Compare three suppliers", "Draft a reply to Northline", "Summarise yesterday’s calls"],
    agents: "2",
    cost: "about £0.60",
    eta: "about 6 min",
    confirm: "Start now",
    steps: [
      "Gather what it needs from your connected tools",
      "Do the work with 2 agents",
      "Hand you the result to review",
    ],
  },
  {
    key: "routine",
    label: "Routine",
    tier: "Town",
    word: "town",
    example: "Every Monday, match invoices to purchase orders",
    short: "Match invoices every Monday",
    start: "Set up routine",
    hint: "You approve the first run. After that it runs on its own.",
    chips: ["Weekly invoice match", "Monday pricing check", "Daily inbox triage"],
    agents: "4",
    cost: "about £0.40 a run",
    eta: "first run tomorrow 08:00",
    confirm: "Schedule it",
    steps: [
      "Run once tomorrow at 08:00 for your approval",
      "Then repeat on the schedule you set",
      "Ask you if anything looks unusual",
    ],
  },
  {
    key: "workspace",
    label: "Workspace",
    tier: "City",
    word: "city",
    example: "Onboard 12 new hires across email, HR and laptops",
    short: "Onboard 12 new hires",
    start: "Plan project",
    hint: "Tilo drafts districts, teams and gates for your sign-off.",
    chips: ["Product launch", "Supplier onboarding", "Quarterly audit prep"],
    agents: "18",
    cost: "£400 budget to start",
    eta: "plan in about 2 min",
    confirm: "Draft the city",
    steps: [
      "Draft districts, teams and gates",
      "Estimate budget and timeline",
      "Wait for your sign-off before any spend",
    ],
  },
];

export const DRAFT_MS = 900;

// Quick / Thinking (COST-FAST-1). Words only: no number here is an estimate, a price or a time. The one number is
// the server's own input cap for a Quick question (config/assistant.yaml question.max_chars).
export const QUICK_MAX_CHARS = 500;

export const EFFORTS = [
  {
    key: "quick",
    label: "Quick",
    note: "A direct answer. No plan is made and no agents start.",
    start: "Ask",
  },
  {
    key: "thinking",
    label: "Thinking",
    note: "The Director plans the work first, and nothing starts until you approve it.",
    start: null,
  },
] as const;

/** Why a Quick ask was sent back to Thinking, in plain words (the server's closed set of reasons). */
export const SWITCH_WORDS: Readonly<Record<SwitchReason, string>> = {
  attachments: "It has files, which a Quick answer cannot read.",
  side_effect: "It would send, post, delete or book something, which needs a plan you approve.",
  deliverable: "It asks for a document, deck or sheet to be made.",
  needs_tools: "It needs tools, like searching the web or reading your inbox or calendar.",
  multi_step: "It has several steps, one after another.",
  too_long: "It is longer than a Quick answer can take.",
  scenario: "It is a ready-made scenario, which runs as a full plan.",
  unclear: "Tilo could not tell whether a quick answer would be enough.",
};

const figure = (n: number): string =>
  n === 0 ? "0" : n < 0.01 ? "under 0.01" : String(Number(n.toFixed(2)));
const credits = (n: number): string => `${figure(n)} ${n === 1 ? "credit" : "credits"}`;

/** The cost line of a Quick answer, only from what the server served; null when it served nothing. */
export function quickCostLine(cost: QuickCost | null): string | null {
  if (!cost) return null;
  const parts: string[] = [];
  if (cost.credits !== undefined) parts.push(`Cost ${credits(cost.credits)}`);
  if (cost.savedCredits !== undefined && cost.savedCredits > 0) {
    parts.push(`Saved ${credits(cost.savedCredits)}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

const plural = (n: number, one: string, many: string): string => (n === 1 ? one : many);

/** The greeting panel's summary line (the "38 agents" count is the reference's own text). */
export function summaryLine(needs: number, night: boolean): string {
  if (night) {
    const tail = needs
      ? `${plural(needs, "One thing needs", "Two things need")} you before morning.`
      : "Nothing needs you.";
    return `Your city keeps working overnight. ${tail}`;
  }
  const tail = needs
    ? plural(needs, "One thing needs you.", "Two things need you.")
    : "Nothing needs you right now.";
  return `38 agents are at work across 4 worlds. ${tail}`;
}

/**
 * The summary on the live path (PRD 9.4): only what the served worlds and decisions say. `running` counts the
 * served worlds that run or need a person; `needs` is the served open-decision count, or null when none were
 * served (then nothing is claimed about it). No agent count: the worlds list does not serve one.
 */
export function liveSummaryLine(running: number, needs: number | null): string {
  const parts: string[] = [];
  if (running > 0)
    parts.push(`${running} ${plural(running, "world is", "worlds are")} in progress.`);
  if (needs !== null) {
    if (needs === 0) parts.push("Nothing needs you right now.");
    else if (needs === 1) parts.push("One thing needs you.");
    else parts.push(needs === 2 ? "Two things need you." : `${needs} things need you.`);
  }
  return parts.join(" ");
}

export const decisionsWaiting = (needs: number): string =>
  `${needs} ${plural(needs, "decision waiting", "decisions waiting")}`;

export interface LiveRow {
  readonly world: World;
  readonly needs: boolean;
  readonly sub: string;
  readonly prog: number;
}

/** "Live now": the worlds that need you or run, five at most, in the Api's order. */
export function liveRows(worlds: readonly World[], needs: number, served = false): LiveRow[] {
  return worlds
    .filter((w) => w.st === "needs" || w.st === "running")
    .slice(0, 5)
    .map((w) => {
      const nd = w.st === "needs";
      const sub = nd
        ? needs > 0
          ? decisionsWaiting(needs)
          : "Needs you" // no served count: no number (BQ-UX11-1)
        : w.isNew
          ? "Starting now"
          : w.tier === "Village"
            ? (w.when ?? "")
            : served && w.prog === undefined
              ? "Running"
              : `Running · ${w.prog ?? 0}%`;
      return { world: w, needs: nd, sub, prog: w.prog ?? 0 };
    });
}

export type CalTone = AgendaEvent["cal"];

export interface NextEvent {
  readonly id: string;
  readonly time: string;
  readonly title: string;
  readonly tone: CalTone;
  readonly sub: string;
}

const clock = (t: number): string => {
  const hh = Math.floor(t);
  const mm = Math.round((t - hh) * 60);
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
};

/** "Up next today": the first two of today's events after 09:18, in the Api's own order. */
export function nextEvents(agenda: Agenda): NextEvent[] {
  return agenda.events
    .filter((e) => e.d === agenda.today && e.s > 9.3)
    .slice(0, 2)
    .map((e) => ({
      id: e.id,
      time: clock(e.s),
      title: e.t,
      tone: e.cal,
      sub: e.brief
        ? "Tilo’s brief is ready"
        : e.cal === "tilo"
          ? "Tilo routine"
          : `Google Calendar · ${Math.round((e.e - e.s) * 60)} min`,
    }));
}

/** 2412 -> "£2,412". */
export const money = (n: number): string =>
  `£${Math.round(n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;

export interface Spend {
  /** The month the ledger shows, as the panel's title names it ("September" for a ledger with daily spend and no
   * period); null when the ledger holds no month (the live report is a total, not a month: HR-1). */
  readonly month: string | null;
  readonly spent: string;
  readonly of: string;
  readonly forecast: string;
  readonly spentPct: number;
  readonly waitingPct: number;
}

/** September spend: the ledger's numbers; "waiting on you" is what its transactions still wait for. */
export function spendOf(ledger: Ledger): Spend {
  const waiting = ledger.tx.filter((t) => t.st === "waiting").reduce((sum, t) => sum + t.amt, 0);
  const pct = (n: number): number =>
    ledger.budget > 0 ? Math.round((n / ledger.budget) * 100) : 0;
  return {
    month: ledger.period?.month ?? (ledger.daily.length > 0 ? "September" : null),
    spent: money(ledger.spent),
    of: `of ${money(ledger.budget)}`,
    forecast: `Forecast ${money(ledger.forecast)} · ${money(waiting)} waiting on you`,
    spentPct: Math.min(pct(ledger.spent), 100),
    waitingPct: Math.min(pct(waiting), 100 - Math.min(pct(ledger.spent), 100)),
  };
}

export type PinTone = "needs" | "run" | "sch";
export interface PinDef {
  readonly worldId: string;
  readonly icon: string;
  readonly tone: PinTone;
  readonly sub: string;
}

/** The world a decision waits in: the first world (not one just started) whose state is "needs". */
export function needsWorld(worlds: readonly World[]): World | undefined {
  return worlds.find((w) => w.st === "needs" && !w.isNew);
}

/**
 * The three pins of the reference, by index of `app.pins`, chosen from the worlds the Api returned (not
 * ones just started): pin 0 is the first world that needs you or runs, pin 1 the next running one, pin 2
 * the first scheduled one. A slot with no such world has no pin.
 */
export function pinDefs(
  worlds: readonly World[],
  needs: number,
  night: boolean,
  served = false,
): readonly (PinDef | undefined)[] {
  const old = worlds.filter((w) => !w.isNew);
  const [first, second] = old.filter((w) => w.st === "needs" || w.st === "running");
  const sched = old.find((w) => w.st === "scheduled");
  const nd = first?.st === "needs";
  return [
    first && {
      worldId: first.id,
      icon: nd ? "flag" : "bolt",
      tone: nd ? "needs" : "run",
      sub: nd
        ? needs > 0
          ? `${needs} ${plural(needs, "decision needs you", "decisions need you")}`
          : "Needs you" // no served count: no number (BQ-UX11-1)
        : served && first.prog === undefined
          ? "Running"
          : `Running · ${first.prog ?? 0}%`,
    },
    second && {
      worldId: second.id,
      icon: "people",
      tone: "run",
      sub: `${night ? "Running overnight" : "Running"}${
        served && second.prog === undefined ? "" : ` · ${second.prog ?? 0}%`
      }`,
    },
    sched && {
      worldId: sched.id,
      icon: "clock",
      tone: "sch",
      sub: `${sched.nextL} ${sched.nextV}`,
    },
  ];
}

export interface PlacedPin extends PinDef {
  readonly x: number;
  readonly y: number;
  readonly world: World;
}

/** A pin is dropped where it would sit under one of the page's own panels (the reference's `blocks`). */
export function placedPins(
  pins: readonly { x: number; y: number }[],
  worlds: readonly World[],
  needs: number,
  night: boolean,
  vw: number,
  vh: number,
  served = false,
): PlacedPin[] {
  const side = vw >= 1180;
  const blocks: readonly [number, number, number, number][] = [
    [0, 0, vw, 96],
    [0, 80, 548, 430],
    side ? [vw - 400, 80, vw, vh - 300] : [0, 0, 0, 0],
    [0, vh - 250, vw, vh],
  ];
  const clear = (p: { x: number; y: number }): boolean =>
    !blocks.some((b) => p.x + 140 > b[0] && p.x - 140 < b[2] && p.y > b[1] && p.y - 84 < b[3]);
  const defs = pinDefs(worlds, needs, night, served);
  const out: PlacedPin[] = [];
  pins.forEach((p, i) => {
    const def = defs[i];
    const world = def ? worlds.find((w) => w.id === def.worldId) : undefined;
    if (def && world && clear(p))
      out.push({ ...def, x: Math.round(p.x), y: Math.round(p.y), world });
  });
  return out;
}
