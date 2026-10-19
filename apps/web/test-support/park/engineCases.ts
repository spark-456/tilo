// WEB-1b test support: the input matrices the parity tests run through both engines. The plans are the
// prototype's own (`D.plans(dec)` of tilo-app.js, copied out of the vm as plain JSON), plus one rich
// plan that reaches every branch of world(): routes, walking agents on routes, gates, presence,
// comments, a locked district (clouds), a district of an unknown id (fallback tint) and a wrapped row.
import { protoPlans } from "./engineProto";

export type Plan = Record<string, unknown>;
export type Dec = Record<string, boolean>;

/** The four decision combinations the prototype's K1 plan reacts to. */
export const DEC_COMBOS: readonly { name: string; dec: Dec }[] = [
  { name: "neither", dec: { depot: false, mail: false } },
  { name: "depot", dec: { depot: true, mail: false } },
  { name: "mail", dec: { depot: false, mail: true } },
  { name: "both", dec: { depot: true, mail: true } },
];

export const PLAN_IDS = ["k1", "hires", "audit", "fresh"] as const;

/** A fresh copy of a real prototype plan. */
export function plan(id: (typeof PLAN_IDS)[number], dec: Dec = {}): Plan {
  const p = protoPlans(dec)[id];
  if (!p) throw new Error(`no prototype plan ${id}`);
  return p;
}

/** Every (plan, decisions) the prototype ships: 4 K1 variants and the three other plans. */
export function realPlans(): { name: string; make: () => Plan }[] {
  return [
    ...DEC_COMBOS.map((c) => ({ name: `k1/${c.name}`, make: () => plan("k1", c.dec) })),
    { name: "hires", make: () => plan("hires") },
    { name: "audit", make: () => plan("audit") },
    { name: "fresh", make: () => plan("fresh") },
  ];
}

/** A plan that exercises routes, gates, presence, comments, locks, wraps and unknown ids. */
export function richPlan(): Plan {
  const kit = (id: string, k: string, state?: string, extra: Record<string, unknown> = {}) => ({
    id,
    kit: k,
    ...(state ? { state } : {}),
    ...extra,
  });
  return {
    districts: [
      {
        id: "hall",
        name: "Town Hall",
        hall: true,
        icon: "hall",
        buildings: [
          kit("townhall", "townhall", "active"),
          kit("treasury", "treasury", "complete"),
          kit("watch", "watchtower", "needs", { event: "search", count: "3" }),
        ],
      },
      {
        id: "fw",
        name: "Firmware",
        icon: "laptop",
        buildings: [
          kit("office", "workshop", "blocked"),
          {
            id: "depot",
            gen: { name: "Laptop Depot", fp: [2, 1], i: "laptop", fl: 2 },
            state: "active",
            event: "laptop",
          },
          kit("lib", "library", "complete"),
        ],
      },
      {
        id: "zzz",
        name: "Elsewhere",
        tint: "delivery",
        icon: "parcel",
        buildings: [
          kit("b1", "browser", "skipped"),
          kit("b2", "testyard", "construction"),
          kit("b3", "dock", "planned"),
          kit("b4", "vault", "idle", { name: "Archive", fl: 3 }),
          kit("b5", "meeting", "active", { event: "people" }),
          { id: "b6", gen: { name: "Mystery Annex" }, state: "needs" },
        ],
      },
      {
        id: "payroll",
        name: "Payroll",
        locked: true,
        icon: "coin",
        buildings: [kit("pay1", "treasury"), kit("pay2", "clock")],
      },
      {
        id: "unlisted",
        name: "No tint match",
        buildings: [kit("u1", "desk", "active"), kit("u2", "connector", "complete")],
      },
    ],
    routes: [
      { id: "m1", from: "office", to: "lib", kind: "memory" },
      { from: "depot", to: "pay1" },
      { from: "townhall", to: "u2" },
      { id: "dead", from: "office", to: "nowhere" },
    ],
    gates: [
      { before: "depot", state: "waiting" },
      { before: "office", state: "open" },
      { before: "b1" },
      { before: "nonexistent", state: "open" },
    ],
    agents: [
      { rank: "director", at: "townhall" },
      { role: "builder", at: "office", expr: "focused" },
      { role: "research", route: "m1", t: 0.3, expr: "walking" },
      { role: "delivery", route: "m1", expr: "walking", facing: "R", step: true },
      { role: "tester", at: "depot", dx: 14, dy: -6, expr: "needs", ring: true },
      { role: "connector", rank: "lead", at: "u1", expr: "talking", parcel: true },
      { role: "finance", at: "missing-building" },
      { role: "browser", route: "no-such-route", at: "b5", expr: "puzzled" },
    ],
    presence: [
      { at: "office", initials: "AM", color: "#F0A500" },
      { at: "office", initials: "JP" },
      { at: "nowhere", initials: "XX" },
    ],
    comments: [
      { at: "depot", n: 3 },
      { at: "depot", n: 12 },
      { at: "nowhere", n: 1 },
    ],
  };
}

