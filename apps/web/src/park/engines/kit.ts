// ported from design_handoff_tilo_web_app/design/tilo-app.js (user's prototype, ADR-0003a)
// The render kit of the Park City app: the icon set, and the memoised agent, building and world pictures
// the screens draw (`kit(h)` and its icon table `X`, lines ~250-300 of the prototype). Faithful port: same
// icon geometry, same cache keys character for character, same memo semantics. Differences by design:
// `createKit(h, deps)` instead of the `window.TiloWorld` / `window.TiloPark` / `window.TiloApp` globals
// (the two engines are built from `./world` and `./park`; the plan source `D.plans` and the optional
// browser calls come in through `deps`), one cache per kit instead of one per document, no `ready()`
// (it only checked those globals), and no animation (the engines draw movers frozen, BQ-WEB-3).
import { createPark } from "./park";
import type { AgentSpec, ArtKit, ArtWorld, Dec, El, H, KitDeps, Plan, Props, Spec } from "./types";
import { createWorld } from "./world";

/** The names of the kit's own icon table, in the prototype's order. Other names fall through to the world engine. */
export const ICON_NAMES = [
  "home",
  "grid",
  "calendar",
  "bell",
  "plus",
  "chevR",
  "chevL",
  "chevD",
  "x",
  "plug",
  "arrowR",
  "arrowL",
  "more",
  "shield",
  "card",
  "sun",
  "moon",
  "pause",
  "play",
  "share",
  "download",
  "logout",
  "bolt",
  "refresh",
  "phone",
  "sparkle",
  "record",
  "upload",
  "pen",
  "globe",
] as const;
type IconName = (typeof ICON_NAMES)[number];

