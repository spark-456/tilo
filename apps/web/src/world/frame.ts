// FR-WLD-04: a pure frame function (layout, state) -> plain-data display list. Geometry comes from
// the solver only; district tints are the solver's roles mapped onto token colours; a building's
// look follows only what the reducer has recorded (status), never a guess. Drawing is art/ and
// renderer.ts; nothing in this file knows about Pixi.
import type { Layout } from "@tilo/contracts";
import tokens from "../design/tokens";
import type { BuildingShown, Facade, Roof } from "./art/building";
import { hash } from "./art/color";
import { type Bridge, type GateLook, LEVEL_RISE, type Link, MARGIN, type Rect } from "./art/ground";
import { P } from "./art/iso";
import { styleOf } from "./art/style";
import { districtLabel } from "./labels";
import { type WorldState, standingAt } from "./reducer";
import { agentNames } from "./runSummary";

const NAMES = new WeakMap<Layout, Map<string, string>>();
function namesOf(layout: Layout): Map<string, string> {
  let names = NAMES.get(layout);
  if (!names) {
    names = agentNames(layout);
    NAMES.set(layout, names);
  }
  return names;
}

// The solver assigns one of 6 numbered district roles (district.1..6); the design exports have
// no numbered slots (design/tokens.json note on `color.district`), so this cycles the named tint
// pool it does expose, in the fixed order the tokens module already lists them.
const DISTRICT_TINTS = Object.values(tokens.color.district).slice(0, 6);

function districtTint(tint: string): string {
  const n = Number(tint.split(".")[1] ?? "1");
  return DISTRICT_TINTS[(n - 1) % DISTRICT_TINTS.length] ?? tokens.color.ink["3"];
}

/** What every ringed or hit-tested thing carries: its centre on the ground, and its footprint. */
export interface FrameRect {
  readonly id: string;
  readonly cx: number; // projected world-space centre of the footprint (at its level's height)
  readonly cy: number;
  readonly gw: number; // grid footprint, for the renderer's own iso diamond sizing
  readonly gd: number;
}
export interface FrameDistrict extends FrameRect {
  readonly name: string;
  readonly rect: Rect;
  readonly tint: string;
  readonly lift: number;
}
export interface FrameBuilding extends FrameRect {
  readonly name: string;
  readonly rect: Rect;
  readonly floors: number;
  readonly status: BuildingShown;
  readonly tint: string;
  readonly roof: Roof;
  readonly facade: Facade;
  readonly lift: number;
}
export interface FrameIsland extends FrameRect {
  readonly name: string;
  readonly rect: Rect;
  readonly state: Link;
  readonly lift: number;
}
export interface FramePath {
  readonly points: ReadonlyArray<{ readonly x: number; readonly y: number }>;
  readonly lift: number;
}
export interface FrameBridge extends FramePath {
  readonly island: string;
  readonly kind: Bridge;
  readonly state: Link;
}
export interface FrameGate {
  readonly id: string;
  readonly cell: { readonly x: number; readonly y: number };
  readonly state: GateLook;
  readonly lift: number;
}
export interface FrameAgent {
  readonly id: string;
  readonly cx: number; // where its feet stand
  readonly cy: number;
  readonly rank: string;
  readonly tint: string;
  readonly level: number; // stacking order of the level it stands on, for draw order
  /** The tool icon over it: agent.working was its latest event (WORLD-LIVE). */
  readonly working: boolean;
  /** Its latest handoff note and who it went to, until its next event (WORLD-LIVE); null otherwise. */
  readonly say: FrameSay | null;
}
/** A speech bubble: the receiver's name (or, when `head` is set, that exact heading) over the words. */
export interface FrameSay {
  readonly text: string;
  readonly to: string;
  readonly head?: string;
}

export interface Frame {
  readonly status: WorldState["status"];
  readonly plates: ReadonlyArray<{
    readonly id: string;
    readonly rect: Rect;
    readonly lift: number;
  }>;
  readonly districts: readonly FrameDistrict[];
  readonly buildings: readonly FrameBuilding[];
  readonly islands: readonly FrameIsland[];
  readonly roads: readonly FramePath[];
  readonly bridges: readonly FrameBridge[];
  readonly gates: readonly FrameGate[];
  readonly agents: readonly FrameAgent[];
  /** The world's extent in px (from the plates), the same for every state: the stage frames it. */
  readonly bounds: {
    readonly x0: number;
    readonly y0: number;
    readonly x1: number;
    readonly y1: number;
  };
}