/** Option sets for world(): every flag the prototype reads. `anim` is covered by its own test. */
export function worldOptionSets(plan: Plan): { name: string; opts: Record<string, unknown> }[] {
  const ids = ((plan.districts as { id: string; buildings: { id?: string }[] }[]) ?? []).flatMap(
    (d) => d.buildings.map((b) => b.id ?? ""),
  );
  const firstDistrict = ((plan.districts as { id: string }[])[0] as { id: string }).id;
  return [
    { name: "defaults", opts: {} },
    { name: "seed 2", opts: { seed: 2 } },
    { name: "seed 7, labels and tags off", opts: { seed: 7, labels: false, tags: false } },
    { name: "stage 1", opts: { stage: 1 } },
    { name: "stage 2", opts: { stage: 2 } },
    { name: "stage 3", opts: { stage: 3 } },
    { name: "stage 4 with labels and tags", opts: { stage: 4, labels: true, tags: true } },
    { name: "1000 x 640", opts: { width: 1000, height: 640 } },
    { name: "50% x 300", opts: { width: "50%", height: 300 } },
    { name: "label scale 1.4", opts: { ls: 1.4 } },
    { name: "only the first district visible", opts: { dvis: new Set([firstDistrict]) } },
    {
      name: "only some buildings visible",
      opts: { bvis: new Set(ids.filter((_, i) => i % 2 === 0)) },
    },
    {
      name: "the park thumbnail options",
      opts: { seed: 3, labels: false, tags: false, anim: false, width: 1000, height: 640 },
    },
  ];
}

/** Levels for metro(): three levels, satellites (with and without a truck), lifts in every state. */
export function metroLevels(): Record<string, unknown>[] {
  const plans = protoPlans({ depot: true, mail: false });
  return [
    {
      name: "Concept",
      code: "L1",
      color: "#2B98B5",
      plan: plans.fresh,
      lifts: [{ t: 0.3, state: "active", label: "Spec pack", parcel: true }],
    },
    {
      name: "Prototype",
      code: "L2",
      plan: plans.hires,
      stage: 3,
      sats: [
        { plan: plans.audit, truck: 0.4 },
        { plan: plans.fresh, truck: 0.7 },
        { plan: plans.audit },
      ],
      lifts: [
        { t: 0, state: "planned" },
        { t: 0.8, state: "idle", label: "Parts" },
      ],
    },
    { name: "Launch", code: "L3", plan: plans.k1 },
  ];
}

export const METRO_OPTION_SETS: { name: string; opts: Record<string, unknown> | undefined }[] = [
  { name: "no options", opts: undefined },
  { name: "defaults spelled", opts: { seed: 1, labels: true, anim: false } },
  { name: "seed 4, no labels", opts: { seed: 4, labels: false } },
  { name: "gapZ 260, zig 90, 900 x 700", opts: { gapZ: 260, zig: 90, width: 900, height: 700 } },
  { name: "zig 0", opts: { zig: 0 } },
];

export const BUILDING_STATES = [
  "planned",
  "construction",
  "active",
  "needs",
  "complete",
  "idle",
  "skipped",
  "blocked",
] as const;

export const EXPRESSIONS = [
  "neutral",
  "focused",
  "needs",
  "delighted",
  "talking",
  "puzzled",
  "sleepy",
  "walking",
  "recovering",
] as const;

export const RANKS: (string | undefined)[] = ["director", "lead", "specialist", undefined];

/** The scene option sets the design uses (1600 x 1000 desktop, a phone) and the knobs it exposes. */
export const SCENE_OPTION_SETS: { name: string; opts: Record<string, unknown> | undefined }[] = [
  {
    name: "desktop day as the design calls it",
    opts: { w: 1600, h: 1000, vw: 1240, night: false, k: 1, still: false },
  },
  { name: "desktop night", opts: { w: 1600, h: 1000, vw: 1240, night: true, k: 1, still: false } },
  { name: "phone day", opts: { w: 390, h: 844, night: false } },
  { name: "phone night", opts: { w: 390, h: 844, night: true } },
  { name: "no options at all", opts: undefined },
  { name: "defaults, still", opts: { still: true } },
  { name: "1440 x 900, muted .5", opts: { w: 1440, h: 900, mute: 0.5 } },
  { name: "1440 x 900, fully muted", opts: { w: 1440, h: 900, mute: 1 } },
  { name: "seed 7, slow-down k 2", opts: { w: 1280, h: 800, seed: 7, k: 2 } },
  { name: "wide view vw 900, seed 99", opts: { w: 1000, h: 700, vw: 900, seed: 99 } },
  { name: "night wins over mute", opts: { w: 800, h: 600, night: true, mute: 0.8 } },
];
