// ported from design_handoff_tilo_web_app/design/tilo-world.js (user's prototype, ADR-0003a)
// The Park City isometric art engine: buildings, agents, pins, roads, clouds, whole worlds and the
// metropolis. Faithful port: same names, numbers, rounding, call order and seeded rng as the prototype,
// so the parity tests (the prototype run in a Node vm, trees compared) stay green. Not carried over:
// `window.TiloWorld` (this is `createWorld(h)`), and the animation (motion returns in WEB-3, BQ-WEB-3).
import type {
  AgentOpts,
  AgentSpec,
  Block,
  Box4,
  BuildingOpts,
  El,
  Faces,
  GenSpec,
  H,
  LBuilding,
  Layout,
  Level,
  MetroOpts,
  Opt,
  PinOpts,
  Plan,
  PlanAgent,
  PlanBuilding,
  PlanRoute,
  Props,
  Pt,
  SoloBuildingOpts,
  Spec,
  TagOpts,
  WorldOpts,
  WorldParts,
} from "./types";

/* ============ utilities ============ */
const hx = (c: string): [number, number, number] => {
  const s = c.replace("#", "");
  return [
    Number.parseInt(s.slice(0, 2), 16),
    Number.parseInt(s.slice(2, 4), 16),
    Number.parseInt(s.slice(4, 6), 16),
  ];
};
const toHex = (a: number[]): string =>
  `#${a
    .map((v) =>
      Math.max(0, Math.min(255, Math.round(v)))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
const mix = (a: string, b: string, t: number): string => {
  const A = hx(a);
  const B = hx(b);
  return toHex(A.map((v, i) => v + ((B[i] as number) - v) * t));
};
const dk = (c: string, t?: number | null): string => mix(c, "#000000", t == null ? 0.2 : t);
const lt = (c: string, t?: number | null): string => mix(c, "#ffffff", t == null ? 0.5 : t);
const gray = (c: string): string => {
  const [r, g, b] = hx(c);
  const y = 0.3 * r + 0.59 * g + 0.11 * b;
  return toHex([y, y, y]);
};
const hash = (s: string): number => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};
const rng = (seed: number): (() => number) => {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};
const clamp = (v: number, a: number, b: number): number => Math.max(a, Math.min(b, v));

/* ============ tokens ============ */
const K0 = {
  hero: "#5A3FE0",
  heroLip: "#3F2AAE",
  ink: "#1F1D2B",
  ink2: "#5A5768",
  gT: "#EEEBE2",
  gL: "#D3CDBD",
  gR: "#BEB7A5",
  road: "#DCD7CA",
  plinT: "#F1EEE6",
  plinL: "#D6D0C0",
  plinR: "#C2BBA8",
  dash: "#8F8A9C",
  scaffold: "#9A8566",
  kraft: "#D8B27C",
  kraftD: "#B48A52",
  cloud: "#FFFFFF",
  cloudD: "#E4E0D5",
  ok: "#1F7F44",
  amber: "#F0A500",
  amberLip: "#B97E00",
  red: "#D23B30",
  blue: "#2A6FD6",
  grey: "#66717A",
  body: "'Nunito Sans',sans-serif",
};
const DIST: Record<string, string> & { hall: string; research: string; payroll: string } = {
  hall: "#7D8793",
  research: "#2B98B5",
  analysis: "#D7864F",
  delivery: "#B35C8F",
  accounts: "#8A9A3F",
  people: "#A8784A",
  learning: "#5B7FA6",
  mail: "#6F8F8A",
  payroll: "#7D8793",
};
const ROLE: Record<string, string> = {
  research: "#3F7FE0",
  builder: "#E57F3E",
  tester: "#C9982A",
  browser: "#2BA3B8",
  connector: "#D9588C",
  delivery: "#76A035",
  designer: "#A45DB8",
  finance: "#3E9A7C",
  bot: "#8C939B",
};
const KIT: Record<string, Spec> = {
  townhall: { n: "Town Hall", fp: [3, 2], fl: 2, roof: "dome", fa: "arches", i: "hall" },
  library: { n: "Library", fp: [2, 2], fl: 2, roof: "gable", fa: "arches", i: "search" },
  browser: { n: "Browser Station", fp: [2, 1], fl: 2, roof: "flat", fa: "band", i: "screen" },
  workshop: { n: "Workshop", fp: [2, 2], fl: 1, roof: "gable", fa: "windows", i: "make" },
  testyard: {
    n: "Test Yard",
    fp: [2, 2],
    fl: 1,
    roof: "flat",
    fa: "windows",
    i: "flask",
    yard: true,
  },
  connector: { n: "Connector Post", fp: [1, 1], fl: 3, roof: "flat", fa: "band", i: "key" },
  vault: { n: "Memory Vault", fp: [2, 1], fl: 1, roof: "dome", fa: "windows", i: "vault" },
  treasury: { n: "Treasury", fp: [1, 1], fl: 2, roof: "dome", fa: "arches", i: "coin" },
  watchtower: { n: "Watchtower", fp: [1, 1], fl: 4, roof: "gable", fa: "windows", i: "eye" },
  dock: {
    n: "Delivery Dock",
    fp: [2, 1],
    fl: 1,
    roof: "flat",
    fa: "windows",
    i: "parcel",
    dock: true,
  },
  clock: { n: "Clock Tower", fp: [1, 1], fl: 4, roof: "dome", fa: "arches", i: "clock" },
  desk: { n: "Your Desk", fp: [1, 1], fl: 2, roof: "gable", fa: "windows", i: "person" },
  meeting: { n: "Meeting Hall", fp: [2, 1], fl: 1, roof: "dome", fa: "arches", i: "people" },
  appstudio: { n: "App Studio", fp: [2, 1], fl: 2, roof: "flat", fa: "band", i: "screen" },
};
const T = 48;
const INS = 5;
const GAP = 0.3 * T;
const PAD = 0.4 * T;
const LANE = 0.85 * T;
const G = 0.82 * T;
const AS = 1.35;

/** The building colours `colorsFor` derives from a tint. */
interface BColors {
  wl: string;
  roof: string;
  door: string;
  win: string;
  winOn: string;
  tint: string;
  wr: string;
  wt: string;
  roofB: string;
  roofR: string;
  roofT: string;
}
type Pin3 = [string, string, string];

export function createWorld(h: H) {
  let LS = 1;
  const E = (t: string, p: Props | null, ...c: unknown[]): El =>
    h(t, p, ...c.flat(9).filter((x) => x != null && x !== false));
  /* ============ projection ============ */
  const C = 0.866;
  const S = 0.5;
  const P = (x: number, y: number, z?: number): Pt => [(x - y) * C, (x + y) * S - (z || 0)];
  const pts = (a: Pt[]): string => a.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const mat = (a: number, b: number, c: number, d: number, p: Pt): string =>
    `matrix(${a} ${b} ${c} ${d} ${p[0].toFixed(2)} ${p[1].toFixed(2)})`;
  const mL = (x: number, y: number, z?: number): string => mat(C, S, 0, 1, P(x, y, z)); // face on plane y=const, u→+x, v→down
  const mR = (x: number, y: number, z?: number): string => mat(C, -S, 0, 1, P(x, y, z)); // face on plane x=const, u→−y (front to back)
  const mT = (x: number, y: number, z?: number): string => mat(C, S, -C, S, P(x, y, z)); // top plane
  const poly = (a: Pt[], fill: string, ex?: Props): El =>
    E("polygon", {
      points: pts(a),
      fill,
      stroke: fill,
      strokeWidth: 0.7,
      strokeLinejoin: "round",
      ...(ex || {}),
    });
  function box(
    x: number,
    y: number,
    z: number,
    w: number,
    d: number,
    hh: number,
    c: Faces,
    ex?: Props,
  ): El[] {
    return [
      poly(
        [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + hh), P(x, y + d, z + hh)],
        c.l,
        ex,
      ),
      poly(
        [P(x + w, y + d, z), P(x + w, y, z), P(x + w, y, z + hh), P(x + w, y + d, z + hh)],
        c.r,
        ex,
      ),
      poly(
        [P(x, y, z + hh), P(x + w, y, z + hh), P(x + w, y + d, z + hh), P(x, y + d, z + hh)],
        c.t,
        ex,
      ),
    ];
  }
  const shade = (c: string): Faces => ({ t: lt(c, 0.22), l: c, r: dk(c, 0.2) });

  /* ============ icons ============ */
  function icon(n: string, c: string, x: number, y: number, s?: number, bg?: string): El {
    const sc = s || 1;
    const bgc = bg || "#fff";
    const sw = {
      stroke: c,
      strokeWidth: 2.4,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      fill: "none",
    };
    const f = { fill: c };
    const R = (rx: number, ry: number, w: number, hh: number, r: number, o?: Props): El =>
      E("rect", { x: rx, y: ry, width: w, height: hh, rx: r, ...(o || f) });
    const K: Record<string, El[]> = {
      search: [
        E("circle", { cx: -1.5, cy: -1.5, r: 4.8, ...sw }),
        E("path", { d: "M2.2 2.2 L6.5 6.5", ...sw, strokeWidth: 3 }),
      ],
      screen: [R(-7, -6, 14, 10, 2.2), E("path", { d: "M-3 7 H3", ...sw })],
      hall: [
        E("path", {
          d: "M-8 -2 L0 -8 L8 -2 Z",
          ...f,
          stroke: c,
          strokeWidth: 1.5,
          strokeLinejoin: "round",
        }),
        R(-6.5, -1, 3, 7.5, 1),
        R(-1.5, -1, 3, 7.5, 1),
        R(3.5, -1, 3, 7.5, 1),
      ],
      make: [R(-7, -7, 11, 6, 1.8), R(-2.2, -2, 3.6, 10, 1.6)],
      flask: [E("path", { d: "M-3.5 -7 H3.5 M-2.5 -7 V-1.5 L-6.5 6 H6.5 L2.5 -1.5 V-7", ...sw })],
      key: [
        E("circle", { cx: -3.5, cy: 0, r: 3.6, ...sw }),
        E("path", { d: "M0 0 H7.5 M5 0 V3 M7.5 0 V2.5", ...sw }),
      ],
      vault: [
        E("circle", { cx: 0, cy: 0, r: 6.5, ...sw }),
        E("circle", { cx: 0, cy: 0, r: 2.2, ...f }),
      ],
      coin: [E("circle", { cx: 0, cy: 0, r: 7, ...f }), R(-1.3, -4, 2.6, 8, 1.3, { fill: bgc })],
      eye: [
        E("path", { d: "M-7.5 0 Q0 -7 7.5 0 Q0 7 -7.5 0 Z", ...sw }),
        E("circle", { cx: 0, cy: 0, r: 2.2, ...f }),
      ],
      parcel: [
        R(-7, -5.5, 14, 11, 2),
        E("path", {
          d: "M-7 -1 H7 M0 -5.5 V-1",
          stroke: bgc,
          strokeWidth: 2,
          strokeLinecap: "round",
        }),
      ],
      clock: [
        E("circle", { cx: 0, cy: 0, r: 6.8, ...sw }),
        E("path", { d: "M0 -3.5 V0 L2.8 1.8", ...sw }),
      ],
      tag: [
        E("path", {
          d: "M-7 -1 L-1 -7 H7 V1 L1 7 Z",
          ...f,
          stroke: c,
          strokeWidth: 1.5,
          strokeLinejoin: "round",
        }),
        E("circle", { cx: 3.5, cy: -3.5, r: 1.6, fill: bgc }),
      ],
      chart: [R(-7, 0, 4, 7, 1.2), R(-2, -4, 4, 11, 1.2), R(3, -7, 4, 14, 1.2)],
      doc: [
        R(-6, -7.5, 12, 15, 2.2, sw),
        E("path", { d: "M-3 -3 H3 M-3 0.5 H3 M-3 4 H1", ...sw, strokeWidth: 2 }),
      ],
      swap: [E("path", { d: "M-6 -3 H5 M2 -6 L5 -3 L2 0 M6 3 H-5 M-2 0 L-5 3 L-2 6", ...sw })],
      person: [
        E("circle", { cx: 0, cy: -3, r: 3.4, ...f }),
        E("path", { d: "M-6.5 7 Q0 -1 6.5 7 Z", ...f }),
      ],
      laptop: [R(-6, -6, 12, 8, 1.8), R(-8, 3, 16, 3, 1.2)],
      mail: [
        R(-7, -5, 14, 10, 2, sw),
        E("path", { d: "M-6 -4 L0 1 L6 -4", ...sw, strokeWidth: 2 }),
      ],
      cap: [
        E("path", {
          d: "M-8 -2 L0 -6 L8 -2 L0 2 Z",
          ...f,
          stroke: c,
          strokeWidth: 1.4,
          strokeLinejoin: "round",
        }),
        E("path", { d: "M-4.5 0 V4 Q0 6.5 4.5 4 V0", ...f }),
      ],
      lock: [
        R(-6, -1.5, 12, 9, 2.2),
        E("path", { d: "M-3.5 -1.5 V-4 Q0 -8.5 3.5 -4 V-1.5", ...sw }),
      ],
      check: [E("path", { d: "M-5 0.5 L-1.5 4 L5.5 -3.5", ...sw, strokeWidth: 3 })],
      flag: [
        E("path", { d: "M-5 7 V-7", ...sw }),
        E("path", {
          d: "M-5 -7 H5 L3 -3.5 L5 0 H-5 Z",
          ...f,
          stroke: c,
          strokeWidth: 1.5,
          strokeLinejoin: "round",
        }),
      ],
      marker: [
        E("path", { d: "M0 -5 V1", stroke: c, strokeWidth: 3, strokeLinecap: "round" }),
        E("circle", { cx: 0, cy: 4.6, r: 1.7, fill: c }),
      ],
      dot: [E("circle", { cx: 0, cy: 0, r: 4, ...f })],
      battery: [
        R(-7, -4.5, 12, 9, 2),
        R(5, -2, 2.5, 4, 1),
        R(-5, -2.5, 3, 5, 0.8, { fill: bgc }),
        R(-1, -2.5, 3, 5, 0.8, { fill: bgc }),
      ],
      wheel: [
        E("circle", { cx: 0, cy: 0, r: 6.5, ...sw, strokeWidth: 2.8 }),
        E("circle", { cx: 0, cy: 0, r: 2, ...f }),
      ],
      cog: [
        E("circle", { cx: 0, cy: 0, r: 4.5, ...sw, strokeWidth: 3 }),
        E("circle", { cx: 0, cy: 0, r: 1.4, ...f }),
      ],
      people: [
        E("circle", { cx: -3.8, cy: -2.8, r: 2.6, ...f }),
        E("circle", { cx: 3.8, cy: -2.8, r: 2.6, ...f }),
        E("path", { d: "M-8.5 6 Q-3.8 -0.5 0.6 6 Z", ...f }),
        E("path", { d: "M-0.6 6 Q3.8 -0.5 8.5 6 Z", ...f }),
      ],
      help: [
        E("path", {
          d: "M-3.2 -3.2 Q-3.2 -7 0.2 -7 Q3.6 -7 3.6 -3.6 Q3.6 -1.2 0.4 -0.2 V1.6",
          ...sw,
          strokeWidth: 2.6,
        }),
        E("circle", { cx: 0.4, cy: 5.4, r: 1.7, ...f }),
      ],
      up: [E("path", { d: "M0 6.5 V-6 M-5 -1 L0 -6 L5 -1", ...sw, strokeWidth: 2.8 })],
    };
    return E("g", { transform: `translate(${x} ${y}) scale(${sc})` }, K[n] || K.dot);
  }

  /* ============ pins (billboards) ============ */
  function pin(kind: string, p: Pt, o0?: PinOpts): El {
    const o = o0 || {};
    const cy = p[1] - (o.lift || 26);
    const r = o.r || 11;
    const M: Record<string, Pin3> = {
      complete: [K0.ok, "check", "#FFFFFF"],
      needs: [K0.amber, "flag", K0.ink],
      blocked: [K0.red, "marker", "#FFFFFF"],
      fyi: [K0.blue, "dot", "#FFFFFF"],
      lock: [K0.grey, "lock", "#FFFFFF"],
      skipped: [K0.grey, "dot", "#FFFFFF"],
    };
    let body: El[];
    if (kind === "active") {
      const tc = o.tint || K0.hero;
      body = [
        E("circle", { cx: p[0], cy, r, fill: "#FFFFFF", stroke: tc, strokeWidth: 2.5 }),
        icon(o.icon || "dot", dk(tc, 0.15), p[0], cy, r / 12),
      ];
    } else if (kind === "blocked") {
      body = [
        E("rect", {
          x: p[0] - r * 0.85,
          y: cy - r * 0.85,
          width: r * 1.7,
          height: r * 1.7,
          rx: 3.5,
          fill: K0.red,
          stroke: "#FFFFFF",
          strokeWidth: 2.5,
          transform: `rotate(45 ${p[0]} ${cy})`,
        }),
        icon("marker", "#FFFFFF", p[0], cy, r / 12),
      ];
    } else {
      const m = (M[kind] || M.fyi) as Pin3;
      body = [
        E("circle", { cx: p[0], cy, r, fill: m[0], stroke: "#FFFFFF", strokeWidth: 2.5 }),
        icon(m[1], m[2], p[0], cy, r / 12, m[0]),
      ];
    }
    const out: El[] = [
      E("path", {
        d: `M${p[0]} ${p[1]} V${cy + r}`,
        stroke: K0.ink,
        strokeWidth: 2,
        strokeLinecap: "round",
        opacity: 0.55,
      }),
      body,
    ];
    if (o.count) {
      const cw = o.count.length * 6.6 + 14;
      out.push(
        E("rect", { x: p[0] + r + 3, y: cy - 9, width: cw, height: 18, rx: 9, fill: K0.ink }),
        E(
          "text",
          {
            x: p[0] + r + 3 + cw / 2,
            y: cy + 3.8,
            textAnchor: "middle",
            fontFamily: K0.body,
            fontSize: 11,
            fontWeight: 800,
            fill: "#FFFFFF",
          },
          o.count,
        ),
      );
    }
    // motion: restored in WEB-3 (BQ-WEB-3)
    return E("g", null, out);
  }
  function tag(text: string, p0: Pt, fill: string, ic?: string, o0?: TagOpts): El {
    const o = o0 || {};
    const fs = o.fs || 11;
    const w = text.length * fs * 0.58 + (ic ? 30 : 16);
    const hh = fs + 9;
    const p: Pt = o.left ? [p0[0] + w / 2, p0[1]] : p0;
    return E(
      "g",
      null,
      E("rect", {
        x: p[0] - w / 2,
        y: p[1] - hh / 2 + 2,
        width: w,
        height: hh,
        rx: hh / 2,
        fill: dk(fill, 0.25),
      }),
      E("rect", { x: p[0] - w / 2, y: p[1] - hh / 2, width: w, height: hh, rx: hh / 2, fill }),
      ic
        ? E("circle", { cx: p[0] - w / 2 + hh / 2, cy: p[1], r: hh / 2 - 3, fill: "#FFFFFF" })
        : null,
      ic ? icon(ic, fill, p[0] - w / 2 + hh / 2, p[1], (hh / 2 - 3) / 9, "#FFFFFF") : null,
      E(
        "text",
        {
          x: p[0] + (ic ? 8 : 0),
          y: p[1] + fs * 0.36,
          textAnchor: "middle",
          fontFamily: K0.body,
          fontSize: fs,
          fontWeight: 800,
          fill: o.ink || "#FFFFFF",
        },
        text,
      ),
    );
  }
  function label(text: string, p: Pt): El {
    const fs = 10.5 * LS;
    const w = text.length * fs * 0.56 + 14 * LS;
    const hh = 18 * LS;
    return E(
      "g",
      null,
      E("rect", {
        x: p[0] - w / 2,
        y: p[1] - hh / 2,
        width: w,
        height: hh,
        rx: hh / 2,
        fill: "#FFFFFF",
        stroke: "#E3E0D8",
        strokeWidth: 1.5,
      }),
      E(
        "text",
        {
          x: p[0],
          y: p[1] + fs * 0.36,
          textAnchor: "middle",
          fontFamily: K0.body,
          fontSize: fs,
          fontWeight: 800,
          fill: K0.ink,
        },
        text,
      ),
    );
  }

  /* ============ buildings ============ */
  function colorsFor(tint: string, st: string): BColors {
    const c: BColors = {
      wl: lt(tint, 0.8),
      roof: tint,
      door: dk(tint, 0.45),
      win: lt(tint, 0.45),
      winOn: "#FFFFFF",
      tint,
      wr: "",
      wt: "",
      roofB: "",
      roofR: "",
      roofT: "",
    };
    c.wr = dk(c.wl, 0.15);
    c.wt = lt(c.wl, 0.35);
    c.roofB = lt(tint, 0.14);
    c.roofR = dk(tint, 0.24);
    c.roofT = lt(tint, 0.22);
    if (st === "skipped") {
      for (const k of Object.keys(c) as (keyof BColors)[]) c[k] = gray(lt(c[k], 0.2));
    }
    return c;
  }
  function facade(
    side: string,
    x0: number,
    y0: number,
    W: number,
    D: number,
    hb: number,
    s: Spec,
    c: BColors,
    lit: boolean,
    fl: number,
  ): El {
    const len = side === "L" ? W : D;
    const tr = side === "L" ? mL(x0, y0 + D, 3 + hb) : mR(x0 + W, y0 + D, 3 + hb);
    const base = side === "L" ? c.wl : c.wr;
    const F: El[] = [];
    const du = len < 60 ? 0.3 : 0.26;
    const dx = len * du;
    for (let i = 1; i < fl; i++) {
      const v = hb - 26 - (i - 1) * 22;
      F.push(E("rect", { x: 0, y: v - 1.5, width: len, height: 3, fill: dk(base, 0.07) }));
    }
    const winC = lit ? c.winOn : c.win;
    for (let f = 0; f < fl; f++) {
      const vTop = f === 0 ? hb - 20 : hb - 26 - f * 22 + 5;
      const wh = f === 0 ? 11 : 12;
      const skip = (u: number): boolean => side === "L" && f === 0 && Math.abs(u - dx) < 13;
      if (s.fa === "band") {
        if (side === "L" && f === 0) {
          F.push(
            E("rect", {
              x: dx + 9,
              y: vTop,
              width: Math.max(0, len - dx - 15),
              height: wh - 2,
              rx: 3,
              fill: winC,
            }),
          );
        } else
          F.push(E("rect", { x: 5, y: vTop, width: len - 10, height: wh - 2, rx: 3, fill: winC }));
      } else {
        const w = s.fa === "arches" ? 8 : 9;
        const n = Math.max(1, Math.floor((len - 6) / 17));
        for (let i = 0; i < n; i++) {
          const u = (len / n) * (i + 0.5);
          if (skip(u)) continue;
          F.push(
            E("rect", {
              x: u - w / 2,
              y: vTop - (s.fa === "arches" ? 1 : 0),
              width: w,
              height: wh + (s.fa === "arches" ? 1 : 0),
              rx: s.fa === "arches" ? 4 : 2.5,
              fill: winC,
            }),
          );
        }
      }
    }
    if (side === "L") {
      F.push(
        E("rect", { x: dx - 5.5, y: hb - 17, width: 11, height: 17, rx: 5, fill: c.door }),
        E("rect", { x: dx - 5.5, y: hb - 8, width: 11, height: 8, fill: c.door }),
        E("rect", { x: dx - 8, y: hb - 1.5, width: 16, height: 1.5, fill: dk(c.door, 0.2) }),
      );
    }
    return E("g", { transform: tr }, F);
  }
  function roofEl(
    kind: string,
    x0: number,
    y0: number,
    z: number,
    W: number,
    D: number,
    c: BColors,
  ): { h: number; el: El[] } {
    if (kind === "flat") {
      return {
        h: 5,
        el: [
          box(x0 - 1.5, y0 - 1.5, z, W + 3, D + 3, 5, { t: c.roofT, l: c.roof, r: c.roofR }),
          poly(
            [
              P(x0 + 4, y0 + 4, z + 5),
              P(x0 + W - 4, y0 + 4, z + 5),
              P(x0 + W - 4, y0 + D - 4, z + 5),
              P(x0 + 4, y0 + D - 4, z + 5),
            ],
            dk(c.roofT, 0.1),
          ),
        ],
      };
    }
    if (kind === "gable") {
      const rh = clamp(Math.min(W, D) * 0.42, 12, 24);
      const o = 3;
      if (W >= D) {
        const ym = y0 + D / 2;
        return {
          h: rh,
          el: [
            poly(
              [
                P(x0 - o, y0 - o, z - 2),
                P(x0 + W + o, y0 - o, z - 2),
                P(x0 + W + o, ym, z + rh),
                P(x0 - o, ym, z + rh),
              ],
              c.roofB,
            ),
            poly([P(x0 + W, y0, z), P(x0 + W, y0 + D, z), P(x0 + W, ym, z + rh)], c.wr),
            poly(
              [
                P(x0 - o, y0 + D + o, z - 2),
                P(x0 + W + o, y0 + D + o, z - 2),
                P(x0 + W + o, y0 + D + o, z - 5),
                P(x0 - o, y0 + D + o, z - 5),
              ],
              dk(c.roof, 0.32),
            ),
            poly(
              [
                P(x0 + W + o, y0 + D + o, z - 5),
                P(x0 + W + o, y0 + D + o, z - 2),
                P(x0 + W + o, ym, z + rh),
                P(x0 + W + o, ym, z + rh - 3),
              ],
              dk(c.roof, 0.4),
            ),
            poly(
              [
                P(x0 - o, y0 + D + o, z - 2),
                P(x0 + W + o, y0 + D + o, z - 2),
                P(x0 + W + o, ym, z + rh),
                P(x0 - o, ym, z + rh),
              ],
              c.roof,
            ),
            E("path", {
              d: `M${P(x0 - o, ym, z + rh).join(" ")} L${P(x0 + W + o, ym, z + rh).join(" ")}`,
              stroke: dk(c.roof, 0.3),
              strokeWidth: 2.2,
              strokeLinecap: "round",
            }),
          ],
        };
      }
      const xm = x0 + W / 2;
      return {
        h: rh,
        el: [
          poly(
            [
              P(x0 - o, y0 - o, z - 2),
              P(x0 - o, y0 + D + o, z - 2),
              P(xm, y0 + D + o, z + rh),
              P(xm, y0 - o, z + rh),
            ],
            c.roofB,
          ),
          poly([P(x0, y0 + D, z), P(x0 + W, y0 + D, z), P(xm, y0 + D, z + rh)], c.wl),
          poly(
            [
              P(x0 + W + o, y0 - o, z - 2),
              P(x0 + W + o, y0 + D + o, z - 2),
              P(x0 + W + o, y0 + D + o, z - 5),
              P(x0 + W + o, y0 - o, z - 5),
            ],
            dk(c.roof, 0.45),
          ),
          poly(
            [
              P(x0 + W + o, y0 - o, z - 2),
              P(x0 + W + o, y0 + D + o, z - 2),
              P(xm, y0 + D + o, z + rh),
              P(xm, y0 - o, z + rh),
            ],
            c.roofR,
          ),
          E("path", {
            d: `M${P(xm, y0 - o, z + rh).join(" ")} L${P(xm, y0 + D + o, z + rh).join(" ")}`,
            stroke: dk(c.roof, 0.35),
            strokeWidth: 2.2,
            strokeLinecap: "round",
          }),
        ],
      };
    }
    const r = Math.min(W, D) / 2 - 5;
    const cc = P(x0 + W / 2, y0 + D / 2, z + 4);
    const R = r * 1.2247;
    // biome-ignore lint/suspicious/noApproximativeNumericConstant: the prototype's own constant, kept bit for bit
    const ry = r * 0.7071;
    return {
      h: 4 + R,
      el: [
        box(x0 + 2, y0 + 2, z, W - 4, D - 4, 4, { t: c.roofT, l: c.roofR, r: dk(c.roofR, 0.15) }),
        E("path", {
          d: `M${cc[0]} ${cc[1] - R} A${R} ${R} 0 0 0 ${cc[0] - R} ${cc[1]} A${R} ${ry} 0 0 0 ${cc[0]} ${cc[1] + ry} Z`,
          fill: c.roof,
          stroke: c.roof,
          strokeWidth: 0.7,
        }),
        E("path", {
          d: `M${cc[0]} ${cc[1] - R} A${R} ${R} 0 0 1 ${cc[0] + R} ${cc[1]} A${R} ${ry} 0 0 1 ${cc[0]} ${cc[1] + ry} Z`,
          fill: c.roofR,
          stroke: c.roofR,
          strokeWidth: 0.7,
        }),
        E("circle", { cx: cc[0], cy: cc[1] - R - 2, r: 2.6, fill: dk(c.roof, 0.3) }),
      ],
    };
  }
  function ghost(x0: number, y0: number, z: number, W: number, D: number, H: number): El[] {
    const s = {
      fill: "rgba(255,255,255,.5)",
      stroke: K0.ink2,
      strokeWidth: 1.5,
      strokeDasharray: "5 4",
      strokeLinejoin: "round",
    };
    return [
      E("polygon", {
        points: pts([
          P(x0, y0 + D, z),
          P(x0 + W, y0 + D, z),
          P(x0 + W, y0 + D, z + H),
          P(x0, y0 + D, z + H),
        ]),
        ...s,
      }),
      E("polygon", {
        points: pts([
          P(x0 + W, y0 + D, z),
          P(x0 + W, y0, z),
          P(x0 + W, y0, z + H),
          P(x0 + W, y0 + D, z + H),
        ]),
        ...s,
      }),
      E("polygon", {
        points: pts([
          P(x0, y0, z + H),
          P(x0 + W, y0, z + H),
          P(x0 + W, y0 + D, z + H),
          P(x0, y0 + D, z + H),
        ]),
        ...s,
      }),
    ];
  }
  function crate(x: number, y: number, z: number, s: number, col?: string): El[] {
    return box(x, y, z, s, s, s * 0.85, {
      t: lt(col || K0.kraft, 0.18),
      l: col || K0.kraft,
      r: dk(col || K0.kraft, 0.2),
    });
  }
  /* s: spec, st: state, (x,y): cell origin in world units */
  function building(
    s: Spec,
    st: string,
    x: number,
    y: number,
    o0?: BuildingOpts,
  ): { el: El; top: Pt; stand: Pt; key: number; W: number; D: number; x0: number; y0: number } {
    const o = o0 || {};
    const tint = o.tint || DIST.hall;
    const c = colorsFor(tint, st);
    const W = s.fp[0] * T - 2 * INS;
    const D = s.fp[1] * T - 2 * INS;
    const x0 = x + INS;
    const y0 = y + INS;
    const H = 26 + (s.fl - 1) * 22;
    const pl = st === "planned";
    const cons = st === "construction";
    const lit = ["active", "complete", "needs"].includes(st);
    const out: El[] = [];
    let topZ = 3 + H;
    let roofH = 0;
    if (!pl)
      out.push(
        box(x0 - 2.5, y0 - 2.5, 0, W + 5, D + 5, 3, { t: K0.plinT, l: K0.plinL, r: K0.plinR }),
      );
    if (s.yard) {
      out.push(
        E("polygon", {
          points: pts([
            P(x0, y0, 3.2),
            P(x0 + W, y0, 3.2),
            P(x0 + W, y0 + D, 3.2),
            P(x0, y0 + D, 3.2),
          ]),
          fill: pl ? "rgba(255,255,255,.5)" : "url(#tiloHatch)",
          stroke: pl ? K0.ink2 : K0.scaffold,
          strokeWidth: 1.5,
          strokeDasharray: pl ? "5 4" : "none",
        }),
      );
      if (!pl) {
        for (let i = 0; i <= 4; i++) {
          const u = i / 4;
          out.push(
            box(x0 + W * u - 1.2, y0 + D - 1.2, 3, 2.4, 2.4, 9, shade(K0.scaffold)),
            box(x0 + W - 1.2, y0 + D * u - 1.2, 3, 2.4, 2.4, 9, shade(K0.scaffold)),
          );
        }
        out.push(
          E("path", {
            d: `M${P(x0, y0 + D, 10).join(" ")} L${P(x0 + W, y0 + D, 10).join(" ")} L${P(x0 + W, y0, 10).join(" ")}`,
            stroke: K0.scaffold,
            strokeWidth: 1.8,
            fill: "none",
          }),
        );
        const sh = {
          wl: lt(tint, 0.8),
          wr: dk(lt(tint, 0.8), 0.15),
          wt: lt(tint, 0.9),
          roof: tint,
          roofR: dk(tint, 0.24),
          roofT: lt(tint, 0.22),
        };
        out.push(
          box(x0 + 4, y0 + 4, 3, 26, 22, 22, { t: sh.wt, l: sh.wl, r: sh.wr }),
          box(x0 + 3, y0 + 3, 25, 28, 24, 4, { t: sh.roofT, l: sh.roof, r: sh.roofR }),
        );
        out.push(crate(x0 + W * 0.55, y0 + D * 0.45, 3, 10, lt(tint, 0.3)));
      }
      topZ = 30;
    } else if (pl) {
      out.push(ghost(x0, y0, 3, W, D, H));
    } else {
      const hb = cons ? Math.max(24, Math.round(H * 0.45)) : H;
      const fl = cons ? 1 : s.fl;
      out.push(box(x0, y0, 3, W, D, hb, { t: c.wt, l: c.wl, r: c.wr }));
      out.push(
        facade("L", x0, y0, W, D, hb, s, c, lit, fl),
        facade("R", x0, y0, W, D, hb, s, c, lit, fl),
      );
      if (cons) {
        out.push(ghost(x0, y0, 3 + hb, W, D, H - hb));
        const sc = { stroke: K0.scaffold, strokeWidth: 2.2, strokeLinecap: "round" };
        const cs: Pt[] = [
          [x0 - 3, y0 + D + 3],
          [x0 + W + 3, y0 + D + 3],
          [x0 + W + 3, y0 - 3],
          [x0 + W / 2, y0 + D + 3],
        ];
        for (const [a, b] of cs)
          out.push(
            E("path", { d: `M${P(a, b, 3).join(" ")} L${P(a, b, 3 + H).join(" ")}`, ...sc }),
          );
        for (let z = 16; z <= H; z += 16)
          out.push(
            E("path", {
              d: `M${P(x0 - 3, y0 + D + 3, 3 + z).join(" ")} L${P(x0 + W + 3, y0 + D + 3, 3 + z).join(" ")} L${P(x0 + W + 3, y0 - 3, 3 + z).join(" ")}`,
              ...sc,
              fill: "none",
            }),
          );
        topZ = 3 + H;
      } else {
        const r = roofEl(s.roof, x0, y0, 3 + H, W, D, c);
        out.push(r.el);
        roofH = r.h;
        if (s.roof === "flat" && s.fp[0] * s.fp[1] > 1)
          out.push(
            box(x0 + W - 18, y0 + 6, 3 + H + 5, 10, 8, 6, {
              t: lt(c.roofR, 0.5),
              l: lt(c.roofR, 0.3),
              r: c.roofR,
            }),
          );
        if (s.dock) {
          out.push(
            crate(x0 + W + 6, y0 + D - 26, 0, 10),
            crate(x0 + W + 6, y0 + D - 14, 0, 10),
            crate(x0 + W + 6, y0 + D - 20, 8.5, 10, K0.kraftD),
          );
        }
      }
    }
    // blade sign
    if (!pl && !s.yard) {
      const su = W < 60 ? W * 0.74 : W * 0.62;
      const sz = 3 + Math.min(H, cons ? 20 : H) - (cons ? 6 : 9);
      const sp = P(x0 + su, y0 + D + 5, sz);
      const sb = P(x0 + su, y0 + D, sz);
      const sr = W < 60 ? 7 : 8.5;
      out.push(
        E("path", {
          d: `M${sb[0]} ${sb[1]} L${sp[0]} ${sp[1]}`,
          stroke: dk(c.wl, 0.35),
          strokeWidth: 2,
        }),
        E("circle", { cx: sp[0], cy: sp[1], r: sr + 1, fill: lit ? dk(c.tint, 0.2) : c.tint }),
        E("circle", {
          cx: sp[0],
          cy: sp[1],
          r: sr,
          fill: lit ? c.tint : "#FFFFFF",
          stroke: lit ? "none" : c.tint,
          strokeWidth: 1.6,
        }),
        icon(
          s.i,
          lit ? "#FFFFFF" : dk(c.tint, 0.1),
          sp[0],
          sp[1],
          sr / 11,
          lit ? c.tint : "#FFFFFF",
        ),
      );
    }
    return {
      el: E("g", null, out),
      top: P(x0 + W / 2, y0 + D / 2, topZ + roofH + (s.roof === "dome" ? 4 : 2)),
      stand: [x0 + W * (W < 60 ? 0.3 : 0.26), y0 + D],
      key: x0 + W * 0.5 + y0 + D,
      W,
      D,
      x0,
      y0,
    };
  }

  /* ============ agents ============ */
  function agent(a: AgentSpec, x: number, y: number, o0?: AgentOpts): El {
    const o = o0 || {};
    const rank = a.rank || "specialist";
    const ex = a.expr || "neutral";
    const face = a.facing || "L";
    const col = rank === "director" ? K0.hero : ROLE[a.role as string] || K0.hero;
    const cT = lt(col, 0.2);
    const cR = dk(col, 0.22);
    const limb = dk(col, 0.3);
    const acc = dk(col, 0.52);
    const w = rank === "director" ? 15 : 13;
    const hh = ({ specialist: 15, lead: 17, director: 19 } as Record<string, number>)[
      rank
    ] as number;
    const x0 = x - w / 2;
    const y0 = y - w / 2;
    const z0 = 3;
    const jump = ex === "delighted" ? 4 : 0;
    const Z = z0 + jump;
    const out: El[] = [];
    const bk = !!a.back;
    out.push(
      E("ellipse", {
        cx: P(x, y, 0)[0],
        cy: P(x, y, 0)[1],
        rx: w * 1.05,
        ry: w * 0.6,
        fill: "rgba(31,29,43,.13)",
      }),
    );
    if (a.ring)
      out.push(
        E("ellipse", {
          cx: P(x, y, 0)[0],
          cy: P(x, y, 0)[1],
          rx: 21,
          ry: 12.1,
          fill: "none",
          stroke: K0.amber,
          strokeWidth: 2.6,
        }),
      );
    const walk = ex === "walking";
    const st = a.step ? 1 : 0;
    out.push(
      box(x0 + 2, y0 + w - 5, jump + (walk && !st ? 1.8 : 0), 4, 4, 3, {
        t: limb,
        l: limb,
        r: dk(limb, 0.2),
      }),
      box(x0 + w - 6, y0 + w - 5, jump + (walk && st ? 1.8 : 0), 4, 4, 3, {
        t: limb,
        l: limb,
        r: dk(limb, 0.2),
      }),
    );
    out.push(box(x0 + 1.2, y0 + 1.2, Z + 1, w - 2.4, w - 2.4, hh - 2, { t: cR, l: cR, r: cR }));
    out.push(
      E("rect", {
        x: 0,
        y: 0,
        width: w,
        height: hh,
        rx: 3.4,
        fill: col,
        transform: mL(x0, y0 + w, Z + hh),
      }),
      E("rect", {
        x: 0,
        y: 0,
        width: w,
        height: hh,
        rx: 3.4,
        fill: cR,
        transform: mR(x0 + w, y0 + w, Z + hh),
      }),
      E("rect", {
        x: 0,
        y: 0,
        width: w,
        height: w,
        rx: 3.4,
        fill: cT,
        transform: mT(x0, y0, Z + hh),
      }),
    );
    if (rank === "lead") out.push(box(x - 2, y - 2, Z + hh, 4, 4, 3.5, shade(col)));
    if (rank === "director") {
      const crown: [number, number][] = [
        [-6, 3.5],
        [-2, 5],
        [2, 3.5],
      ];
      for (const [i, [d, ht]] of crown.entries())
        out.push(
          box(x + d, y - 2 + (i - 1) * 0, Z + hh, 4, 4, ht, shade(i === 1 ? col : dk(col, 0.12))),
        );
    }
    // face
    const ink = K0.ink;
    const F: El[] = [];
    const cx = w / 2;
    const er = 1.05;
    const ey = 5.5;
    const ed = 2.55;
    const my = 8.1;
    const mw = 1.9;
    const sw = {
      stroke: ink,
      strokeWidth: 0.8,
      strokeLinecap: "round",
      strokeLinejoin: "round",
      fill: "none",
    };
    F.push(E("rect", { x: 1.6, y: 2.3, width: w - 3.2, height: 7.6, rx: 3.2, fill: "#FFFFFF" }));
    const eye = (u: number, sc: number): El => {
      if (ex === "delighted")
        return E("path", {
          d: `M${u - er} ${ey + 0.4} Q${u} ${ey - er * 1.9} ${u + er} ${ey + 0.4}`,
          ...sw,
          strokeWidth: 0.9,
        });
      if (ex === "focused")
        return E("rect", {
          x: u - er * 1.1,
          y: ey - 0.45,
          width: er * 2.2,
          height: 0.95,
          rx: 0.45,
          fill: ink,
        });
      return E("circle", {
        cx: u,
        cy: ey,
        r: er * (sc || 1) * (ex === "needs" ? 1.15 : 1),
        fill: ink,
      });
    };
    F.push(eye(cx - ed, ex === "puzzled" ? 1.15 : 1), eye(cx + ed, ex === "puzzled" ? 0.72 : 1));
    const b0 = ey - 2.4;
    const bw = 1.4;
    const L = (a1: number, b1: number, a2: number, b2: number): El =>
      E("path", { d: `M${a1} ${b1} L${a2} ${b2}`, ...sw, strokeWidth: 0.75 });
    if (ex === "focused")
      F.push(
        L(cx - ed - bw, b0 - 0.2, cx - ed + bw, b0 + 0.5),
        L(cx + ed + bw, b0 - 0.2, cx + ed - bw, b0 + 0.5),
      );
    if (ex === "recovering")
      F.push(
        L(cx - ed - bw, b0 - 0.7, cx - ed + bw, b0 + 0.7),
        L(cx + ed + bw, b0 - 0.7, cx + ed - bw, b0 + 0.7),
      );
    if (ex === "puzzled")
      F.push(
        E("path", {
          d: `M${cx - ed - bw} ${b0} Q${cx - ed} ${b0 - 1.6} ${cx - ed + bw} ${b0 - 0.6}`,
          ...sw,
          strokeWidth: 0.75,
        }),
        L(cx + ed - bw, b0 + 0.6, cx + ed + bw, b0 + 0.6),
      );
    const MO: Record<string, El> = {
      neutral: E("path", { d: `M${cx - mw} ${my} H${cx + mw}`, ...sw }),
      walking: E("path", {
        d: `M${cx - mw} ${my - 0.4} Q${cx} ${my + 1.2} ${cx + mw} ${my - 0.4}`,
        ...sw,
      }),
      focused: E("path", { d: `M${cx - mw * 0.55} ${my} H${cx + mw * 0.55}`, ...sw }),
      talking: E("ellipse", { cx, cy: my, rx: 1.2, ry: 1, fill: ink }),
      needs: E("circle", { cx, cy: my, r: 0.85, fill: ink }),
      puzzled: E("path", {
        d: `M${cx - mw} ${my} l${mw / 2} -.7 l${mw / 2} .7 l${mw / 2} -.7 l${mw / 2} .7`,
        ...sw,
      }),
      recovering: E("path", {
        d: `M${cx - mw} ${my + 0.3} L${cx + mw} ${my - 0.4}`,
        ...sw,
        strokeWidth: 0.95,
      }),
      delighted: E("path", {
        d: `M${cx - mw - 0.4} ${my - 1} Q${cx} ${my + 2.4} ${cx + mw + 0.4} ${my - 1} Z`,
        fill: ink,
        stroke: ink,
        strokeWidth: 0.5,
        strokeLinejoin: "round",
      }),
    };
    F.push(MO[ex] || MO.neutral);
    if (ex === "sleepy") {
      F.splice(
        1,
        2,
        E("path", {
          d: `M${cx - ed - er} ${ey} Q${cx - ed} ${ey + 1.3} ${cx - ed + er} ${ey}`,
          ...sw,
        }),
        E("path", {
          d: `M${cx + ed - er} ${ey} Q${cx + ed} ${ey + 1.3} ${cx + ed + er} ${ey}`,
          ...sw,
        }),
      );
      F[F.length - 1] = E("circle", { cx, cy: my, r: 0.6, fill: ink });
    }
    if (ex === "delighted")
      F.push(
        E("circle", { cx: cx - ed * 1.75, cy: my - 0.4, r: 0.9, fill: lt(col, 0.55) }),
        E("circle", { cx: cx + ed * 1.75, cy: my - 0.4, r: 0.9, fill: lt(col, 0.55) }),
      );
    if (a.role === "builder" && rank !== "director") {
      out.push(
        E("rect", {
          x: 0,
          y: hh - 5.2,
          width: w,
          height: 2.4,
          fill: acc,
          transform: mL(x0, y0 + w, Z + hh),
        }),
        E("rect", {
          x: 0,
          y: hh - 5.2,
          width: w,
          height: 2.4,
          fill: dk(acc, 0.2),
          transform: mR(x0 + w, y0 + w, Z + hh),
        }),
      );
    }
    if (a.role === "connector" && rank !== "director")
      F.push(
        E("rect", {
          x: w - 5.2,
          y: hh - 5.8,
          width: 3.6,
          height: 4.4,
          rx: 0.8,
          fill: "#FFFFFF",
          stroke: acc,
          strokeWidth: 0.7,
        }),
      );
    const fT = face === "L" ? mL(x0, y0 + w, Z + hh) : mR(x0 + w, y0 + w, Z + hh);
    if (!bk) out.push(E("g", { transform: fT }, F));
    if (bk || a.pack)
      out.push(
        E("rect", {
          x: 2.2,
          y: 3,
          width: w - 4.4,
          height: hh - 7.5,
          rx: 2.2,
          fill: a.pack ? K0.hero : dk(col, 0.38),
          transform: bk ? fT : face === "L" ? mR(x0 + w, y0 + w, Z + hh) : mL(x0, y0 + w, Z + hh),
          opacity: bk ? 1 : 0.95,
        }),
      );
    // arms (billboard)
    const arms: Record<string, [number, number]> = {
      sleepy: [5, -5],
      neutral: [12, -12],
      walking: a.step ? [-26, 22] : [30, -8],
      focused: [-34, 34],
      talking: [12, -78],
      needs: [12, -170],
      puzzled: [40, -12],
      recovering: [12, -130],
      delighted: [150, -150],
    };
    const A: [number, number] = arms[ex] || [12, -12];
    const sL = P(x0, y0 + w, Z + hh * 0.56);
    const sR = P(x0 + w, y0, Z + hh * 0.56);
    const al = ex === "needs" ? 9.5 : 7.5;
    const aw = 3.4;
    const arm = (s: Pt, an: number): El =>
      E("rect", {
        x: s[0] - aw / 2,
        y: s[1] - aw / 2,
        width: aw,
        height: al + aw / 2,
        rx: aw / 2,
        fill: limb,
        transform: `rotate(${an} ${s[0]} ${s[1]})`,
      });
    const hand = (s: Pt, an: number): Pt => {
      const r = (an * Math.PI) / 180;
      return [s[0] - al * Math.sin(r), s[1] + al * Math.cos(r)];
    };
    out.push(arm(sL, A[0]), arm(sR, A[1]));
    const lh = hand(sL, A[0]);
    const rh = hand(sR, A[1]);
    if (a.role === "research" && rank !== "director")
      out.push(
        E("circle", {
          cx: lh[0] - 1,
          cy: lh[1] + 1,
          r: 2.7,
          fill: "#FFFFFF",
          stroke: acc,
          strokeWidth: 1.2,
        }),
        E("path", {
          d: `M${lh[0] + 0.8} ${lh[1] + 3} L${lh[0] + 2.8} ${lh[1] + 5.4}`,
          stroke: acc,
          strokeWidth: 1.6,
          strokeLinecap: "round",
        }),
      );
    if (a.role === "tester" && rank !== "director")
      out.push(
        E("rect", {
          x: lh[0] - 3,
          y: lh[1] - 1.5,
          width: 5.4,
          height: 7,
          rx: 1,
          fill: "#FFFFFF",
          stroke: acc,
          strokeWidth: 0.9,
        }),
        E("rect", { x: lh[0] - 1.3, y: lh[1] - 2.4, width: 2, height: 1.6, rx: 0.6, fill: acc }),
      );
    if (a.role === "browser" && rank !== "director") {
      const t1 = P(x0, y0 + w, Z + hh - 2);
      const t2 = P(x0 + w, y0, Z + hh - 2);
      const tp = P(x0 + w / 2, y0 + w / 2, Z + hh + 6);
      out.push(
        E("path", {
          d: `M${t1[0]} ${t1[1]} Q${tp[0]} ${tp[1] - 3} ${t2[0]} ${t2[1]}`,
          stroke: acc,
          strokeWidth: 1.5,
          fill: "none",
        }),
        E("circle", { cx: t1[0], cy: t1[1], r: 1.9, fill: acc }),
        E("circle", { cx: t2[0], cy: t2[1], r: 1.9, fill: acc }),
      );
    }
    if (a.role === "delivery" && rank !== "director")
      out.push(box(x0 + w, y0 + 2, Z + 2, 2.5, 6, 5.5, shade(dk(col, 0.35))));
    if (ex === "talking" || a.parcel) {
      const p = a.parcel ? lh : rh;
      out.push(
        E("rect", {
          x: p[0] - 1,
          y: p[1] - 4,
          width: 6,
          height: 5,
          rx: 1,
          fill: K0.kraft,
          stroke: K0.kraftD,
          strokeWidth: 0.8,
        }),
      );
    }
    const gp = P(x, y, 0);
    // motion: restored in WEB-3 (BQ-WEB-3)
    const tilt = ex === "puzzled" ? ` rotate(-6 ${gp[0]} ${gp[1]})` : "";
    return E(
      "g",
      {
        transform: `translate(${gp[0]} ${gp[1]}) scale(${o.scale || AS}) translate(${-gp[0]} ${-gp[1]})${tilt}`,
      },
      out,
    );
  }

  /* ============ road pieces ============ */
  function gate(x: number, y: number, st?: string): { el: El; top: Pt; key: number } {
    const col = st === "open" ? K0.ok : st === "waiting" ? K0.amber : K0.grey;
    const post = { t: lt(K0.ink2, 0.5), l: lt(K0.ink2, 0.25), r: K0.ink2 };
    const out: El[] = [
      box(x - 17, y - 2, 0, 4, 4, 20, post),
      box(x + 13, y - 2, 0, 4, 4, 20, post),
    ];
    if (st === "open")
      out.push(box(x - 16, y - 1, 20, 2, 2, 22, { t: "#FFFFFF", l: "#FFFFFF", r: lt(col, 0.4) }));
    else
      out.push(
        box(x - 15, y - 1, 13, 28, 2, 3.5, { t: "#FFFFFF", l: "#FFFFFF", r: "#E3E0D8" }),
        E("rect", {
          x: 0,
          y: 0,
          width: 28,
          height: 3.5,
          fill: "none",
          stroke: col,
          strokeWidth: 0.9,
          strokeDasharray: "4 3",
          transform: mL(x - 15, y + 1, 16.5),
        }),
      );
    return { el: E("g", null, out), top: P(x, y, 26), key: x + y };
  }
  function clouds(bx: number, by: number, bw: number, bd: number, seed?: number): El {
    const r = rng(seed || 7);
    const out: { k: number; el: El }[] = [];
    const nx = Math.max(2, Math.round(bw / 34));
    const ny = Math.max(2, Math.round(bd / 34));
    for (let j = 0; j < ny; j++)
      for (let i = 0; i < nx; i++) {
        const px = bx + (bw * (i + 0.5)) / nx + (r() - 0.5) * 8;
        const py = by + (bd * (j + 0.5)) / ny + (r() - 0.5) * 8;
        const p = P(px, py, 34 + r() * 10);
        const rr = 19 + r() * 8;
        out.push({
          k: px + py,
          el: E(
            "g",
            null,
            E("circle", { cx: p[0], cy: p[1] + 4, r: rr, fill: K0.cloudD }),
            E("circle", { cx: p[0], cy: p[1], r: rr, fill: K0.cloud }),
          ),
        });
      }
    out.sort((a, b) => a.k - b.k);
    return E(
      "g",
      null,
      out.map((o) => o.el),
    );
  }

  /* ============ props ============ */
  const TREE = "#A3B89D";
  const TREED = "#7E9878";
  const TRUNK = "#9A8566";
  function tree(x: number, y: number, r: number, kind?: string): El {
    const out: El[] = [box(x - 1.6, y - 1.6, 0, 3.2, 3.2, 6, shade(TRUNK))];
    if (kind === "pine") {
      const b = P(x, y, 5);
      const tp = P(x, y, 5 + r * 2.7);
      const w = r * 1.25;
      out.push(
        E("path", {
          d: `M${b[0] - w} ${b[1]} L${tp[0]} ${tp[1]} L${b[0]} ${b[1] + w * 0.42} Z`,
          fill: TREE,
        }),
        E("path", {
          d: `M${b[0] + w} ${b[1]} L${tp[0]} ${tp[1]} L${b[0]} ${b[1] + w * 0.42} Z`,
          fill: TREED,
        }),
      );
    } else {
      const c = P(x, y, 6 + r);
      const Rr = r * 1.2247;
      out.push(
        E("path", {
          d: `M${c[0]} ${c[1] - Rr} A${Rr} ${Rr} 0 0 0 ${c[0]} ${c[1] + Rr} Z`,
          fill: TREE,
        }),
        E("path", {
          d: `M${c[0]} ${c[1] - Rr} A${Rr} ${Rr} 0 0 1 ${c[0]} ${c[1] + Rr} Z`,
          fill: TREED,
        }),
      );
    }
    return E("g", null, out);
  }
  function presence(p: Pt, initials: string, col?: string): El {
    return E(
      "g",
      null,
      E("circle", { cx: p[0], cy: p[1], r: 12.5, fill: "#FFFFFF" }),
      E("circle", { cx: p[0], cy: p[1], r: 10.5, fill: col || K0.ink2 }),
      E(
        "text",
        {
          x: p[0],
          y: p[1] + 3.6,
          textAnchor: "middle",
          fontFamily: K0.body,
          fontSize: 9.5,
          fontWeight: 800,
          fill: "#FFFFFF",
        },
        initials,
      ),
    );
  }
  function comment(p: Pt, n: number | string): El {
    return E(
      "g",
      null,
      E("path", {
        d: `M${p[0] - 11} ${p[1] - 9} h22 a4 4 0 0 1 4 4 v10 a4 4 0 0 1 -4 4 h-12 l-5 5 v-5 h-5 a4 4 0 0 1 -4 -4 v-10 a4 4 0 0 1 4 -4 z`,
        fill: "#FFFFFF",
        stroke: K0.ink,
        strokeWidth: 1.6,
        strokeLinejoin: "round",
      }),
      E(
        "text",
        {
          x: p[0],
          y: p[1] + 4,
          textAnchor: "middle",
          fontFamily: K0.body,
          fontSize: 10.5,
          fontWeight: 800,
          fill: K0.ink,
        },
        String(n),
      ),
    );
  }

  /* ============ generator ============ */
  function specOf(b: PlanBuilding, seed: number): Spec {
    if (b.kit) {
      const s = { ...KIT[b.kit] } as Spec;
      if (b.name) s.n = b.name;
      if (b.fl) s.fl = b.fl;
      return s;
    }
    const g = b.gen as GenSpec;
    const r = rng(hash(g.name) + seed * 7919);
    const fp: [number, number] = g.fp || [r() < 0.5 ? 1 : 2, 1];
    return {
      n: g.name,
      fp,
      fl: g.fl || 1 + Math.floor(r() * (fp[0] * fp[1] > 1 ? 2 : 3)),
      roof: g.roof || (["flat", "gable", "dome"][Math.floor(r() * 3)] as string),
      fa: g.fa || (["windows", "band", "arches"][Math.floor(r() * 3)] as string),
      i: g.i || "dot",
      gen: true,
    };
  }
  function layout(plan: Plan, seed: number): Layout {
    const blocks: Block[] = plan.districts.map((d) => {
      const tint = DIST[d.tint || d.id] || DIST.hall;
      const bs = d.buildings.map((b) => ({ ...b, s: specOf(b, seed) }) as LBuilding);
      const rows: LBuilding[][] = [[]];
      let ws = 0;
      const maxRow = 6 * T;
      for (const b of bs) {
        const fw = b.s.fp[0] * T;
        if (ws + fw > maxRow && (rows[rows.length - 1] as LBuilding[]).length) {
          rows.push([]);
          ws = 0;
        }
        (rows[rows.length - 1] as LBuilding[]).push(b);
        ws += fw + GAP;
      }
      const rw = rows.map((r) => r.reduce((a, b) => a + b.s.fp[0] * T, 0) + GAP * (r.length - 1));
      const rd = rows.map((r) => Math.max(...r.map((b) => b.s.fp[1] * T)));
      return {
        d,
        tint,
        rows,
        rw,
        rd,
        w: Math.max(...rw) + PAD * 2,
        h0: PAD + rd.reduce((a, b) => a + b + LANE, 0),
      } as Block;
    });
    const hall = blocks.filter((b) => b.d.hall);
    const rest = blocks.filter((b) => !b.d.hall);
    const n = blocks.length;
    const cols = n <= 2 ? n : n <= 4 ? 2 : 3;
    const order = [...rest];
    order.splice(Math.min(order.length, cols === 3 ? 1 : 0), 0, ...hall);
    const grid: Block[][] = [];
    for (let i = 0; i < order.length; i += cols) grid.push(order.slice(i, i + cols));
    const rowW = grid.map((r) => r.reduce((a, b) => a + b.w, 0) + G * (r.length - 1));
    const maxW = Math.max(...rowW);
    const bmap: Record<string, LBuilding> = {};
    const vseg: [number, number, number][] = [];
    let y = G;
    for (const [ri, row] of grid.entries()) {
      const extra = (maxW - (rowW[ri] as number)) / row.length;
      const rD = Math.max(...row.map((b) => b.h0));
      let x = G;
      for (const [ci, b] of row.entries()) {
        b.w += extra;
        b.x = x;
        b.y = y;
        b.h = rD;
        b.frontRoad = y + rD + G / 2;
        b.leftRoad = x - G / 2;
        b.lanes = [];
        let ry = b.y + PAD + (rD - b.h0);
        for (const [i, r] of b.rows.entries()) {
          let rx = b.x + PAD + (b.w - 2 * PAD - (b.rw[i] as number)) / 2;
          for (const bb of r) {
            bb.cx = rx;
            bb.cy = ry + (b.rd[i] as number) - bb.s.fp[1] * T;
            bb.block = b;
            bb.front = i === b.rows.length - 1;
            bb.laneY = ry + (b.rd[i] as number) + LANE / 2;
            rx += bb.s.fp[0] * T + GAP;
            if (bb.id) bmap[bb.id] = bb;
          }
          b.lanes.push([ry + (b.rd[i] as number), LANE]);
          ry += (b.rd[i] as number) + LANE;
        }
        b.trees = [];
        const back = rD - b.h0;
        if (back >= 26)
          for (let tx = b.x + 18; tx < b.x + b.w - 12; tx += 30)
            b.trees.push([tx, b.y + back / 2 + 2]);
        let ry2 = b.y + PAD + back;
        for (const [i, _r] of b.rows.entries()) {
          const side = (b.w - 2 * PAD - (b.rw[i] as number)) / 2;
          if (side >= 24) {
            const yy = ry2 + (b.rd[i] as number) * 0.55;
            for (let tx = b.x + PAD + 10; tx < b.x + PAD + side - 8; tx += 24)
              b.trees.push([tx, yy]);
            for (let tx = b.x + b.w - PAD - 10; tx > b.x + b.w - PAD - side + 8; tx -= 24)
              b.trees.push([tx, yy]);
          }
          ry2 += (b.rd[i] as number) + LANE;
        }
        if (ci > 0) vseg.push([x - G, y, y + rD]);
        x += b.w + G;
      }
      y += rD + G;
    }
    const Wt = maxW + 2 * G;
    const Dt = y;
    const hg = [0, ...grid.map((r) => (r[0] as Block).y + (r[0] as Block).h)];
    return { blocks, bmap, Wt, Dt, hg, vseg, ring: [G / 2, Wt - G / 2] };
  }
  function standOf(bb: LBuilding): Pt {
    const W = bb.s.fp[0] * T - 2 * INS;
    return [bb.cx + INS + W * (W < 60 ? 0.3 : 0.26), bb.laneY];
  }
  function route(L: Layout, a: string, b: string): Pt[] | null {
    const A = L.bmap[a];
    const B = L.bmap[b];
    if (!A || !B) return null;
    const sa = standOf(A);
    const sb = standOf(B);
    const pts: Pt[] = [sa];
    if (A.block === B.block && A.laneY === B.laneY) {
      pts.push(sb);
      return pts;
    }
    const exit = (bb: LBuilding, s: Pt): Pt[] =>
      bb.front
        ? [[s[0], bb.block.frontRoad]]
        : [
            [bb.block.leftRoad, s[1]],
            [bb.block.leftRoad, bb.block.frontRoad],
          ];
    const ea = exit(A, sa);
    const eb = exit(B, sb).reverse();
    pts.push(...ea);
    const ya = (ea[ea.length - 1] as Pt)[1];
    const yb = (eb[0] as Pt)[1];
    if (Math.abs(ya - yb) > 1) {
      const mid = ((ea[ea.length - 1] as Pt)[0] + (eb[0] as Pt)[0]) / 2;
      const gx = L.ring.reduce(
        (best, v) => (Math.abs(v - mid) < Math.abs(best - mid) ? v : best),
        L.ring[0],
      );
      pts.push([gx, ya], [gx, yb]);
    }
    pts.push(...eb, sb);
    return pts;
  }
  function along(pts: Pt[], t: number): { p: Pt; dir: string } {
    let tot = 0;
    const seg: number[] = [];
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1] as Pt;
      const b = pts[i] as Pt;
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
      seg.push(l);
      tot += l;
    }
    let d = t * tot;
    for (let i = 0; i < seg.length; i++) {
      const sl = seg[i] as number;
      if (d <= sl) {
        const f = sl ? d / sl : 0;
        const a = pts[i] as Pt;
        const b = pts[i + 1] as Pt;
        return {
          p: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f],
          dir: Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1]) ? "x" : "y",
        };
      }
      d -= sl;
    }
    return { p: pts[pts.length - 1] as Pt, dir: "x" };
  }

  function world(plan: Plan, o: WorldOpts & { parts: true }): WorldParts;
  function world(plan: Plan, o?: WorldOpts): El;
  function world(plan: Plan, o0?: WorldOpts): El | WorldParts {
    const o = Object.assign(
      { seed: 1, labels: true, stage: 4, anim: true, tags: true },
      o0 || ({} as WorldOpts),
    );
    LS = o.ls || 1;
    const hid = (b: Block): boolean => !!(o.dvis && !o.dvis.has(b.d.id));
    const bh = (bb: LBuilding): boolean => !!(o.bvis && !o.bvis.has(bb.id as string));
    const L = layout(plan, o.seed);
    const M = 0.8 * T;
    const st = o.stage;
    const tr = rng(o.seed * 31 + 7);
    const ground: El[] = [];
    const objs: { k: number; el: El }[] = [];
    const top: El[] = [];
    ground.push(
      box(-M, -M, -26, L.Wt + 2 * M, L.Dt + 2 * M, 6, {
        t: K0.gR,
        l: dk(K0.gL, 0.12),
        r: dk(K0.gR, 0.14),
      }).slice(0, 2),
    );
    ground.push(box(-M, -M, -20, L.Wt + 2 * M, L.Dt + 2 * M, 20, { t: K0.gT, l: K0.gL, r: K0.gR }));
    for (const x of [0, L.Wt - G])
      ground.push(
        poly([P(x, 0, 0.2), P(x + G, 0, 0.2), P(x + G, L.Dt, 0.2), P(x, L.Dt, 0.2)], K0.road),
      );
    for (const [x, y0, y1] of L.vseg)
      ground.push(
        poly([P(x, y0, 0.2), P(x + G, y0, 0.2), P(x + G, y1, 0.2), P(x, y1, 0.2)], K0.road),
      );
    for (const y of L.hg)
      ground.push(
        poly([P(0, y, 0.2), P(L.Wt, y, 0.2), P(L.Wt, y + G, 0.2), P(0, y + G, 0.2)], K0.road),
      );
    if (st >= 2)
      for (const b of L.blocks) {
        if (hid(b)) continue;
        ground.push(
          box(b.x, b.y, 0, b.w, b.h, 3, {
            t: lt(b.tint, 0.86),
            l: lt(b.tint, 0.6),
            r: lt(b.tint, 0.48),
          }),
        );
        for (const [ly, lh] of b.lanes)
          ground.push(
            poly(
              [
                P(b.x + 6, ly + 6, 3.1),
                P(b.x + b.w - 6, ly + 6, 3.1),
                P(b.x + b.w - 6, ly + lh - 6, 3.1),
                P(b.x + 6, ly + lh - 6, 3.1),
              ],
              lt(b.tint, 0.93),
            ),
          );
      }
    const line = (p: Pt[], z: number): string =>
      p
        .map(
          (q, i) =>
            (i ? "L" : "M") +
            P(q[0], q[1], z)
              .map((v) => v.toFixed(1))
              .join(" "),
        )
        .join(" ");
    const routes: Record<string, PlanRoute & { p: Pt[] }> = {};
    for (const r of plan.routes || []) {
      const p = route(L, r.from, r.to);
      if (p) routes[r.id || `${r.from}-${r.to}`] = { ...r, p };
    }
    if (st >= 4)
      for (const r of Object.values(routes)) {
        // motion: restored in WEB-3 (BQ-WEB-3)
        if (r.kind === "memory") {
          ground.push(
            E("path", {
              d: line(r.p, 3.3),
              stroke: lt(K0.hero, 0.62),
              strokeWidth: 9,
              fill: "none",
              strokeLinecap: "round",
              strokeLinejoin: "round",
            }),
            E("path", {
              d: line(r.p, 3.3),
              stroke: K0.hero,
              strokeWidth: 3,
              fill: "none",
              strokeDasharray: "9 7",
              strokeLinecap: "round",
              strokeLinejoin: "round",
            }),
          );
        } else
          ground.push(
            E("path", {
              d: line(r.p, 3.3),
              stroke: K0.dash,
              strokeWidth: 2.6,
              fill: "none",
              strokeDasharray: "7 7",
              strokeLinecap: "round",
              strokeLinejoin: "round",
            }),
          );
      }
    const agPos: { a: PlanAgent; x: number; y: number; fa: string | undefined }[] = [];
    if (st >= 4)
      for (const a of plan.agents || []) {
        let x: number;
        let y: number;
        let fa = a.facing;
        const rt = a.route ? routes[a.route] : undefined;
        if (a.route && rt) {
          const q = along(rt.p, a.t == null ? 0.5 : a.t);
          x = q.p[0];
          y = q.p[1];
          fa = fa || (q.dir === "x" ? "L" : "R");
        } else {
          const bb = L.bmap[a.at as string];
          if (!bb) continue;
          const s = standOf(bb);
          x = s[0] + (a.dx || 0);
          y = s[1] + (a.dy || 0);
        }
        agPos.push({ a, x, y, fa });
      }
    const occ: Box4[] = agPos.map((q) => {
      const p = P(q.x, q.y, 0);
      return [p[0] - 13 * AS, p[1] - 36 * AS, p[0] + 13 * AS, p[1] + 6];
    });
    const hit = (r: Box4, list: Box4[]): boolean =>
      list.some((t) => r[0] < t[2] && r[2] > t[0] && r[1] < t[3] && r[3] > t[1]);
    const tagRects: Box4[] = [];
    const tagEls: El[] = [];
    if (o.tags && st >= 2)
      for (const b of L.blocks) {
        if (hid(b)) continue;
        const tfs = 11.5 * LS;
        const w = b.d.name.length * tfs * 0.58 + 30 * LS;
        const cands: Pt[] = [
          P(b.x - G * 0.5, b.y + b.h * 0.55, 0.3),
          P(b.x - G * 0.5, b.y + b.h * 0.2, 0.3),
          P(b.x - G * 0.5, b.y + b.h * 0.85, 0.3),
          P(b.x + PAD * 0.6, b.y + b.h + G * 0.45, 0.3),
          P(b.x + b.w * 0.5, b.y + b.h + G * 0.45, 0.3),
          P(b.x + b.w * 0.5, b.y - G * 0.5, 0.3),
        ];
        let p = cands[0] as Pt;
        for (const c of cands) {
          const r: Box4 = [c[0] - w / 2 - 4, c[1] - 14, c[0] + w / 2 + 4, c[1] + 14];
          if (!hit(r, occ) && !hit(r, tagRects)) {
            p = c;
            break;
          }
        }
        tagRects.push([p[0] - w / 2 - 4, p[1] - 14, p[0] + w / 2 + 4, p[1] + 14]);
        tagEls.push(tag(b.d.name, p, dk(b.tint, 0.28), b.d.icon, { fs: tfs }));
      }
    const placeLabel = (text: string, p: Pt): El => {
      const w = text.length * 10.5 * LS * 0.56 + 14 * LS;
      const hh = 11 * LS;
      let y = p[1];
      for (let i = 0; i < 4; i++) {
        const r: Box4 = [p[0] - w / 2, y - hh, p[0] + w / 2, y + hh];
        if (!tagRects.some((t) => r[0] < t[2] && r[2] > t[0] && r[1] < t[3] && r[3] > t[1])) break;
        y -= hh * 2;
      }
      tagRects.push([p[0] - w / 2, y - hh, p[0] + w / 2, y + hh]);
      return label(text, [p[0], y]);
    };
    for (const b of L.blocks) {
      if (hid(b)) continue;
      for (const bb of b.rows.flat()) {
        if (bh(bb)) continue;
        const state = st <= 2 ? "planned" : bb.state || "idle";
        const r = building(bb.s, state, bb.cx, bb.cy, { tint: b.tint });
        objs.push({ k: r.key, el: r.el });
        if (st >= 4 && !b.d.locked) {
          const pk = ["complete", "needs", "blocked", "skipped"].includes(state)
            ? state
            : state === "active" && bb.event
              ? "active"
              : null;
          // motion: restored in WEB-3 (BQ-WEB-3)
          if (pk) top.push(pin(pk, r.top, { icon: bb.event, tint: b.tint, count: bb.count }));
          if (o.labels) top.push(placeLabel(bb.s.n, [r.top[0], r.top[1] + (pk ? -50 : -12)]));
        }
      }
    }
    if (st >= 3)
      for (const gt of plan.gates || []) {
        const bb = L.bmap[gt.before];
        if (!bb || bh(bb) || hid(bb.block)) continue;
        const s = standOf(bb);
        const g = gate(s[0] + 20, s[1], gt.state || "closed");
        objs.push({ k: g.key + 2, el: g.el });
        if (st >= 4)
          top.push(
            pin(
              gt.state === "waiting" ? "needs" : gt.state === "open" ? "complete" : "lock",
              g.top,
              {
                lift: 16,
                r: 9,
              },
            ),
          );
      }
    for (const { a, x, y, fa } of agPos) {
      // motion: restored in WEB-3 (BQ-WEB-3)
      objs.push({ k: x + y + 0.5, el: agent({ ...a, facing: fa || "L" }, x, y) });
    }
    if (st >= 3) {
      for (const b of L.blocks) {
        if (b.d.locked || hid(b)) continue;
        for (const [x, y] of b.trees || [])
          objs.push({ k: x + y - 4, el: tree(x, y, 6 + tr() * 3, tr() < 0.35 ? "pine" : "round") });
      }
      const edge: Pt[] = [];
      for (let x = 12; x < L.Wt; x += 40 + tr() * 14) edge.push([x, L.Dt + M * 0.5], [x, -M * 0.5]);
      for (let y = 12; y < L.Dt; y += 40 + tr() * 14) edge.push([L.Wt + M * 0.5, y], [-M * 0.5, y]);
      for (const [x, y] of edge) {
        if (tr() < 0.8)
          objs.push({
            k: x + y - 4,
            el: tree(x, y, 6.5 + tr() * 3.5, tr() < 0.4 ? "pine" : "round"),
          });
      }
    }
    objs.sort((a, b) => a.k - b.k);
    const cover: El[] = [];
    if (st >= 2)
      for (const b of L.blocks) {
        if (b.d.locked && !hid(b)) {
          cover.push(clouds(b.x, b.y, b.w, b.h, hash(b.d.id)));
          const c = P(b.x + b.w / 2, b.y + b.h / 2, 48);
          top.push(pin("lock", [c[0], c[1] + 18], { lift: 0, r: 13 }));
        }
      }
    top.push(...tagEls);
    if (st >= 4) {
      for (const q of plan.presence || []) {
        const bb = L.bmap[q.at];
        if (!bb) continue;
        const W0 = bb.s.fp[0] * T;
        let p = P(bb.cx + W0 - 8, bb.cy + 8, 40 + bb.s.fl * 22);
        for (let n = 0; n < 6 && hit([p[0] - 14, p[1] - 14, p[0] + 14, p[1] + 14], tagRects); n++)
          p = [p[0] + 18, p[1] - 10];
        tagRects.push([p[0] - 14, p[1] - 14, p[0] + 14, p[1] + 14]);
        top.push(presence(p, q.initials, q.color));
      }
      for (const q of plan.comments || []) {
        const bb = L.bmap[q.at];
        if (!bb) continue;
        let p = P(bb.cx + 8, bb.cy + 8, 36 + bb.s.fl * 22);
        for (let n = 0; n < 6 && hit([p[0] - 16, p[1] - 12, p[0] + 16, p[1] + 16], tagRects); n++)
          p = [p[0] - 18, p[1] - 10];
        tagRects.push([p[0] - 16, p[1] - 12, p[0] + 16, p[1] + 16]);
        top.push(comment(p, q.n));
      }
    }
    const cs = [P(-M, -M, 0), P(L.Wt + M, -M, 0), P(L.Wt + M, L.Dt + M, 0), P(-M, L.Dt + M, 0)];
    const minX = Math.min(...cs.map((c) => c[0])) - 16;
    const maxX = Math.max(...cs.map((c) => c[0])) + 16;
    const minY = Math.min(...cs.map((c) => c[1])) - 120;
    const maxY = Math.max(...cs.map((c) => c[1])) + 40;
    if (o.parts) return { ground, objs, cover, top, L, M, bb: [minX, maxX, minY, maxY] };
    const defs = E(
      "defs",
      null,
      E(
        "pattern",
        {
          id: "tiloHatch",
          width: 8,
          height: 8,
          patternUnits: "userSpaceOnUse",
          patternTransform: "rotate(30)",
        },
        E("rect", { width: 8, height: 8, fill: "#F4EFE2" }),
        E("rect", { width: 3, height: 8, fill: "#E4D9BE" }),
      ),
    );
    return E(
      "svg",
      {
        viewBox: `${minX.toFixed(0)} ${minY.toFixed(0)} ${(maxX - minX).toFixed(0)} ${(maxY - minY).toFixed(0)}`,
        width: o.width || "100%",
        height: o.height || "100%",
        preserveAspectRatio: "xMidYMid meet",
        style: { display: "block" },
      },
      defs,
      ground,
      objs.map((q) => q.el),
      cover,
      top,
    );
  }

  /* ============ solo renders for sheets ============ */
  function soloBuilding(spec: string | Spec, state: string, o0?: SoloBuildingOpts): El {
    const o = o0 || {};
    const s = typeof spec === "string" ? ({ ...KIT[spec] } as Spec) : spec;
    const tint = o.tint || DIST[o.d || "hall"];
    const r = building(s, state, 0, 0, { tint });
    const W = s.fp[0] * T;
    const D = s.fp[1] * T;
    const cs = [P(0, 0, 0), P(W, 0, 0), P(W, D, 0), P(0, D, 0)];
    const minX = Math.min(...cs.map((c) => c[0])) - 22;
    const maxX = Math.max(...cs.map((c) => c[0])) + 36;
    const minY = r.top[1] - (o.pin ? 46 : 18);
    const maxY = Math.max(...cs.map((c) => c[1])) + 12;
    const extra: El[] = [];
    if (o.pin) extra.push(pin(state === "active" ? "active" : state, r.top, { icon: s.i, tint }));
    if (o.cloud)
      extra.push(
        clouds(0, 0, W, D, 3),
        pin("lock", [P(W / 2, D / 2, 48)[0], P(W / 2, D / 2, 48)[1] + 18], { lift: 0, r: 12 }),
      );
    const hh = o.height || 150;
    const ww = (hh * (maxX - minX)) / (maxY - minY);
    return E(
      "svg",
      {
        viewBox: `${minX} ${minY} ${maxX - minX} ${maxY - minY}`,
        width: ww,
        height: hh,
        style: { display: "block" },
      },
      E(
        "defs",
        null,
        E(
          "pattern",
          {
            id: "tiloHatch",
            width: 8,
            height: 8,
            patternUnits: "userSpaceOnUse",
            patternTransform: "rotate(30)",
          },
          E("rect", { width: 8, height: 8, fill: "#F4EFE2" }),
          E("rect", { width: 3, height: 8, fill: "#E4D9BE" }),
        ),
      ),
      r.el,
      extra,
    );
  }
  function soloAgent(a: AgentSpec, size0?: number): El {
    const p = P(0, 0, 0);
    const size = size0 || 90;
    return E(
      "svg",
      {
        viewBox: `${p[0] - 26} ${p[1] - 44} 52 54`,
        width: (size * 52) / 54,
        height: size,
        style: { display: "block" },
      },
      agent(a, 0, 0, { scale: 1 }),
    );
  }
  function soloPiece(kind: string, size?: number): El {
    const out: El[] = [];
    let vb: number[] | undefined;
    const plate = (w: number, d: number): El[] =>
      box(-w / 2, -d / 2, -6, w, d, 6, { t: K0.gT, l: K0.gL, r: K0.gR });
    if (kind === "plot") {
      out.push(
        plate(130, 90),
        box(-55, -35, 0, 110, 70, 3, {
          t: lt(DIST.research, 0.86),
          l: lt(DIST.research, 0.6),
          r: lt(DIST.research, 0.48),
        }),
        poly(
          [P(-49, 10, 3.1), P(49, 10, 3.1), P(49, 29, 3.1), P(-49, 29, 3.1)],
          lt(DIST.research, 0.93),
        ),
      );
      vb = [-100, -80, 200, 150];
    }
    if (kind === "road") {
      out.push(
        plate(130, 90),
        poly([P(-65, -20, 0.2), P(65, -20, 0.2), P(65, 20, 0.2), P(-65, 20, 0.2)], K0.road),
        poly([P(-20, -45, 0.2), P(20, -45, 0.2), P(20, 45, 0.2), P(-20, 45, 0.2)], K0.road),
      );
      vb = [-100, -80, 200, 150];
    }
    if (kind === "walk" || kind === "memory") {
      out.push(
        plate(130, 90),
        poly([P(-65, -20, 0.2), P(65, -20, 0.2), P(65, 20, 0.2), P(-65, 20, 0.2)], K0.road),
      );
      const d = `M${P(-58, 0, 0.5).join(" ")} L${P(58, 0, 0.5).join(" ")}`;
      if (kind === "memory")
        out.push(
          E("path", { d, stroke: lt(K0.hero, 0.62), strokeWidth: 9, strokeLinecap: "round" }),
        );
      out.push(
        E("path", {
          d,
          stroke: kind === "memory" ? K0.hero : K0.dash,
          strokeWidth: kind === "memory" ? 3 : 2.6,
          strokeDasharray: kind === "memory" ? "9 7" : "7 7",
          strokeLinecap: "round",
        }),
      );
      if (kind === "walk")
        out.push(agent({ role: "research", expr: "walking", facing: "L" }, 10, 0, { scale: 1.6 }));
      vb = [-100, -80, 200, 150];
    }
    if (kind === "handoff") {
      out.push(
        plate(130, 90),
        poly([P(-65, -20, 0.2), P(65, -20, 0.2), P(65, 20, 0.2), P(-65, 20, 0.2)], K0.road),
        agent({ role: "research", expr: "talking", facing: "L" }, -16, 0, { scale: 1.6 }),
        agent({ role: "builder", rank: "lead", expr: "neutral", facing: "R" }, 18, 0, {
          scale: 1.6,
        }),
      );
      vb = [-100, -80, 200, 150];
    }
    if (kind.startsWith("gate")) {
      const s = kind.split("-")[1];
      out.push(
        plate(130, 90),
        poly([P(-65, -20, 0.2), P(65, -20, 0.2), P(65, 20, 0.2), P(-65, 20, 0.2)], K0.road),
      );
      const g = gate(0, 0, s);
      out.push(
        g.el,
        pin(s === "waiting" ? "needs" : s === "open" ? "complete" : "lock", g.top, {
          lift: 16,
          r: 9,
        }),
      );
      vb = [-100, -95, 200, 165];
    }
    if (kind === "cloud") {
      out.push(
        plate(130, 90),
        box(-55, -35, 0, 110, 70, 3, {
          t: lt(DIST.payroll, 0.86),
          l: lt(DIST.payroll, 0.6),
          r: lt(DIST.payroll, 0.48),
        }),
        clouds(-55, -35, 110, 70, 5),
        pin("lock", [P(0, 0, 48)[0], P(0, 0, 48)[1] + 18], { lift: 0, r: 12 }),
      );
      vb = [-100, -110, 200, 180];
    }
    if (kind === "island") {
      out.push(
        box(-60, -45, -26, 120, 90, 6, { t: K0.gR, l: dk(K0.gL, 0.12), r: dk(K0.gR, 0.14) }).slice(
          0,
          2,
        ),
        box(-60, -45, -20, 120, 90, 20, { t: K0.gT, l: K0.gL, r: K0.gR }),
      );
      vb = [-100, -80, 200, 150];
    }
    // the prototype throws a TypeError for a kind it does not know (vb is undefined); so does the port
    if (!vb) throw new TypeError(`soloPiece: unknown kind "${kind}"`);
    const hh = size || 130;
    return E(
      "svg",
      {
        viewBox: vb.join(" "),
        width: (hh * (vb[2] as number)) / (vb[3] as number),
        height: hh,
        style: { display: "block" },
      },
      out,
    );
  }
  /* ============ metropolis: stacked levels, lifts, satellites, bridges ============ */
  function liftEl(
    x: number,
    y: number,
    z0: number,
    z1: number,
    o: { state?: string | undefined; t?: number | undefined; parcel?: boolean | undefined },
  ): { el: El; cab: Pt | null } {
    const s = 24;
    const pl = o.state === "planned";
    const out: El[] = [];
    const post = { t: lt(K0.ink2, 0.55), l: lt(K0.ink2, 0.3), r: K0.ink2 };
    const face = {
      fill: pl ? "none" : K0.hero,
      fillOpacity: 0.1,
      stroke: pl ? K0.ink2 : lt(K0.hero, 0.35),
      strokeWidth: 1.3,
      strokeDasharray: pl ? "6 5" : "none",
    };
    const zb = z0 - 26;
    const hh = z1 - zb;
    if (!pl) out.push(box(x - s / 2 - 1.5, y - s / 2 - 1.5, zb, 3, 3, hh, post));
    out.push(
      E("polygon", {
        points: pts([
          P(x - s / 2, y + s / 2, zb),
          P(x + s / 2, y + s / 2, zb),
          P(x + s / 2, y + s / 2, z1),
          P(x - s / 2, y + s / 2, z1),
        ]),
        ...face,
      }),
      E("polygon", {
        points: pts([
          P(x + s / 2, y + s / 2, zb),
          P(x + s / 2, y - s / 2, zb),
          P(x + s / 2, y - s / 2, z1),
          P(x + s / 2, y + s / 2, z1),
        ]),
        ...face,
      }),
    );
    let cab: Pt | null = null;
    if (!pl) {
      const zc = z0 + (z1 - z0) * (o.t || 0);
      out.push(
        box(x - s / 2 + 2.5, y - s / 2 + 2.5, zc, s - 5, s - 5, 20, {
          t: lt(K0.hero, 0.55),
          l: lt(K0.hero, 0.25),
          r: K0.hero,
        }),
      );
      if (o.parcel) out.push(box(x - 4.5, y - 4.5, zc + 20, 9, 9, 8, shade(K0.kraft)));
      cab = P(x, y, zc + (o.parcel ? 30 : 22));
      const posts: Pt[] = [
        [x + s / 2, y - s / 2],
        [x + s / 2, y + s / 2],
        [x - s / 2, y + s / 2],
      ];
      for (const [a, b] of posts) out.push(box(a - 1.5, b - 1.5, zb, 3, 3, hh, post));
      out.push(box(x - s / 2 - 2, y - s / 2 - 2, z1 - 3, s + 4, s + 4, 3, post));
    }
    return { el: E("g", null, out), cab };
  }
  function landing(x: number, yEdge: number, yS: number, z: number): El[] {
    return box(x - 11, yEdge, z - 5, 22, Math.max(0, yS - yEdge), 5, {
      t: K0.road,
      l: dk(K0.road, 0.14),
      r: dk(K0.road, 0.24),
    });
  }
  function metro(levels: Level[], o0?: MetroOpts): El {
    const o = Object.assign({ seed: 1, labels: true, anim: false }, o0 || ({} as MetroOpts));
    const GZ = o.gapZ || 330;
    const layers: El[] = [];
    const tops: El[] = [];
    let bb: Box4 = [1e9, -1e9, 1e9, -1e9];
    const grow = (b: Box4, p: Pt): void => {
      bb = [
        Math.min(bb[0], b[0] + p[0]),
        Math.max(bb[1], b[1] + p[0]),
        Math.min(bb[2], b[2] + p[1]),
        Math.max(bb[3], b[3] + p[1]),
      ];
    };
    const info = levels.map((lv, i) => {
      const z = i * GZ;
      const zig = o.zig == null ? 170 : o.zig;
      const dx = (i % 2) * zig;
      const dy = -(i % 2) * zig;
      const Lm = layout(lv.plan, o.seed + i);
      const M0 = 0.8 * T;
      let sy = 0;
      const sx = dx + Lm.Wt + 2 * M0 + 110;
      const sats = (lv.sats || []).map((s, j) => {
        const Ls = layout(s.plan, o.seed + i + 9);
        if (j > 0) sy += Ls.Dt + 2 * M0 + 70;
        return { plan: s.plan, dx: sx, dy: dy - sy, Ls, truck: s.truck, j };
      });
      return { lv, i, z, dx, dy, Lm, M0, sats };
    });
    for (const [idx, q] of info.entries()) {
      const pieces = [{ plan: q.lv.plan, dx: q.dx, dy: q.dy, seed: o.seed + q.i }].concat(
        q.sats
          .slice()
          .reverse()
          .map((s) => ({ plan: s.plan, dx: s.dx, dy: s.dy, seed: o.seed + q.i + 9 })),
      );
      const parts = pieces.map((pc) => ({
        pc,
        r: world(pc.plan, {
          seed: pc.seed,
          labels: o.labels,
          anim: o.anim,
          parts: true,
          stage: q.lv.stage || 4,
        }),
      }));
      const tr = (pc: { dx: number; dy: number }): { transform: string; p: Pt } => {
        const p = P(pc.dx, pc.dy, q.z);
        return { transform: `translate(${p[0].toFixed(1)} ${p[1].toFixed(1)})`, p };
      };
      const g: El[] = [];
      for (const { pc, r } of parts) {
        const t = tr(pc);
        g.push(E("g", { transform: t.transform }, r.ground));
        grow(r.bb, t.p);
      }
      for (const [j, s] of q.sats.entries()) {
        const rd = { t: K0.road, l: dk(K0.road, 0.14), r: dk(K0.road, 0.24) };
        if (j === 0) {
          const x1 = q.dx + q.Lm.Wt + q.M0;
          const x2 = s.dx - q.M0;
          const yb = s.dy + Math.min(s.Ls.Dt, q.Lm.Dt) / 2;
          g.push(box(x1, yb - 15, q.z - 5, x2 - x1, 30, 5, rd));
          if (s.truck != null) {
            const tx = x1 + (x2 - x1) * s.truck;
            g.push(
              box(tx - 12, yb - 7, q.z, 24, 14, 13, shade(K0.kraft)),
              box(tx + 12, yb - 7, q.z, 9, 14, 9, shade(lt(K0.ink2, 0.3))),
            );
          }
        } else {
          const pv = q.sats[j - 1] as (typeof q.sats)[number];
          const y1 = s.dy + s.Ls.Dt + q.M0;
          const y2 = pv.dy - q.M0;
          const xb = s.dx + Math.min(s.Ls.Wt, pv.Ls.Wt) / 2;
          g.push(box(xb - 15, y1, q.z - 5, 30, y2 - y1, 5, rd));
          if (s.truck != null) {
            const ty = y1 + (y2 - y1) * s.truck;
            g.push(box(xb - 7, ty - 12, q.z, 14, 24, 13, shade(K0.kraft)));
          }
        }
      }
      const objs: { k: number; el: El }[] = [];
      for (const { pc, r } of parts) {
        const t = tr(pc);
        for (const ob of r.objs)
          objs.push({ k: ob.k + pc.dx + pc.dy, el: E("g", { transform: t.transform }, ob.el) });
      }
      objs.sort((a, b) => a.k - b.k);
      g.push(objs.map((ob) => ob.el));
      for (const { pc, r } of parts) {
        const t = tr(pc);
        g.push(E("g", { transform: t.transform }, r.cover));
        tops.push(E("g", { transform: t.transform }, r.top));
      }
      layers.push(E("g", null, g));
      const vx = P(q.dx - q.M0, q.dy + q.Lm.Dt + q.M0, q.z - 10);
      const txt = q.lv.name;
      const w = txt.length * 16 * 0.58 + 70;
      tops.push(
        E(
          "g",
          null,
          E("rect", {
            x: vx[0] - w - 18,
            y: vx[1] - 18,
            width: w,
            height: 40,
            rx: 20,
            fill: "#1F1D2B",
          }),
          E("rect", {
            x: vx[0] - w - 14,
            y: vx[1] - 14,
            width: 40,
            height: 32,
            rx: 16,
            fill: q.lv.color || K0.hero,
          }),
          E(
            "text",
            {
              x: vx[0] - w + 6,
              y: vx[1] + 7,
              textAnchor: "middle",
              fontFamily: K0.body,
              fontSize: 15,
              fontWeight: 800,
              fill: "#FFFFFF",
            },
            q.lv.code,
          ),
          E(
            "text",
            {
              x: vx[0] - w + 34,
              y: vx[1] + 7,
              fontFamily: K0.body,
              fontSize: 16,
              fontWeight: 800,
              fill: "#FFFFFF",
            },
            txt,
          ),
        ),
      );
      grow([vx[0] - w - 30, vx[0], vx[1] - 30, vx[1] + 30], [0, 0]);
      const nx = info[idx + 1];
      if (nx) {
        for (const [j, lf] of (q.lv.lifts || [{ t: 0, state: "idle" }]).entries()) {
          const x = Math.max(q.dx, nx.dx) + 80 + j * 70;
          const fa = q.dy + q.Lm.Dt + q.M0;
          const fb = nx.dy + nx.Lm.Dt + nx.M0;
          const yS = Math.max(fa, fb) + 34;
          const lg: El[] = [landing(x, fa, yS - 12, q.z)];
          const L1 = liftEl(x, yS, q.z, nx.z, lf);
          lg.push(L1.el);
          if (lf.state !== "planned") lg.push(landing(x, fb, yS - 12, nx.z));
          layers.push(E("g", null, lg));
          if (L1.cab && lf.label) {
            tops.push(
              tag(
                lf.label,
                [L1.cab[0] + lf.label.length * 3.2 + 34, L1.cab[1] - 6],
                K0.hero,
                "parcel",
                {
                  fs: 12,
                },
              ),
            );
          }
        }
      }
    }
    const defs = E(
      "defs",
      null,
      E(
        "pattern",
        {
          id: "tiloHatch",
          width: 8,
          height: 8,
          patternUnits: "userSpaceOnUse",
          patternTransform: "rotate(30)",
        },
        E("rect", { width: 8, height: 8, fill: "#F4EFE2" }),
        E("rect", { width: 3, height: 8, fill: "#E4D9BE" }),
      ),
    );
    const vb = [bb[0] - 20, bb[2] - 20, bb[1] - bb[0] + 40, bb[3] - bb[2] + 40];
    return E(
      "svg",
      {
        viewBox: vb.map((v) => v.toFixed(0)).join(" "),
        width: o.width || "100%",
        height: o.height || "100%",
        preserveAspectRatio: "xMidYMid meet",
        style: { display: "block" },
      },
      defs,
      layers,
      tops,
    );
  }
  return {
    metro,
    world,
    soloBuilding,
    soloAgent,
    soloPiece,
    layout,
    KIT,
    DIST,
    ROLE,
    K0,
    icon,
    dk,
    lt,
    agent,
    pin,
    tag,
    label,
    box,
    poly,
    shade,
    crate,
    P,
    pts,
    mL,
    mR,
    mT,
    route,
    along,
    standOf,
    gate,
    clouds,
    liftEl,
    landing,
    building,
    specOf,
    presence,
    comment,
    tree,
    T,
    G,
    INS,
    AS,
  };
}

/** What `createWorld(h)` returns (the prototype's `TiloWorld(h)` object). */
export type World = ReturnType<typeof createWorld>;
