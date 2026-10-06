// Typed shapes of the Park City fixtures (WEB-1a; README "State and data"; plan section 5).
// Each shape follows design_handoff_tilo_web_app/design/tilo-app.js, the user's own prototype data.

export type Source = "fixture" | "live";
export type ApiResult<T> = { data: T; source: Source };

export type DecisionKey = "depot" | "mail";
/** Which decisions the person has taken so far. A missing key means not yet. */
export type Dec = Partial<Record<DecisionKey, boolean>>;
export type TierKey = "quick" | "routine" | "workspace";

export interface User {
  first: string;
  name: string;
  initials: string;
  email: string;
  title: string;
  org: string;
  plan: string;
  tz: string;
  lang: string;
  hours: string;
}

export interface Today {
  long: string;
  short: string;
  time: string;
}

export interface Decision {
  k: DecisionKey;
  world: string;
  title: string;
  body: string;
  yes: string;
  icon: string;
  done: string;
}

export type TierName = "Village" | "Town" | "City";
export interface Tier {
  tier: TierName;
  tool: string;
  word: string;
  agents: number;
  cost: string;
  eta: string;
  ph: string;
  start: string;
  hint: string;
  chips: string[];
}

// Plans: the city layout that the world art draws.
export interface PlanBuilding {
  id: string;
  kit?: string;
  gen?: { name: string; fp: [number, number]; i: string };
  state?: string;
}
export interface PlanDistrict {
  id: string;
  name: string;
  hall?: boolean;
  icon: string;
  buildings: PlanBuilding[];
}
export interface PlanAgent {
  rank?: string;
  role?: string;
  at: string;
  expr?: string;
  ring?: boolean;
}
export interface Plan {
  districts: PlanDistrict[];
  gates?: { before: string; state: string }[];
  agents: PlanAgent[];
}

// Worlds
export type WorldState = "needs" | "running" | "finished" | "scheduled";
export interface WorldDistrict {
  name: string;
  icon: string;
  done: number;
  total: number;
  agents: number;
  st: WorldState;
  note: string;
}
export interface ActivityItem {
  t: string;
  role?: string;
  rank?: string;
  you?: boolean;
  who: string;
  text: string;
  kind: "needs" | "done" | "info";
}
export interface WorldRun {
  when: string;
  what: string;
  ok: boolean;
  cost: string;
}
/** A building in a world's one-row art: a kit name, or an inline generated building. */
export type RowKit =
  | string
  | { fp: [number, number]; fl: number; roof: string; fa: string; i: string };
/** Row and single art are `[building, state, district]`. */
export type ArtSlot = [RowKit, string, string];
export interface World {
  id: string;
  name: string;
  short: string;
  tier: TierName;
  tool: string;
  st: WorldState;
  meta?: string;
  agents: number;
  prog?: number;
  spend: string;
  of?: string;
  spendV: number;
  budget?: number;
  nextL: string;
  nextV: string;
  when?: string;
  owner: string;
  started: string;
  isNew?: boolean;
  plan?: string | null;
  districts?: WorldDistrict[] | null;
  activity?: ActivityItem[];
  row?: ArtSlot[] | null;
  single?: ArtSlot | null;
  runs?: WorldRun[] | null;
  skill?: string;
  out?: string | null;
}

// Skills and learning
export interface Skill {
  id: string;
  name: string;
  team: string;
  owner: string;
  role: string;
  runs: number;
  rate: number | null;
  last: string;
  improved: string;
  status: "live" | "draft";
  st: "trusted" | "learning" | "review" | "draft";
  first?: number;
  now?: number;
  from: string;
  tools: [string, number][];
  used: string[];
  steps: string[];
  ask?: { q: string; a: string[] };
}
export interface Learn {
  rates: { id: string; name: string; meta: string; steps: string[] }[];
  reviews: { id: string; meta: string; bars: number[] }[];
  helpers: {
    id: string;
    name: string;
    you?: boolean;
    init: string;
    c: string;
    impact: string;
    n: number;
  }[];
  /** `[id, name, icon, source, level, what each level can do]` */
  tools: [string, string, string, string, number, string[]][];
}

// Ledger
export interface LedgerTx {
  id: string;
  d: string;
  world: string;
  wn: string;
  item: string;
  type: string;
  amt: number;
  st: string;
  dec?: DecisionKey;
}
export interface LedgerEntry {
  day: string;
  t: string;
  k: string;
  dec?: DecisionKey;
  world: string;
  what: string;
  sub: string;
  amt: string;
  detail: [string, string][];
}
export interface Ledger {
  budget: number;
  spent: number;
  forecast: number;
  daily: number[];
  by: Record<"world" | "tool" | "role", { head: string; rows: [string, number][] }>;
  tx: LedgerTx[];
  runs: [string, number[], number, string][];
  waits: { buckets: [string, number][]; types: [string, string, string][] };
  memory: number[];
  hours: [string, number, string, string][];
  activity: LedgerEntry[];
}

// Agenda
export interface AgendaEvent {
  id: string;
  d: number;
  s: number;
  e: number;
  t: string;
  cal: "work" | "personal" | "tilo";
  joins?: boolean;
  past?: boolean;
  brief?: boolean;
  tiloOnly?: boolean;
}
export interface AgendaDetail {
  people: string[];
  brief?: string[];
  briefMeta?: string;
  notes?: string[];
  actions?: [string, string, string][];
}
export interface AgendaPin {
  id: string;
  board: "team" | "me";
  title: string;
  note: string;
  by: string;
  role?: string;
  suggested?: boolean;
  kind?: string;
  color: string;
  due?: string;
  group?: string;
  dec?: DecisionKey;
  done?: boolean;
  go?: string;
}
export interface Agenda {
  days: string[];
  wkend: string[];
  today: number;
  start: number;
  end: number;
  now: number;
  events: AgendaEvent[];
  slots: { d: number; s: number; e: number; l: string }[];
  details: Record<string, AgendaDetail>;
  pins: AgendaPin[];
}
export type AgendaSlot = Agenda["slots"][number];

// Team, connectors, notifications
export interface Team {
  people: {
    id: string;
    name: string;
    email: string;
    dept: string;
    role: string;
    active: string;
    you?: boolean;
    limit?: string;
    c: string;
  }[];
  rules: [string, string, string, boolean][];
  matrix: [string, number][];
  roles: string[];
  coverage: { id: string; what: string; who: string[]; wait: string; slow?: boolean }[];
}
export interface Connector {
  id: string;
  name: string;
  cat: string;
  mono: string;
  col: string;
  st: "connected" | "attention" | "available";
  acct?: string;
  sync?: string;
  scopes?: [string, number][];
  level?: number;
  used?: string[];
  blurb?: string;
}
export interface Notification {
  id: string;
  t: string;
  title: string;
  sub: string;
  kind: "needs" | "done" | "warn";
  go: ["world", string] | ["connectors"];
  dec?: DecisionKey;
}

// Acknowledgements of writes
export interface Ack {
  ok: true;
}
export interface DecideAck extends Ack {
  dec: Dec;
}
export interface StartAck extends Ack {
  world: World;
}
