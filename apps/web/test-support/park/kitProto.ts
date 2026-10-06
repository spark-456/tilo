// WEB-1c test support: runs the user's whole Park City prototype render kit (`TiloApp.kit(h)` of
// design_handoff_tilo_web_app/design/tilo-app.js, with the prototype tilo-world.js and tilo-park.js as
// window.TiloWorld / window.TiloPark and the prototype's own `D`) in a Node vm, so the TypeScript kit
// under src/park/engines/kit.ts can be compared with it. It reuses the WEB-1b vm fakes and canonical
// compare from engineProto.ts and does not create a second reference construction: the prototype runs
// with the same serialising `h` and the same fake Blob / URL.createObjectURL, and the comparison is
// `sameAsPrototype(port, proto, { frozenWalkers: true })`, exactly as the WEB-1b park parity does
// (the port draws movers frozen; WEB-3 restores motion).
// Lives outside src/ on purpose: the honesty scan (FR-WLD-09) and the park static checks walk src/.
import fs from "node:fs";
import vm from "node:vm";
import {
  APP_JS,
  DESIGN_DIR,
  type Engine,
  FakeBlob,
  PARK_JS,
  type TestH,
  WORLD_JS,
  fakeCreateObjectURL,
  serialiseH,
} from "./engineProto";

export type Dec = Record<string, boolean>;

/** What art() and strip() read of a world: `single` or `row` (null or missing when it has none). */
export interface ArtWorld {
  single?: unknown;
  row?: unknown;
}

/** The members `createKit(h, deps)` returns, as the prototype's `kit(h)` returns them. */
export interface Kit {
  W: Engine;
  TP: Engine;
  ck: <T>(key: string, f: () => T) => T;
  icon: (name: string, size?: number) => unknown;
  agent: (a: Record<string, unknown>, size?: number, night?: boolean) => unknown;
  building: (spec: unknown, state: string, dist?: string, ht?: number, night?: boolean) => unknown;
  world: (planId: string, dec?: Dec, night?: boolean) => unknown;
  art: (w: ArtWorld, ht?: number, night?: boolean) => unknown;
  strip: (w: ArtWorld, ht?: number, night?: boolean) => unknown;
}

export const KIT_MEMBERS = ["TP", "W", "agent", "art", "building", "ck", "icon", "strip", "world"];

/** The second argument of `createKit`: the plan source and the optional browser calls. */
export interface KitDeps {
  plans: (dec?: Dec) => Record<string, unknown>;
  env?: unknown;
}
export type MakeKit = (h: TestH, deps: KitDeps) => Kit;

export interface ProtoData {
  plans(dec?: Dec): Record<string, unknown>;
  worlds(dec?: Dec, added?: unknown[]): unknown[];
  makeWorld(mode: string, q: string, i: number): unknown;
  TIERS: Record<string, unknown>;
}

interface ProtoWindow {
  TiloApp?: { data: ProtoData; kit(h: TestH): Kit; ready(): boolean };
}

let scripts: vm.Script[] | undefined;
function compiled(): vm.Script[] {
  if (scripts) return scripts;
  scripts = [WORLD_JS, PARK_JS, APP_JS].map((file) => {
    if (!fs.existsSync(file)) {
      throw new Error(
        `WEB-1c parity needs the design handoff prototype at ${file}. Merge the design handoff commit into this branch.`,
      );
    }
    return new vm.Script(fs.readFileSync(file, "utf8"), { filename: file });
  });
  return scripts;
}

/**
 * A fresh prototype kit in its own vm context (the prototype's kit is a module singleton, so each call
 * needs a fresh context), plus that context's `D`. Same fakes as the WEB-1b park reference.
 */
export function protoKitWithData(h: TestH = serialiseH): { kit: Kit; data: ProtoData } {
  const win: ProtoWindow = {};
  const sandbox = vm.createContext({
    window: win,
    Blob: FakeBlob,
    URL: { createObjectURL: fakeCreateObjectURL },
  });
  for (const s of compiled()) s.runInContext(sandbox);
  if (!win.TiloApp) throw new Error("tilo-app.js did not set window.TiloApp");
  return { kit: win.TiloApp.kit(h), data: win.TiloApp.data };
}

export function protoKit(h: TestH = serialiseH): Kit {
  return protoKitWithData(h).kit;
}

/**
 * The prototype's `D.worlds(dec, added)` as plain JSON, with one world made by each tier appended
 * (`D.makeWorld`: a quick task has `single`, a routine has `row`, a workspace has neither). The list
 * holds worlds with `single`, with `row` (one with an inline generated building) and with neither.
 */
export function protoWorlds(dec: Dec = {}): Record<string, unknown>[] {
  const { data } = protoKitWithData();
  const added = Object.keys(data.TIERS).map((mode, i) => data.makeWorld(mode, "A new world", i));
  return JSON.parse(JSON.stringify(data.worlds(dec, added))) as Record<string, unknown>[];
}

/** The names in the prototype kit's own icon table `X` (read from the source, so the list cannot rot). */
export function protoKitIconNames(): string[] {
  const src = fs.readFileSync(`${DESIGN_DIR}/tilo-app.js`, "utf8");
  const from = src.indexOf("const X={");
  const to = src.indexOf("const icon=", from);
  if (from < 0 || to < 0) throw new Error("could not find the X icon table in tilo-app.js");
  return [...src.slice(from, to).matchAll(/^\s{2}(\w+):\(\)=>/gm)].map((m) => m[1] as string);
}

/** Every serialised element (`{ tag, props, children }`) in a tree, parents before children. */
export function nodesOf(v: unknown): { tag: string; props: Record<string, unknown> | null }[] {
  const out: { tag: string; props: Record<string, unknown> | null }[] = [];
  const walk = (x: unknown) => {
    if (Array.isArray(x)) return x.forEach(walk);
    if (x && typeof x === "object") {
      const o = x as Record<string, unknown>;
      if ("tag" in o && "props" in o && "children" in o) {
        out.push({ tag: String(o.tag), props: o.props as Record<string, unknown> | null });
        walk(o.children);
      }
    }
  };
  walk(v);
  return out;
}
