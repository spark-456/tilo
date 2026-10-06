// WEB-1b test support: runs the user's two Park City art engines (design_handoff_tilo_web_app/design/
// tilo-world.js and tilo-park.js) in a Node vm with a stub `window`, so the TypeScript ports under
// src/park/engines can be compared with them tree by tree.
// Lives outside src/ on purpose: the honesty scan (FR-WLD-09) and the park static checks walk src/.
//
// The comparison is on a canonical form of the hyperscript trees (see `canon`): numbers exact, strings
// exact, object key order ignored. A serialising `h` turns every element into a plain
// `{ tag, props, children }` so prototype and port trees can be compared without React.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = path.dirname(fileURLToPath(import.meta.url));
export const WEB_DIR = path.resolve(here, "..", "..");
export const REPO_ROOT = path.resolve(WEB_DIR, "..", "..");
export const DESIGN_DIR = path.join(REPO_ROOT, "design_handoff_tilo_web_app", "design");
export const WORLD_JS = path.join(DESIGN_DIR, "tilo-world.js");
export const PARK_JS = path.join(DESIGN_DIR, "tilo-park.js");
export const APP_JS = path.join(DESIGN_DIR, "tilo-app.js");
export const ENGINES_DIR = path.join(WEB_DIR, "src", "park", "engines");

/** The hyperscript factory both engines take (the same shape the builder exports as `H`). */
export type TestH = (
  tag: string,
  props: Record<string, unknown> | null,
  ...children: unknown[]
) => unknown;
export type Fn = (...args: unknown[]) => unknown;
export type Engine = Record<string, unknown>;

/** A serialising `h`: every element becomes a plain, cross-realm-safe object. */
export const serialiseH: TestH = (tag, props, ...children) => ({ tag, props, children });

// ---------------------------------------------------------------------------------------------
// Fakes for the browser calls tilo-park.js makes (Blob, URL.createObjectURL). The same fakes are
// handed to the prototype's vm and to the port's injectable `env`, so the SVG strings can be compared.
// ---------------------------------------------------------------------------------------------
export class FakeBlob {
  readonly text: string;
  readonly type: string;
  constructor(parts: unknown[], opts?: { type?: string }) {
    this.text = parts.map(String).join("");
    this.type = opts?.type ?? "";
  }
}
export const fakeCreateObjectURL = (blob: FakeBlob): string => `blob:${blob.type}|${blob.text}`;
/** The `env` the port's `createPark` takes (the Blob class and createObjectURL, both optional). */
export const fakeEnv = { Blob: FakeBlob, createObjectURL: fakeCreateObjectURL };

// ---------------------------------------------------------------------------------------------
// Prototype loading
// ---------------------------------------------------------------------------------------------
function readProto(file: string): string {
  if (!fs.existsSync(file)) {
    throw new Error(
      `WEB-1b parity needs the design handoff prototype at ${file}. Merge the design handoff commit into this branch.`,
    );
  }
  return fs.readFileSync(file, "utf8");
}

interface ProtoWindow {
  TiloWorld?: (h: TestH) => Engine;
  TiloPark?: (h: TestH) => Engine;
  TiloApp?: { data: { plans(dec?: Record<string, boolean>): Record<string, unknown> } };
}

let ctx: { win: ProtoWindow } | undefined;
function protoContext(): { win: ProtoWindow } {
  if (ctx) return ctx;
  const win: ProtoWindow = {};
  const sandbox = vm.createContext({
    window: win,
    Blob: FakeBlob,
    URL: { createObjectURL: fakeCreateObjectURL },
  });
  vm.runInContext(readProto(WORLD_JS), sandbox, { filename: "tilo-world.js" });
  vm.runInContext(readProto(PARK_JS), sandbox, { filename: "tilo-park.js" });
  if (!win.TiloWorld || !win.TiloPark)
    throw new Error("the prototypes did not set TiloWorld/TiloPark");
  ctx = { win };
  return ctx;
}

