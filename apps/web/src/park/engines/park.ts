// ported from design_handoff_tilo_web_app/design/tilo-park.js (user's prototype, ADR-0003a)
// The Park City backdrop and glass-friendly world thumbnails. Static art is built as SVG strings and
// shown as images; only the movers are separate layers. Faithful port: same names, numbers, rounding,
// call order and seeded rng as the prototype. Differences by design: `createPark(h, makeWorld, env)`
// instead of `window.TiloPark(h)` (the world engine is built from the factory on the park's own string
// builder; the browser calls Blob and URL.createObjectURL come in through `env`), and no animation: the
// cars and walkers are always drawn frozen at their seeded phase (motion returns in WEB-3, BQ-WEB-3).
import type {
  AgentSpec,
  El,
  H,
  Opt,
  ParkEnv,
  Plan,
  Props,
  Pt,
  SceneOpts,
  Spec,
  Spot,
} from "./types";
import type { World } from "./world";

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
const ATTR =
  /^(viewBox|preserveAspectRatio|patternUnits|patternTransform|gradientTransform|gradientUnits|attributeName|repeatCount|xmlns)$/;
const kb = (k: string): string => k.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
const esc = (v: unknown): string =>
  String(v).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
type RGB = [number, number, number];
const NAVY: RGB = [16, 20, 56];
const PAPER: RGB = [240, 238, 232];
/** The string-building element the park hands to the world engine: `{ s }` is the SVG text. */
interface Str {
  s: string;
}
type CMap = (c: unknown) => unknown;
const toward =
  (B: RGB, t: number, warm?: boolean): CMap =>
  (c) => {
    if (typeof c !== "string" || c[0] !== "#" || c.length !== 7) return c;
    const u = c.toUpperCase();
    if (warm && u === "#FFFFFF") return "#FFD98A";
    return `#${[1, 3, 5]
      .map((i, j) => {
        const v = Number.parseInt(u.slice(i, i + 2), 16);
        return Math.round(v + ((B[j] as number) - v) * t)
          .toString(16)
          .padStart(2, "0");
      })
      .join("")}`;
  };

type Walk5 = [number, number, number, number, number];
interface SceneObj {
  k: number;
  b: [number, number, number, number];
  el: El;
}