export function createKit(h: H, deps: KitDeps) {
  const W = createWorld(h);
  const TP = createPark(h, createWorld, deps.env);
  const C = new Map<string, unknown>();
  const ck = <T>(k: string, f: () => T): T => {
    if (C.has(k)) return C.get(k) as T;
    const v = f();
    C.set(k, v);
    return v;
  };

  const sw = {
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    fill: "none",
  };
  const p = (d: string, o?: Props): El => h("path", { d, ...sw, ...(o || {}) });
  const rect = (x: number, y: number, width: number, height: number, rx: number): El =>
    h("rect", { x, y, width, height, rx, ...sw });
  const X: Record<IconName, () => El | El[]> = {
    home: () => p("M-7 -0.5 L0 -6.5 L7 -0.5 M-5 -2 V6.5 H5 V-2"),
    grid: () => [
      rect(-7, -7, 5.5, 5.5, 1.5),
      rect(1.5, -7, 5.5, 5.5, 1.5),
      rect(-7, 1.5, 5.5, 5.5, 1.5),
      rect(1.5, 1.5, 5.5, 5.5, 1.5),
    ],
    calendar: () => [rect(-7, -5.5, 14, 12.5, 2.5), p("M-7 -1.5 H7 M-3.5 -8 V-4 M3.5 -8 V-4")],
    bell: () => [
      p("M-5.5 3.5 V-1 Q-5.5 -6.5 0 -6.5 Q5.5 -6.5 5.5 -1 V3.5 L7 5.5 H-7 Z"),
      p("M-2 7.5 H2"),
    ],
    plus: () => p("M0 -6 V6 M-6 0 H6", { strokeWidth: 2.4 }),
    chevR: () => p("M-2 -5 L3 0 L-2 5", { strokeWidth: 2.4 }),
    chevL: () => p("M2 -5 L-3 0 L2 5", { strokeWidth: 2.4 }),
    chevD: () => p("M-5 -2 L0 3 L5 -2", { strokeWidth: 2.4 }),
    x: () => p("M-5 -5 L5 5 M5 -5 L-5 5", { strokeWidth: 2.4 }),
    plug: () => [
      p("M-3 -8 V-4 M3 -8 V-4 M0 4.5 V8"),
      p("M-6 -4 H6 V-0.5 Q6 4.5 0 4.5 Q-6 4.5 -6 -0.5 Z"),
    ],
    arrowR: () => p("M-6 0 H6 M2 -4 L6 0 L2 4"),
    arrowL: () => p("M6 0 H-6 M-2 -4 L-6 0 L-2 4"),
    more: () =>
      [-5, 0, 5].map((x) => h("circle", { key: x, cx: x, cy: 0, r: 1.6, fill: "currentColor" })),
    shield: () => p("M0 -7.5 L6.5 -5 V0 Q6.5 5 0 7.5 Q-6.5 5 -6.5 0 V-5 Z"),
    card: () => [rect(-8, -5.5, 16, 11, 2), p("M-8 -1.5 H8 M-5 2.5 H-1")],
    sun: () => [
      h("circle", { cx: 0, cy: 0, r: 3.2, ...sw }),
      p(
        "M0 -7.5 V-6 M0 6 V7.5 M-7.5 0 H-6 M6 0 H7.5 M-5.3 -5.3 L-4.3 -4.3 M4.3 4.3 L5.3 5.3 M-5.3 5.3 L-4.3 4.3 M4.3 -4.3 L5.3 -5.3",
      ),
    ],
    moon: () => p("M2.5 -6.8 A6.8 6.8 0 1 0 6.8 2.5 A5.2 5.2 0 0 1 2.5 -6.8 Z"),
    pause: () => p("M-2.5 -5 V5 M2.5 -5 V5", { strokeWidth: 2.6 }),
    play: () => h("path", { d: "M-3 -5.5 L5 0 L-3 5.5 Z", fill: "currentColor" }),
    share: () => p("M1.5 -6.5 H6.5 V-1.5 M6.5 -6.5 L-0.5 0.5 M3.5 2 V6.5 H-6.5 V-3.5 H-2"),
    download: () => p("M0 -7 V3 M-4 -1 L0 3 L4 -1 M-6.5 6.5 H6.5"),
    logout: () => p("M-1.5 -6.5 H-6.5 V6.5 H-1.5 M1.5 -3.5 L5 0 L1.5 3.5 M5 0 H-2.5"),
    bolt: () => h("path", { d: "M1.5 -8 L-5 1 H-0.5 L-1.5 8 L5 -1 H0.5 Z", fill: "currentColor" }),
    refresh: () => [p("M5.8 -1.5 A6 6 0 1 0 5 3.4"), p("M6.2 -6 V-1.2 H1.5")],
    phone: () => [rect(-4.5, -7.5, 9, 15, 2.2), p("M-1 5 H1")],
    sparkle: () =>
      h("path", {
        d: "M0 -7.5 Q1 -1 7.5 0 Q1 1 0 7.5 Q-1 1 -7.5 0 Q-1 -1 0 -7.5 Z",
        fill: "currentColor",
      }),
    record: () => [
      h("circle", { cx: 0, cy: 0, r: 6.5, ...sw }),
      h("circle", { cx: 0, cy: 0, r: 3, fill: "currentColor" }),
    ],
    upload: () => p("M0 4 V-6 M-4 -2 L0 -6 L4 -2 M-6.5 6.5 H6.5"),
    pen: () => p("M-6 6 L-5 2 L3 -6 L6 -3 L-2 5 Z M1 -4 L4 -1"),
    globe: () => [
      h("circle", { cx: 0, cy: 0, r: 7, ...sw }),
      p("M-7 0 H7 M0 -7 Q-4 0 0 7 Q4 0 0 -7"),
    ],
  };
  const isIcon = (n: string): n is IconName => (ICON_NAMES as readonly string[]).includes(n);

  const icon = (n: string, s?: number): El =>
    h(
      "svg",
      {
        width: s || 16,
        height: s || 16,
        viewBox: "-10 -10 20 20",
        style: { display: "block", flex: "none" },
        "aria-hidden": true,
      },
      ...[isIcon(n) ? X[n]() : W.icon(n, "currentColor", 0, 0, 0.9, "#FFFFFF")].flat(),
    );
  const agent = (a: AgentSpec, s?: number, night?: boolean): El =>
    ck(`a|${JSON.stringify(a)}|${s}|${!!night}`, () => TP.agent(a, s, night));
  const building = (
    spec: ArtKit | Spec,
    st: string,
    dist?: string,
    ht?: number,
    night?: boolean,
  ): El =>
    ck(`b|${JSON.stringify(spec)}${st}${dist}${ht}${!!night}`, () =>
      // an inline generated building has no name of its own; the world engine never needs one
      TP.building(spec as string | Spec, st, dist, ht, night),
    );
  const world = (planId: string, dec?: Dec, night?: boolean): El => {
    // The key is the plan and the decisions that are on (sorted), so each decision state is its own picture.
    const on = Object.keys(dec ?? {})
      .filter((k) => dec?.[k as keyof Dec])
      .sort()
      .join("+");
    return ck(`w|${planId}|${on}|${!!night}`, () => {
      const plan: Plan | undefined = deps.plans(dec)[planId];
      if (!plan) throw new Error(`createKit: no plan with id "${planId}"`);
      return TP.world(plan, { night });
    });
  };
  const art = (w: ArtWorld, ht?: number, night?: boolean): El => {
    const src = w.single || w.row?.[0];
    return src ? building(src[0], src[1], src[2], ht, night) : null;
  };
  const strip = (w: ArtWorld, ht?: number, night?: boolean): El =>
    w.row
      ? w.row.map((b, i) =>
          h(
            "div",
            { key: i, style: { marginLeft: i ? -14 : 0 } },
            building(b[0], b[1], b[2], ht, night),
          ),
        )
      : null;
  return { W, TP, ck, icon, agent, building, world, art, strip };
}
