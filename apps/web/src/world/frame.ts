// FR-WLD-04: a pure frame function (layout, state) -> plain-data display list. Placeholder
// shapes only (art port is P0-08c); colours from tokens only, geometry from the solver only.
import type { Layout } from "@tilo/contracts";
import tokens from "../design/tokens";
import type { BuildingStatus, WorldState } from "./reducer";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;
// The solver assigns one of 6 numbered district roles (district.1..6); the design exports have
// no numbered slots (design/tokens.json note on `color.district`), so this cycles the named tint
// pool it does expose, in the fixed order the tokens module already lists them.
const DISTRICT_TINTS = Object.values(tokens.color.district).slice(0, 6);

function districtTint(tint: string): string {
  const n = Number(tint.split(".")[1] ?? "1");
  return DISTRICT_TINTS[(n - 1) % DISTRICT_TINTS.length] ?? tokens.color.ink["3"];
}

const BUILDING_COLOR: Readonly<Record<BuildingStatus, string | null>> = {
  hidden: null, // not drawn at all until building.planned
  planned: tokens.color.ink["3"],
  constructing: tokens.color.signal.needs,
  operational: null, // filled in with the owning district's tint (see buildingColor below)
  completed: tokens.color.signal.done,
  archived: tokens.color.ink["2"],
};

function buildingColor(status: BuildingStatus, tint: string): string | null {
  if (status === "operational") return districtTint(tint);
  return BUILDING_COLOR[status];
}

export interface FrameRect {
  readonly id: string;
  readonly cx: number; // projected world-space centre (iso projection of the grid footprint)
  readonly cy: number;
  readonly gw: number; // grid footprint, for the renderer's own iso diamond sizing
  readonly gd: number;
  readonly color: string;
}

export interface FrameAgent {
  readonly id: string;
  readonly cx: number;
  readonly cy: number;
  readonly color: string;
}

export interface Frame {
  readonly status: WorldState["status"];
  readonly districts: readonly FrameRect[];
  readonly buildings: readonly FrameRect[];
  readonly agents: readonly FrameAgent[];
}

/** Standard 2:1 iso projection of a grid-space point, in the same world-unit space Stage.tsx's
 * own iso grid is drawn in (tokens.stage tileWidth/tileHeight). */
function project(gx: number, gy: number): { x: number; y: number } {
  return { x: ((gx - gy) * TW) / 2, y: ((gx + gy) * TH) / 2 };
}

/** The building/district/level id `target` resolves to, for placing an agent. */
function locationCentre(layout: Layout, id: string | null): { x: number; y: number } | null {
  if (!id || !layout.geometry) return null;
  const rects = [
    ...layout.geometry.buildings.map((b) => ({ id: b.id, ...b.footprint })),
    ...layout.geometry.districts.map((d) => ({ id: d.id, ...d.plot })),
    ...layout.geometry.levels.map((l) => ({ id: l.id, ...l.plate })),
  ];
  const r = rects.find((r) => r.id === id);
  return r ? project(r.x + r.w / 2, r.y + r.d / 2) : null;
}

export function frameOf(layout: Layout, state: WorldState): Frame {
  const geometry = layout.geometry;
  const districtTintById = new Map(geometry?.districts.map((d) => [d.id, d.tint]) ?? []);
  const buildingDistrict = new Map<string, string>();
  for (const level of layout.semantic.levels) {
    for (const district of level.districts) {
      for (const building of district.buildings) buildingDistrict.set(building.id, district.id);
    }
  }

  const districts: FrameRect[] = (geometry?.districts ?? []).map((d) => {
    const c = project(d.plot.x + d.plot.w / 2, d.plot.y + d.plot.d / 2);
    return { id: d.id, cx: c.x, cy: c.y, gw: d.plot.w, gd: d.plot.d, color: districtTint(d.tint) };
  });

  const buildings: FrameRect[] = (geometry?.buildings ?? []).flatMap((b) => {
    const status = state.buildings[b.id]?.status ?? "hidden";
    const tint = districtTintById.get(buildingDistrict.get(b.id) ?? "") ?? "district.1";
    const color = buildingColor(status, tint);
    if (!color) return [];
    const c = project(b.footprint.x + b.footprint.w / 2, b.footprint.y + b.footprint.d / 2);
    return [{ id: b.id, cx: c.x, cy: c.y, gw: b.footprint.w, gd: b.footprint.d, color }];
  });

  const agents: FrameAgent[] = Object.values(state.agents).flatMap((agent) => {
    if (!agent.spawned) return [];
    const c = locationCentre(layout, agent.location);
    if (!c) return [];
    return [{ id: agent.id, cx: c.x, cy: c.y, color: tokens.color.ink["1"] }];
  });

  return { status: state.status, districts, buildings, agents };
}