const centreOf = (r: Rect, lift: number): { cx: number; cy: number } => {
  const [cx, cy] = P(r.x + r.w / 2, r.y + r.d / 2, lift);
  return { cx, cy };
};

/** Where an agent stands at a building, district or level: on the ground in front of a building, on the plot's front
 * lane, on the plate's front edge. `slot` (its place in the layout's roster) fans out agents that share a spot by the
 * golden ratio, so any number of them spread across the frontage in a fixed pattern that never changes when another
 * arrives (TILO-T-WORLD: nobody huddles, nobody shifts). */
function standAt(r: Rect, kind: "building" | "district" | "level", lift: number, slot: number) {
  const across = (slot * 0.618034) % 1; // 0..1 along the frontage
  const row = slot % 2; // two lanes deep
  const [sx, sy] =
    kind === "building"
      ? [r.x + r.w * (0.1 + 0.8 * across), r.y + r.d + 0.5 + row * 0.45]
      : [
          r.x + r.w * (0.1 + 0.8 * across),
          r.y + r.d - (kind === "district" ? 0.6 : 0.5) - row * 0.35,
        ];
  const [x, y] = P(sx, sy, lift);
  return { cx: x, cy: y };
}

/** The ground in front of a building where agents rest (the whole frontage `standAt` fans over),
 * in world px: feet only, so a caller pads it by a figure's size. From the layout alone, so a
 * building's tag can keep clear of it whoever is standing there (nothing here moves). */
export function standZone(r: Rect, lift: number) {
  const feet = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((slot) => standAt(r, "building", lift, slot));
  const xs = feet.map((f) => f.cx);
  const ys = feet.map((f) => f.cy);
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
}