/** A fresh prototype world engine (its own closure state, as `window.TiloWorld(h)` gives). */
export function protoWorld(h: TestH = serialiseH): Engine {
  const f = protoContext().win.TiloWorld;
  if (!f) throw new Error("TiloWorld missing");
  return f(h);
}

/** A fresh prototype park engine. It builds its own world engine inside, as the prototype does. */
export function protoPark(h: TestH = serialiseH): Engine {
  const f = protoContext().win.TiloPark;
  if (!f) throw new Error("TiloPark missing");
  return f(h);
}

let appData: { plans(dec?: Record<string, boolean>): Record<string, unknown> } | undefined;
/** The prototype's real plans (`D.plans(dec)` of tilo-app.js), copied out of the vm as plain JSON. */
export function protoPlans(
  dec: Record<string, boolean> = {},
): Record<string, Record<string, unknown>> {
  if (!appData) {
    const win: ProtoWindow = {};
    vm.runInNewContext(readProto(APP_JS), { window: win }, { filename: "tilo-app.js" });
    if (!win.TiloApp) throw new Error("tilo-app.js did not set window.TiloApp");
    appData = win.TiloApp.data;
  }
  return JSON.parse(JSON.stringify(appData.plans(dec))) as Record<string, Record<string, unknown>>;
}

