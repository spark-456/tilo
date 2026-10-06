// Shared types of the two Park City art engines (world.ts, park.ts), WEB-1b.
// The engines are ported from design_handoff_tilo_web_app/design/tilo-world.js and tilo-park.js
// (user's prototype, ADR-0003a); these types describe the shapes the prototype takes as plain objects.

/** The hyperscript factory both engines draw with (React's createElement shape, or a string builder). */
export type H = (
  tag: string,
  props: Record<string, unknown> | null,
  ...children: unknown[]
) => unknown;

/** One drawn element: whatever the factory `H` returns (the engines never look inside it). */
export type El = unknown;
export type Props = Record<string, unknown>;
/** A point in the projected (screen) plane, or a pair of plain numbers. */
export type Pt = [number, number];
/** The four corners of a box: minX, maxX, minY, maxY. */
export type Box4 = [number, number, number, number];
/** All keys optional and explicitly allowed to be undefined (option bags). */
export type Opt<T> = { [K in keyof T]?: T[K] | undefined };
/** Top, left and right face colours of a box. */
export interface Faces {
  t: string;
  l: string;
  r: string;
}

/**
 * The browser calls tilo-park.js makes, injectable so the engine never names a window global.
 * Defaults are the platform's own `Blob` and `URL.createObjectURL`.
 */
export interface ParkEnv {
  Blob?: (new (parts: BlobPart[], options?: BlobPropertyBag) => Blob) | undefined;
  createObjectURL?: ((blob: Blob) => string) | undefined;
}

/** A building spec (an entry of KIT, or one made by `specOf`). */
export type Spec = {
  n: string;
  fp: [number, number];
  fl: number;
  roof: string;
  fa: string;
  i: string;
} & Opt<{ yard: boolean; dock: boolean; gen: boolean }>;

export type GenSpec = { name: string } & Opt<{
  fp: [number, number];
  fl: number;
  roof: string;
  fa: string;
  i: string;
}>;

// ---- the plan the world is drawn from (the prototype's `D.plans(...)` entries) ----
export type PlanBuilding = Opt<{
  id: string;
  kit: string;
  name: string;
  fl: number;
  gen: GenSpec;
  state: string;
  event: string;
  count: string;
}>;
export type PlanDistrict = { id: string; name: string; buildings: PlanBuilding[] } & Opt<{
  tint: string;
  hall: boolean;
  locked: boolean;
  icon: string;
}>;
export type PlanRoute = { from: string; to: string } & Opt<{ id: string; kind: string }>;
export type PlanGate = { before: string } & Opt<{ state: string }>;
/** The look of one agent (what `agent()` draws). */
export type AgentSpec = Opt<{
  role: string;
  rank: string;
  expr: string;
  facing: string;
  back: boolean;
  step: boolean;
  ring: boolean;
  pack: boolean;
  parcel: boolean;
}>;
export type PlanAgent = AgentSpec &
  Opt<{ at: string; route: string; t: number; dx: number; dy: number }>;
export type PlanPresence = { at: string; initials: string } & Opt<{ color: string }>;
export interface PlanComment {
  at: string;
  n: number | string;
}
export type Plan = { districts: PlanDistrict[] } & Opt<{
  routes: PlanRoute[];
  gates: PlanGate[];
  agents: PlanAgent[];
  presence: PlanPresence[];
  comments: PlanComment[];
}>;

// ---- layout (the solver-free packing the prototype does inside world()) ----
export type LBuilding = PlanBuilding & {
  s: Spec;
  cx: number;
  cy: number;
  block: Block;
  front: boolean;
  laneY: number;
};
export interface Block {
  d: PlanDistrict;
  tint: string;
  rows: LBuilding[][];
  rw: number[];
  rd: number[];
  w: number;
  h0: number;
  x: number;
  y: number;
  h: number;
  frontRoad: number;
  leftRoad: number;
  lanes: [number, number][];
  trees: [number, number][];
}
export interface Layout {
  blocks: Block[];
  bmap: Record<string, LBuilding>;
  Wt: number;
  Dt: number;
  hg: number[];
  vseg: [number, number, number][];
  ring: [number, number];
}

// ---- option bags ----
export type PinOpts = Opt<{
  lift: number;
  r: number;
  tint: string;
  icon: string;
  count: string;
  /** Accepted and ignored: motion is restored in WEB-3 (BQ-WEB-3). */
  anim: string | null;
}>;
export type TagOpts = Opt<{ fs: number; left: boolean; ink: string }>;
export type AgentOpts = Opt<{ scale: number; anim: string | null }>;
export type BuildingOpts = Opt<{ tint: string }>;
export type WorldOpts = Opt<{
  seed: number;
  labels: boolean;
  stage: number;
  /** Accepted and ignored: motion is restored in WEB-3 (BQ-WEB-3). */
  anim: boolean;
  tags: boolean;
  ls: number;
  dvis: Set<string>;
  bvis: Set<string>;
  parts: boolean;
  width: number | string;
  height: number | string;
}>;
export interface WorldParts {
  ground: El[];
  objs: { k: number; el: El }[];
  cover: El[];
  top: El[];
  L: Layout;
  M: number;
  bb: Box4;
}
export type SoloBuildingOpts = Opt<{
  tint: string;
  d: string;
  height: number;
  pin: boolean;
  cloud: boolean;
}>;
export type Lift = Opt<{ t: number; state: string; parcel: boolean; label: string }>;
export type Sat = { plan: Plan } & Opt<{ truck: number }>;
export type Level = { name: string; code: string; plan: Plan } & Opt<{
  color: string;
  stage: number;
  sats: Sat[];
  lifts: Lift[];
}>;
export type MetroOpts = Opt<{
  seed: number;
  labels: boolean;
  /** Accepted and ignored: motion is restored in WEB-3 (BQ-WEB-3). */
  anim: boolean;
  gapZ: number;
  zig: number;
  width: number | string;
  height: number | string;
}>;
export type SceneOpts = Opt<{
  w: number;
  h: number;
  vw: number;
  seed: number;
  night: boolean;
  /** Accepted and ignored: motion is restored in WEB-3 (BQ-WEB-3). */
  k: number;
  /** Accepted and ignored: the scene is always drawn frozen until WEB-3 (BQ-WEB-3). */
  still: boolean;
  mute: number;
}>;
/** A spot on the backdrop where the app may place a pin (scene()'s second result). */
export interface Spot {
  x: number;
  y: number;
  area: number;
  st: string;
}

// ---- the render kit (kit.ts, WEB-1c; ported from tilo-app.js `kit(h)`) ----
/** The decisions taken so far (structurally the same as `Dec` of ../api/types, which engines may not import). */
export type Dec = Partial<Record<"depot" | "mail", boolean>>;
/** The plan source: the prototype's `D.plans(dec)`, every plan by id. */
export type PlanSource = (dec?: Dec) => Record<string, Plan>;
/** What `createKit(h, deps)` needs: the plan source and the optional browser calls of the park engine. */
export interface KitDeps {
  plans: PlanSource;
  env?: ParkEnv | undefined;
}
/** A building in a world's art: a kit name, or an inline generated building (no name of its own). */
export type ArtKit =
  | string
  | { fp: [number, number]; fl: number; roof: string; fa: string; i: string };
/** An art slot is `[building, state, district]`. */
export type ArtSlot = [ArtKit, string, string];
/** The part of a world that `art()` and `strip()` read: `single` or `row`, both null or missing when absent. */
export interface ArtWorld {
  single?: ArtSlot | null | undefined;
  row?: ArtSlot[] | null | undefined;
}