export function frameOf(layout: Layout, state: WorldState): Frame {
  const geometry = layout.geometry;
  const levelIndex = new Map(geometry?.levels.map((l) => [l.id, l.index]));
  const liftOf = (levelId: string | undefined) => (levelIndex.get(levelId ?? "") ?? 0) * LEVEL_RISE;
  const buildingLevel = new Map<string, string>();
  const buildingDistrict = new Map<string, string>();
  const districtLevel = new Map<string, string>();
  const names = new Map<string, string>();
  const common = new Map<string, string | undefined>();
  const leads = new Map<string, string>();
  for (const level of layout.semantic.levels) {
    for (const district of level.districts) {
      districtLevel.set(district.id, level.id);
      names.set(district.id, districtLabel(district));
      leads.set(district.lead, district.id);
      for (const building of district.buildings) {
        buildingLevel.set(building.id, level.id);
        buildingDistrict.set(building.id, district.id);
        names.set(building.id, building.name);
        common.set(building.id, building.common_type);
      }
    }
  }
  const tints = new Map(geometry?.districts.map((d) => [d.id, districtTint(d.tint)]));

  const plates = (geometry?.levels ?? []).map((l) => ({
    id: l.id,
    rect: l.plate,
    lift: liftOf(l.id),
  }));
  const districts: FrameDistrict[] = (geometry?.districts ?? []).map((d) => {
    const lift = liftOf(districtLevel.get(d.id));
    return {
      id: d.id,
      name: names.get(d.id) ?? d.id,
      rect: d.plot,
      tint: tints.get(d.id) ?? tokens.color.ink["3"],
      lift,
      ...centreOf(d.plot, lift),
      gw: d.plot.w,
      gd: d.plot.d,
    };
  });
  const buildings: FrameBuilding[] = (geometry?.buildings ?? []).flatMap((b) => {
    const status = state.buildings[b.id]?.status ?? "hidden";
    if (status === "hidden") return []; // nothing is drawn until building.planned
    const lift = liftOf(buildingLevel.get(b.id));
    return [
      {
        id: b.id,
        name: names.get(b.id) ?? b.id,
        rect: b.footprint,
        floors: b.floors,
        status,
        tint: tints.get(buildingDistrict.get(b.id) ?? "") ?? tokens.color.ink["3"],
        ...styleOf({ id: b.id, common_type: common.get(b.id) as never }),
        lift,
        ...centreOf(b.footprint, lift),
        gw: b.footprint.w,
        gd: b.footprint.d,
      },
    ];
  });
  const islandState = new Map(layout.semantic.islands.map((i) => [i.id, i]));
  const islands: FrameIsland[] = (geometry?.islands ?? []).flatMap((i) => {
    const sem = islandState.get(i.id);
    const lift = liftOf(i.level);
    return [
      {
        id: i.id,
        name: sem?.name ?? i.id,
        rect: i.plot,
        state: sem?.state ?? "connected",
        lift,
        ...centreOf(i.plot, lift),
        gw: i.plot.w,
        gd: i.plot.d,
      },
    ];
  });
  const roads: FramePath[] = (geometry?.roads ?? []).map((r) => ({
    points: r.path,
    lift: liftOf(buildingLevel.get(r.from)),
  }));
  const bridges: FrameBridge[] = (geometry?.bridges ?? []).map((b) => ({
    island: b.island,
    kind: islandState.get(b.island)?.bridge ?? "road",
    state: islandState.get(b.island)?.state ?? "connected",
    points: b.path,
    lift: liftOf(buildingLevel.get(b.from)),
  }));
  const gateBuilding = new Map(layout.semantic.gates.map((g) => [g.id, g.between[0]]));
  const gates: FrameGate[] = (geometry?.gates ?? []).map((g) => ({
    id: g.id,
    cell: g.cell,
    state: state.gates[g.id] ?? "closed",
    lift: liftOf(buildingLevel.get(gateBuilding.get(g.id) ?? "")),
  }));

  // Where each placed agent stands: a building, district or level it was last sent to.
  const spots = new Map<
    string,
    { r: Rect; kind: "building" | "district" | "level"; lift: number; level: number }
  >();
  for (const b of geometry?.buildings ?? []) {
    spots.set(b.id, {
      r: b.footprint,
      kind: "building",
      lift: liftOf(buildingLevel.get(b.id)),
      level: levelIndex.get(buildingLevel.get(b.id) ?? "") ?? 0,
    });
  }
  for (const d of geometry?.districts ?? []) {
    spots.set(d.id, {
      r: d.plot,
      kind: "district",
      lift: liftOf(districtLevel.get(d.id)),
      level: levelIndex.get(districtLevel.get(d.id) ?? "") ?? 0,
    });
  }
  for (const l of geometry?.levels ?? [])
    spots.set(l.id, { r: l.plate, kind: "level", lift: liftOf(l.id), level: l.index });
  const rank = new Map(layout.semantic.agents.map((a, i) => [a.id, { rank: a.rank, slot: i }]));
  const agents: FrameAgent[] = Object.values(state.agents).flatMap((agent) => {
    const stands = standingAt(state, agent);
    const spot = agent.spawned && stands ? spots.get(stands) : undefined;
    const meta = rank.get(agent.id);
    if (!spot || !meta) return [];
    const ledDistrict = leads.get(agent.id);
    const tint =
      (ledDistrict && tints.get(ledDistrict)) ||
      DISTRICT_TINTS[hash(agent.id) % DISTRICT_TINTS.length] ||
      tokens.color.ink["2"];
    return [
      {
        id: agent.id,
        ...standAt(spot.r, spot.kind, spot.lift, meta.slot),
        rank: meta.rank,
        tint,
        level: spot.level,
        working: agent.working,
        say: agent.say
          ? { text: agent.say.text, to: namesOf(layout).get(agent.say.to) ?? "You" }
          : null,
      },
    ];
  });

  const corners = plates.flatMap((p) => {
    const [x, y] = [p.rect.x - MARGIN, p.rect.y - MARGIN]; // the slab runs MARGIN past its plate
    const [w, d] = [p.rect.w + 2 * MARGIN, p.rect.d + 2 * MARGIN];
    return [P(x, y, p.lift), P(x + w, y, p.lift), P(x + w, y + d, p.lift), P(x, y + d, p.lift)];
  });
  const xs = corners.map((c) => c[0]);
  const ys = corners.map((c) => c[1]);
  const bounds = corners.length
    ? {
        x0: Math.min(...xs),
        y0: Math.min(...ys) - 90,
        x1: Math.max(...xs),
        y1: Math.max(...ys) + 20,
      }
    : { x0: 0, y0: 0, x1: 0, y1: 0 };
  return {
    status: state.status,
    plates,
    districts,
    buildings,
    islands,
    roads,
    bridges,
    gates,
    agents,
    bounds,
  };
}