/** The icon names the prototype's `icon()` table knows, read from the source (so the list cannot rot). */
export function protoIconNames(): string[] {
  const src = readProto(WORLD_JS);
  const from = src.indexOf("const K={", src.indexOf("function icon("));
  const to = src.indexOf("return E('g',{transform:`translate(${x} ${y}) scale(${s})`}", from);
  const names = [...src.slice(from, to).matchAll(/^\s{2}(\w+):\[/gm)].map((m) => m[1] as string);
  return names;
}

// ---------------------------------------------------------------------------------------------
// Canonical form and comparison
// ---------------------------------------------------------------------------------------------
export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

const isNode = (o: object): boolean => {
  const k = Object.keys(o);
  return k.length === 3 && "tag" in o && "props" in o && "children" in o;
};

/**
 * Cross-realm, order-independent canonical form. Numbers stay exact (NaN, infinities and -0 are
 * tagged strings so they cannot hide). Cycles (layout blocks point at their buildings and back) are
 * cut. In an element, a prop whose value is null or undefined is the same as no prop, and an element
 * with no props is `props: null`; nothing else is loosened.
 */
export function canon(v: unknown, stack: object[] = []): Json {
  if (v === null) return null;
  switch (typeof v) {
    case "undefined":
      return "[undefined]";
    case "number":
      if (Number.isNaN(v)) return "[NaN]";
      if (v === Number.POSITIVE_INFINITY) return "[Infinity]";
      if (v === Number.NEGATIVE_INFINITY) return "[-Infinity]";
      return Object.is(v, -0) ? "[-0]" : v;
    case "string":
    case "boolean":
      return v;
    case "function":
      return "[function]";
    case "bigint":
    case "symbol":
      return `[${typeof v}]`;
    default:
  }
  const o = v as object;
  if (stack.includes(o)) return "[cycle]";
  const next = [...stack, o];
  if (Array.isArray(o)) return o.map((x) => canon(x, next));
  if (o instanceof Set || Object.prototype.toString.call(o) === "[object Set]") {
    return { "[Set]": [...(o as Set<unknown>)].map((x) => canon(x, next)) };
  }
  const rec = o as Record<string, unknown>;
  const out: { [k: string]: Json } = {};
  const keys = Object.keys(rec).sort();
  if (isNode(o)) {
    const props = rec.props as Record<string, unknown> | null | undefined;
    const kept: { [k: string]: Json } = {};
    if (props) {
      for (const k of Object.keys(props).sort()) {
        const pv = props[k];
        if (pv !== null && pv !== undefined) kept[k] = canon(pv, next);
      }
    }
    out.tag = canon(rec.tag, next);
    out.props = Object.keys(kept).length ? kept : null;
    out.children = canon(rec.children, next);
    return out;
  }
  for (const k of keys) {
    const x = rec[k];
    if (x !== undefined) out[k] = canon(x, next);
  }
  return out;
}

/** Drops `animation: 'none'` style entries (the prototype writes them for a frozen walker). */
export function withoutAnimationNone(j: Json): Json {
  if (Array.isArray(j)) return j.map(withoutAnimationNone);
  if (j && typeof j === "object") {
    const out: { [k: string]: Json } = {};
    for (const [k, x] of Object.entries(j)) {
      if (k === "animation" && x === "none") continue;
      out[k] = withoutAnimationNone(x);
    }
    return out;
  }
  return j;
}

const clip = (s: string, at: number): string =>
  JSON.stringify(s.slice(Math.max(0, at - 50), at + 90));

/** The path and values of the first difference between two canonical trees, or null if equal. */
export function firstDiff(a: Json, b: Json, at = "$"): string | null {
  if (a === b) return null;
  if (typeof a === "string" && typeof b === "string") {
    let i = 0;
    while (i < a.length && i < b.length && a[i] === b[i]) i++;
    return `${at}: strings differ at char ${i}: port ${clip(a, i)} vs prototype ${clip(b, i)}`;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    const n = Math.max(a.length, b.length);
    for (let i = 0; i < n; i++) {
      if (i >= a.length)
        return `${at}[${i}]: missing in port (port has ${a.length} items, prototype ${b.length})`;
      if (i >= b.length)
        return `${at}[${i}]: extra in port (port has ${a.length} items, prototype ${b.length})`;
      const d = firstDiff(a[i] as Json, b[i] as Json, `${at}[${i}]`);
      if (d) return d;
    }
    return null;
  }
  if (
    a &&
    b &&
    typeof a === "object" &&
    typeof b === "object" &&
    !Array.isArray(a) &&
    !Array.isArray(b)
  ) {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    for (const k of new Set([...ka, ...kb])) {
      if (!(k in a))
        return `${at}.${k}: missing in port (prototype has ${JSON.stringify(b[k])?.slice(0, 80)})`;
      if (!(k in b)) return `${at}.${k}: extra in port (${JSON.stringify(a[k])?.slice(0, 80)})`;
      const d = firstDiff(a[k] as Json, b[k] as Json, `${at}.${k}`);
      if (d) return d;
    }
    return null;
  }
  return `${at}: port ${JSON.stringify(a)?.slice(0, 80)} vs prototype ${JSON.stringify(b)?.slice(0, 80)}`;
}

/** null when the port's value equals the prototype's, else where it first differs. */
export function sameAsPrototype(
  port: unknown,
  proto: unknown,
  opts: { frozenWalkers?: boolean } = {},
): string | null {
  const p = canon(proto);
  return firstDiff(canon(port), opts.frozenWalkers ? withoutAnimationNone(p) : p);
}

/** Number of nodes (objects, arrays, strings, numbers) in a canonical tree: a non-vacuity measure. */
export function size(v: unknown): number {
  const j = canon(v);
  let n = 0;
  const walk = (x: Json) => {
    n++;
    if (Array.isArray(x)) x.forEach(walk);
    else if (x && typeof x === "object") Object.values(x).forEach(walk);
  };
  walk(j);
  return n;
}

/** The motion words the port must not carry in any output (WEB-1b adds no keyframes, ADR-0003a 5). */
const MOTION_WORDS =
  /animation|keyframes|--dx|--dy|tiloDash|tiloBob|tiloGhost|tiloPulse|mvXY|waddle|sprite2/;
/** Which motion words appear in a port output tree (strings, keys and values alike). */
export function motionLeaks(port: unknown): string[] {
  const text = JSON.stringify(canon(port));
  return [...new Set(text.match(new RegExp(MOTION_WORDS.source, "g")) ?? [])];
}

/** Call a member of an engine by name; throws a readable error when it is missing. */
export function call(engine: Engine, name: string, ...args: unknown[]): unknown {
  const f = engine[name];
  if (typeof f !== "function") throw new Error(`engine has no function member "${name}"`);
  return (f as Fn)(...args);
}