export function createPark(
  h: H,
  makeWorld: (h: H) => World,
  env: ParkEnv = {},
): {
  scene: (o?: SceneOpts) => { el: El; spots: Spot[] };
  world: (plan: Plan, o?: Opt<{ night: boolean; seed: number }>) => El;
  building: (spec: string | Spec, state: string, d?: string, ht?: number, night?: boolean) => El;
  agent: (a: AgentSpec, size?: number, night?: boolean) => El;
} {
  let cmap: CMap | null = null;
  const E = (t: string, p: Props | null, ...c: unknown[]): Str => {
    let a = "";
    if (p)
      for (const k in p) {
        let v = p[k];
        if (v == null || v === false || k === "key") continue;
        if (cmap && (k === "fill" || k === "stroke" || k === "stopColor")) v = cmap(v);
        const val =
          k === "style" && typeof v === "object"
            ? Object.entries(v as Record<string, unknown>)
                .filter((e) => e[1] != null)
                .map(([q, w]) => `${kb(q)}:${w}`)
                .join(";")
            : v;
        a += ` ${ATTR.test(k) ? k : kb(k)}="${esc(val)}"`;
      }
    const kids = c
      .flat(9)
      .filter((x) => x != null && x !== false)
      .map((x) =>
        typeof x === "object"
          ? (x as Str).s
          : String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;"),
      )
      .join("");
    return { s: `<${t}${a}${kids ? `>${kids}</${t}>` : "/>"}` };
  };
  const W = makeWorld(E);
  const using = <R>(m: CMap | null, fn: () => R): R => {
    const p = cmap;
    cmap = m;
    try {
      return fn();
    } finally {
      cmap = p;
    }
  };
  // The browser calls come in through env (the platform's own Blob and URL.createObjectURL by default).
  const blob = (s: string): string => {
    const B = env.Blob ?? Blob;
    const make = env.createObjectURL ?? ((b: Blob) => URL.createObjectURL(b));
    return make(new B([s], { type: "image/svg+xml" }));
  };
  const svgUrl = (w: number, hh: number, vb: string, kids: unknown, par?: string): string =>
    blob(
      E(
        "svg",
        {
          xmlns: "http://www.w3.org/2000/svg",
          width: w,
          height: hh,
          viewBox: vb,
          preserveAspectRatio: par || "xMidYMid slice",
        },
        kids,
      ).s,
    );
  const cover = (src: string): El =>
    h("img", {
      src,
      alt: "",
      draggable: false,
      style: {
        position: "absolute",
        left: 0,
        top: 0,
        width: "100%",
        height: "100%",
        display: "block",
        pointerEvents: "none",
      },
    });
  // motion: restored in WEB-3 (BQ-WEB-3). Until then every mover sits at its seeded phase along the road.
  const motion = (dx: number, dy: number, f: number): Props => ({
    transform: `translate(${(dx * f).toFixed(1)}px, ${(dy * f).toFixed(1)}px)`,
  });
  function mover(
    x: number,
    y: number,
    dx: number,
    dy: number,
    f: number,
    vb: Walk5,
    child: unknown,
  ): El {
    const sc = vb[4];
    const src = svgUrl(vb[2] * sc, vb[3] * sc, vb.slice(0, 4).join(" "), child, "xMidYMid meet");
    return h(
      "div",
      {
        style: {
          position: "absolute",
          left: `${x.toFixed(1)}px`,
          top: `${y.toFixed(1)}px`,
          width: 0,
          height: 0,
          willChange: "transform",
          pointerEvents: "none",
          ...motion(dx, dy, f),
        },
      },
      h("img", {
        src,
        alt: "",
        draggable: false,
        style: {
          position: "absolute",
          left: `${vb[0] * sc}px`,
          top: `${vb[1] * sc}px`,
          width: `${vb[2] * sc}px`,
          height: `${vb[3] * sc}px`,
          display: "block",
        },
      }),
    );
  }
  function walker(
    x: number,
    y: number,
    dx: number,
    dy: number,
    f: number,
    vb: Walk5,
    frames: [unknown, unknown],
  ): El {
    const sc = vb[4];
    const w = vb[2] * sc;
    const hh = vb[3] * sc;
    const src = svgUrl(
      2 * w,
      hh,
      `${vb[0]} ${vb[1]} ${2 * vb[2]} ${vb[3]}`,
      [frames[0], E("g", { transform: `translate(${vb[2]} 0)` }, frames[1])],
      "xMidYMid meet",
    );
    return h(
      "div",
      {
        style: {
          position: "absolute",
          left: `${x.toFixed(1)}px`,
          top: `${y.toFixed(1)}px`,
          width: 0,
          height: 0,
          willChange: "transform",
          pointerEvents: "none",
          ...motion(dx, dy, f),
        },
      },
      h(
        "div",
        {
          style: {
            position: "absolute",
            left: 0,
            top: 0,
            width: 0,
            height: 0,
            transformOrigin: "0 0",
          },
        },
        h("div", {
          style: {
            position: "absolute",
            left: `${vb[0] * sc}px`,
            top: `${vb[1] * sc}px`,
            width: `${w}px`,
            height: `${hh}px`,
            backgroundImage: `url("${src}")`,
            backgroundSize: "200% 100%",
            backgroundRepeat: "no-repeat",
            backgroundPosition: "0% 0",
          },
        }),
      ),
    );
  }
  function depthSort(list: SceneObj[]): SceneObj[] {
    const n = list.length;
    const out: SceneObj[] = [];
    const indeg: number[] = new Array(n).fill(0);
    const adj: number[][] = Array.from({ length: n }, () => []);
    const done: boolean[] = new Array(n).fill(false);
    const bh = (A: SceneObj["b"], B: SceneObj["b"]): boolean =>
      A[1] <= B[0] + 0.01 || A[3] <= B[2] + 0.01;
    for (let i = 0; i < n; i++)
      for (let j = i + 1; j < n; j++) {
        const a = (list[i] as SceneObj).b;
        const b = (list[j] as SceneObj).b;
        const ab = bh(a, b);
        const ba = bh(b, a);
        if (ab && !ba) {
          (adj[i] as number[]).push(j);
          indeg[j] = (indeg[j] as number) + 1;
        } else if (ba && !ab) {
          (adj[j] as number[]).push(i);
          indeg[i] = (indeg[i] as number) + 1;
        }
      }
    const ready: number[] = [];
    for (let i = 0; i < n; i++) if (!indeg[i]) ready.push(i);
    while (out.length < n) {
      if (!ready.length) {
        let m = -1;
        for (let i = 0; i < n; i++)
          if (!done[i] && (m < 0 || (list[i] as SceneObj).k < (list[m] as SceneObj).k)) m = i;
        ready.push(m);
      }
      ready.sort((p, q) => (list[q] as SceneObj).k - (list[p] as SceneObj).k);
      const i = ready.pop() as number;
      if (done[i]) continue;
      done[i] = true;
      out.push(list[i] as SceneObj);
      for (const j of adj[i] as number[]) {
        indeg[j] = (indeg[j] as number) - 1;
        if (indeg[j] === 0 && !done[j]) ready.push(j);
      }
    }
    return out;
  }
  /* o: {w,h} artboard px, night, mute (0..1 pull towards paper); k and still are accepted and ignored */
  function scene(o0?: SceneOpts): { el: El; spots: Spot[] } {
    const o = Object.assign(
      { w: 1440, h: 900, vw: 1120, seed: 23, night: false, k: 1, still: false, mute: 0 },
      o0 || ({} as SceneOpts),
    );
    const { P, box, poly, shade, lt, building, agent } = W;
    const T = 48;
    const r = rng(o.seed);
    const pick = <V>(a: readonly V[]): V => a[Math.floor(r() * a.length)] as V;
    const night = o.night;
    const SM = night ? toward(NAVY, 0.64, true) : o.mute ? toward(PAPER, o.mute) : null;
    const MM = night ? toward(NAVY, 0.3) : o.mute ? toward(PAPER, o.mute * 0.5) : null;
    const prev = cmap;
    cmap = SM;
    try {
      const BW = 4 * T;
      const BD = 3 * T;
      const RD = 46;
      const PX = BW + RD;
      const PY = BD + RD;
      const C = 8;
      const R = 9;
      const X = C * PX + RD;
      const Y = R * PY + RD;
      const VW = o.vw;
      const VH = (VW * o.h) / o.w;
      const ctr = P(X / 2, Y / 2, 0);
      const vx = ctr[0] - VW / 2;
      const vy = ctr[1] - VH / 2 - 40;
      const s2 = o.w / VW;
      const toPx = (p: Pt): Pt => [(p[0] - vx) * s2, (p[1] - vy) * s2];
      const HUES = [
        "#F2825F",
        "#F4B23E",
        "#3FBF8C",
        "#3E9BE6",
        "#8A6CF0",
        "#EC6AA6",
        "#22AFAF",
        "#F07A3A",
        "#5A7BEF",
      ];
      const TC: [string, string][] = [
        ["#6CC56B", "#47A653"],
        ["#8FD45E", "#69B640"],
        ["#3FB487", "#2A9470"],
        ["#6CC56B", "#47A653"],
        ["#F59BC3", "#E275A6"],
        ["#F7BE4F", "#E59E2C"],
        ["#8FD45E", "#69B640"],
        ["#3FB487", "#2A9470"],
      ];
      const CARS = ["#F2825F", "#3E9BE6", "#F4B23E", "#8A6CF0", "#EC6AA6", "#FFFFFF", "#22AFAF"];
      const ROLES = [
        "research",
        "builder",
        "tester",
        "browser",
        "connector",
        "delivery",
        "designer",
        "finance",
      ];
      const ICONS = [
        "search",
        "doc",
        "mail",
        "coin",
        "people",
        "clock",
        "swap",
        "laptop",
        "cap",
        "parcel",
        "person",
        "hall",
      ];
      const TPL: [number, number, number, number][][] = [
        [
          [0, 1, 2, 2],
          [2, 2, 2, 1],
          [3, 0, 1, 1],
        ],
        [
          [0, 2, 2, 1],
          [2, 1, 2, 2],
          [0, 0, 1, 1],
        ],
        [
          [1, 1, 2, 2],
          [3, 2, 1, 1],
          [0, 2, 1, 1],
        ],
        [
          [0, 1, 1, 2],
          [1, 2, 2, 1],
          [3, 1, 1, 2],
        ],
        [[1, 1, 2, 2]],
        [
          [0, 2, 1, 1],
          [1, 2, 1, 1],
          [2, 1, 2, 2],
        ],
      ];
      const LAMP = { t: "rgb(255,238,176)", l: "rgb(255,226,150)", r: "rgb(236,196,118)" };
      const LOFF = { t: "#F4F1EA", l: "#E2DDD2", r: "#CFC8BA" };
      const tree = (x: number, y: number, s: number, kind: string, c: [string, string]): El => {
        const out: El[] = [box(x - 1.8, y - 1.8, 0, 3.6, 3.6, 7, shade("#9C7556"))];
        if (kind === "pine") {
          const b = P(x, y, 6);
          const tp = P(x, y, 6 + s * 2.8);
          const w = s * 1.25;
          out.push(
            E("path", {
              d: `M${b[0] - w} ${b[1]} L${tp[0]} ${tp[1]} L${b[0]} ${b[1] + w * 0.42} Z`,
              fill: c[0],
            }),
            E("path", {
              d: `M${b[0] + w} ${b[1]} L${tp[0]} ${tp[1]} L${b[0]} ${b[1] + w * 0.42} Z`,
              fill: c[1],
            }),
          );
        } else {
          const cc = P(x, y, 7 + s);
          const R0 = s * 1.2247;
          out.push(
            E("path", {
              d: `M${cc[0]} ${cc[1] - R0} A${R0} ${R0} 0 0 0 ${cc[0]} ${cc[1] + R0} Z`,
              fill: c[0],
            }),
            E("path", {
              d: `M${cc[0]} ${cc[1] - R0} A${R0} ${R0} 0 0 1 ${cc[0]} ${cc[1] + R0} Z`,
              fill: c[1],
            }),
          );
        }
        return E("g", null, out);
      };
      const car = (x: number, y: number, col: string, dir: number): El[] => {
        const c = P(x, y, 0);
        const out: El[] = [
          E("ellipse", { cx: c[0], cy: c[1], rx: 15, ry: 8, fill: "rgba(31,29,43,.14)" }),
          box(x - 11, y - 5.5, 2, 22, 11, 7, shade(col)),
          box(x - 5, y - 5, 9, 11, 10, 6, { t: lt(col, 0.35), l: "#E3F0FF", r: "#C3D6EE" }),
        ];
        const L = night
          ? dir > 0
            ? LAMP
            : { t: "rgb(255,96,112)", l: "rgb(255,96,112)", r: "rgb(220,70,90)" }
          : dir > 0
            ? LOFF
            : { t: "#D98A94", l: "#C9707C", r: "#B35E6A" };
        out.push(
          box(x + 10.6, y - 4.6, 4, 1, 2.8, 2.4, L),
          box(x + 10.6, y + 1.8, 4, 1, 2.8, 2.4, L),
        );
        return out;
      };
      const lamp = (x: number, y: number): unknown[] => {
        const hd = P(x, y, 33);
        return [
          box(x - 1.3, y - 1.3, 0, 2.6, 2.6, 30, { t: "#6A6680", l: "#4C4860", r: "#3C3850" }),
          box(x - 3, y - 3, 30, 6, 6, 4, night ? LAMP : LOFF),
          night && E("circle", { cx: hd[0], cy: hd[1], r: 11, fill: "rgba(255,222,140,.32)" }),
        ];
      };
      const big = 30 * T;
      const ROAD = "#E2DBF0";
      const DASH = night ? "rgba(170,170,210,.5)" : "#FFFFFF";
      const seg = (a: Pt, b: Pt, z: number): string =>
        `M${P(a[0], a[1], z)
          .map((v) => v.toFixed(1))
          .join(" ")} L${P(b[0], b[1], z)
          .map((v) => v.toFixed(1))
          .join(" ")}`;
      const ground: unknown[] = [
        poly(
          [P(-big, -big, 0), P(X + big, -big, 0), P(X + big, Y + big, 0), P(-big, Y + big, 0)],
          "#A6D78C",
        ),
      ];
      const marks: unknown[] = [];
      const plots: unknown[] = [];
      const glows: unknown[] = [];
      for (let j = 0; j <= R; j++) {
        const y = j * PY;
        ground.push(
          poly(
            [P(-big, y, 0.2), P(X + big, y, 0.2), P(X + big, y + RD, 0.2), P(-big, y + RD, 0.2)],
            ROAD,
          ),
        );
        marks.push(
          E("path", {
            d: seg([-big, y + RD / 2], [X + big, y + RD / 2], 0.4),
            stroke: DASH,
            strokeWidth: 2.4,
            strokeDasharray: "12 12",
            fill: "none",
          }),
        );
      }
      for (let i = 0; i <= C; i++) {
        const x = i * PX;
        ground.push(
          poly(
            [P(x, -big, 0.2), P(x + RD, -big, 0.2), P(x + RD, Y + big, 0.2), P(x, Y + big, 0.2)],
            ROAD,
          ),
        );
        marks.push(
          E("path", {
            d: seg([x + RD / 2, -big], [x + RD / 2, Y + big], 0.4),
            stroke: DASH,
            strokeWidth: 2.4,
            strokeDasharray: "12 12",
            fill: "none",
          }),
        );
      }
      const inView = (cs: Pt[], top: number): boolean => {
        const xs = cs.map((p) => p[0]);
        const ys = cs.map((p) => p[1]);
        return (
          Math.max(...xs) > vx - 90 &&
          Math.min(...xs) < vx + VW + 90 &&
          Math.max(...ys) > vy - 60 &&
          Math.min(...ys) - top < vy + VH + 90
        );
      };
      const rows: SceneObj[][] = [];
      const spots: { top: Pt; area: number; st: string }[] = [];
      for (let j = 0; j < R; j++) {
        const objs: SceneObj[] = [];
        rows[j] = objs;
        for (let i = 0; i < C; i++) {
          const bx = i * PX + RD;
          const by = j * PY + RD;
          if (
            !inView(
              [P(bx, by, 0), P(bx + BW, by, 0), P(bx + BW, by + BD, 0), P(bx, by + BD, 0)],
              170,
            )
          )
            continue;
          plots.push(box(bx, by, 0, BW, BD, 4, { t: "#C6EBB0", l: "#9FCF88", r: "#8EBF78" }));
          for (const ly of [by + BD * 0.2, by + BD * 0.8]) {
            const lx = bx - 7;
            const g = P(lx, ly, 0);
            objs.push({ k: lx + ly, b: [lx - 1, lx + 1, ly - 1, ly + 1], el: lamp(lx, ly) });
            if (night)
              glows.push(E("ellipse", { cx: g[0], cy: g[1], rx: 64, ry: 37, fill: "url(#lg)" }));
          }
          if (r() < 0.15) {
            const cx = bx + BW / 2;
            const cy = by + BD / 2;
            const ell = (rx: number, ry: number, z: number): Pt[] =>
              Array.from({ length: 28 }, (_, n) => {
                const a = (n / 28) * Math.PI * 2;
                return P(cx + Math.cos(a) * rx, cy + Math.sin(a) * ry, z);
              });
            plots.push(poly(ell(60, 42, 4.2), "#B4E4F8"), poly(ell(51, 34, 4.4), "#62BDEB"));
            for (let n = 0; n < 16; n++) {
              const tx = bx + 10 + r() * (BW - 20);
              const ty = by + 10 + r() * (BD - 20);
              const dx = (tx - cx) / 66;
              const dy = (ty - cy) / 48;
              if (dx * dx + dy * dy < 1) continue;
              objs.push({
                k: tx + ty,
                b: [tx - 1, tx + 1, ty - 1, ty + 1],
                el: tree(tx, ty, 6 + r() * 4, r() < 0.3 ? "pine" : "round", pick(TC)),
              });
            }
            continue;
          }
          const occ = new Set<string>();
          for (const [cx, cy, fw, fd] of pick(TPL)) {
            for (let a = 0; a < fw; a++)
              for (let b = 0; b < fd; b++) occ.add(`${cx + a},${cy + b}`);
            const big2 = fw * fd >= 4;
            const sq = fw === fd;
            const spec: Spec = {
              n: "",
              fp: [fw, fd],
              fl: big2 ? 2 + Math.floor(r() * 3) : 1 + Math.floor(r() * 2.6),
              roof: pick(sq ? ["flat", "gable", "dome", "flat"] : ["flat", "gable"]),
              fa: pick(["windows", "band", "arches"]),
              i: pick(ICONS),
            };
            const u = r();
            const st = u < 0.64 ? "active" : u < 0.93 ? "idle" : "construction";
            const b = building(spec, st, bx + cx * T, by + cy * T, { tint: pick(HUES) });
            objs.push({
              k: b.key,
              b: [b.x0 - 2.5, b.x0 + b.W + 2.5, b.y0 - 2.5, b.y0 + b.D + 2.5],
              el: b.el,
            });
            if (st !== "construction") spots.push({ top: b.top, area: fw * fd, st });
            const roll = r();
            if (st !== "construction" && cy + fd === 3 && roll < 0.45) {
              const ax = b.x0 + b.W * 0.26;
              const ay = by + BD + 3;
              const ex = pick(["focused", "neutral", "talking", "delighted"]);
              const fa = r() < 0.5 ? "L" : "R";
              const role = pick(ROLES);
              objs.push({
                k: ax + ay,
                b: [ax - 1, ax + 1, ay - 1, ay + 1],
                el: using(MM, () => agent({ role, expr: ex, facing: fa }, ax, ay, { scale: 1.15 })),
              });
            }
          }
          for (let cx = 0; cx < 4; cx++)
            for (let cy = 0; cy < 3; cy++) {
              if (occ.has(`${cx},${cy}`)) continue;
              const n = r() < 0.35 ? 2 : 1;
              for (let q = 0; q < n; q++) {
                const tx = bx + cx * T + 12 + r() * (T - 24);
                const ty = by + cy * T + 12 + r() * (T - 24);
                objs.push({
                  k: tx + ty,
                  b: [tx - 1, tx + 1, ty - 1, ty + 1],
                  el: tree(tx, ty, 6 + r() * 3.5, r() < 0.3 ? "pine" : "round", pick(TC)),
                });
              }
            }
        }
      }
      const movers: unknown[][] = [];
      for (let j = 0; j <= R; j++) {
        const y = j * PY;
        const yc = y + RD / 2;
        const list: { ly: number; el: El }[] = [];
        const x0 = Math.max(yc + (vx - 140) / 0.866, 2 * (vy - 100) - yc, -RD);
        const x1 = Math.min(yc + (vx + VW + 140) / 0.866, 2 * (vy + VH + 140) - yc, X + RD);
        if (x1 - x0 > 80) {
          const nc = r() < 0.75 ? 1 : 0;
          const nw = r() < 0.7 ? (r() < 0.35 ? 2 : 1) : 0;
          // `speed` only set the duration of the animation (restored in WEB-3, BQ-WEB-3); its draw from the rng stays.
          const place = (
            dir: number,
            ly: number,
            _speed: number,
            vb: Walk5,
            make: (a: number) => unknown,
            walk: boolean,
          ): void => {
            const a = dir > 0 ? x0 : x1;
            const b = dir > 0 ? x1 : x0;
            const f = r();
            const p0 = P(a, ly, 0);
            const q = toPx(p0);
            const dx = (b - a) * 0.866 * s2;
            const dy = (b - a) * 0.5 * s2;
            const wrap = (el: unknown): El =>
              E("g", { transform: `translate(${(-p0[0]).toFixed(1)} ${(-p0[1]).toFixed(1)})` }, el);
            const made = using(MM, () => make(a));
            list.push({
              ly,
              el: walk
                ? walker(
                    q[0],
                    q[1],
                    dx,
                    dy,
                    f,
                    vb,
                    (made as unknown[]).map(wrap) as [unknown, unknown],
                  )
                : mover(q[0], q[1], dx, dy, f, vb, wrap(made)),
            });
          };
          for (let n = 0; n < nc; n++) {
            const dir = r() < 0.5 ? 1 : -1;
            const ly = y + (dir > 0 ? RD * 0.72 : RD * 0.28);
            const col = pick(CARS);
            place(
              dir,
              ly,
              50 + r() * 20,
              [-30, -30, 60, 45, s2],
              (a) => car(a, ly, col, dir),
              false,
            );
          }
          for (let n = 0; n < nw; n++) {
            const dir = r() < 0.5 ? 1 : -1;
            const ly = y + (dir > 0 ? RD * 0.9 : RD * 0.1);
            const role = pick(ROLES);
            place(
              dir,
              ly,
              13 + r() * 5,
              [-22, -60, 44, 70, s2],
              (a) =>
                [false, true].map((step) =>
                  agent({ role, expr: "walking", facing: "R", back: dir < 0, step }, a, ly, {
                    scale: 1.1,
                  }),
                ),
              true,
            );
          }
        }
        movers.push(list.sort((p, q) => p.ly - q.ly).map((o) => o.el));
      }
      const vbS = `${vx.toFixed(1)} ${vy.toFixed(1)} ${VW} ${VH.toFixed(1)}`;
      const sv = (els: unknown): El => cover(svgUrl(o.w, o.h, vbS, els));
      const defs = night
        ? E(
            "defs",
            null,
            E(
              "radialGradient",
              { id: "lg" },
              E("stop", { offset: "0%", stopColor: "rgb(255,214,130)", stopOpacity: 0.5 }),
              E("stop", { offset: "100%", stopColor: "rgb(255,214,130)", stopOpacity: 0 }),
            ),
          )
        : null;
      const kids: unknown[] = [sv([defs, ground, marks, plots, glows])];
      for (let j = 0; j <= R; j++) {
        kids.push(movers[j]);
        const rj = rows[j];
        if (j < R && rj?.length) kids.push(sv(depthSort(rj).map((q) => q.el)));
      }
      return {
        el: h(
          "div",
          { style: { position: "absolute", inset: 0 } },
          ...kids.flat(9).filter((x) => x != null && x !== false),
        ),
        spots: spots.map((c) => {
          const q = toPx(c.top);
          return { x: q[0], y: q[1], area: c.area, st: c.st };
        }),
      };
    } finally {
      cmap = prev;
    }
  }
  const ns = (s: string): string => s.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  const dims = (s: string): [number | undefined, number | undefined] => {
    const m = s.match(/^<svg[^>]*?\swidth="([\d.]+)"[^>]*?\sheight="([\d.]+)"/);
    return m ? [+(m[1] as string), +(m[2] as string)] : [undefined, undefined];
  };
  const pic = (
    s: string,
    style: Props | undefined,
    size?: [number | undefined, number | undefined],
  ): El => {
    const t = ns(s);
    return h("img", {
      src: blob(t),
      alt: "",
      draggable: false,
      width: size?.[0],
      height: size?.[1],
      style: Object.assign({ display: "block", pointerEvents: "none" }, style || {}),
    });
  };
  function world(plan: Plan, o0?: Opt<{ night: boolean; seed: number }>): El {
    const o = o0 || {};
    const s = (
      using(o.night ? toward(NAVY, 0.6, true) : null, () =>
        W.world(plan, {
          seed: o.seed || 3,
          labels: false,
          tags: false,
          anim: false,
          width: 1000,
          height: 640,
        }),
      ) as Str
    ).s;
    return pic(s, {
      position: "absolute",
      left: 0,
      top: 0,
      width: "100%",
      height: "100%",
      objectFit: "contain",
    });
  }
  function building(
    spec: string | Spec,
    state: string,
    d?: string,
    ht?: number,
    night?: boolean,
  ): El {
    const s = (
      using(night ? toward(NAVY, 0.58, true) : null, () =>
        W.soloBuilding(spec, state, { d, height: ht }),
      ) as Str
    ).s;
    return pic(s, { flex: "none" }, dims(ns(s)));
  }
  function agent(a: AgentSpec, size?: number, night?: boolean): El {
    const s = (using(night ? toward(NAVY, 0.3) : null, () => W.soloAgent(a, size)) as Str).s;
    return pic(s, { flex: "none" }, dims(ns(s)));
  }
  return { scene, world, building, agent };
}
