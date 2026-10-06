// WEB-PARITY: captures the design reference and our /park pages side by side, diffs them and writes
// parity-report/. Opt-in (`TILO_PARITY=1`, `just parity [page]`); it reports, it never fails on a diff.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "@playwright/test";
import { type Shot, openDesign, openOurs, setTheme, shoot } from "./capture";
import { type Rect, crop, decode, diffImages, encode, gridRects } from "./diff";
import { PAGES, type PageSpec, THEMES, type Theme, VIEWPORTS } from "./pages";
import { startRefServer } from "./refServer";
import { DEFAULT_STYLE_ROOT, REGIONS } from "./regions";
import { type CaptureResult, type RegionResult, writeReport } from "./report";
import { compareStyles } from "./styles";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "../../../parity-report");
const REF_PORT = Number(process.env.TILO_PARITY_REF_PORT ?? 5396);
const OURS = `http://127.0.0.1:${Number(process.env.TILO_PARITY_PORT ?? 5395)}`;
const only = (process.env.PARITY_PAGES ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const pages = PAGES.filter((p) => only.length === 0 || only.includes(p.name));
const results: CaptureResult[] = [];
let refOrigin = "";
let closeRef = async () => {};

test.describe.configure({ mode: "serial" });
test.beforeAll(async () => {
  const ref = await startRefServer(REF_PORT);
  refOrigin = ref.origin;
  closeRef = () => new Promise((ok) => ref.server.close(() => ok(undefined)));
});
test.afterAll(async () => {
  await closeRef();
  writeReport(OUT, results, {
    generatedAt: new Date().toISOString(),
    design: refOrigin,
    ours: OURS,
    pages: pages.map((p) => p.name),
  });
});

function compare(
  spec: PageSpec,
  vp: string,
  theme: Theme,
  d: Shot,
  o: Shot,
  errors: string[],
): CaptureResult {
  const dir = `${spec.name}/${vp}-${theme}`;
  mkdirSync(join(OUT, dir), { recursive: true });
  const save = (file: string, buf: Buffer) => writeFileSync(join(OUT, dir, file), buf);
  const a = decode(d.png);
  const b = decode(o.png);
  const full = diffImages(a, b);
  save("design.png", d.png);
  save("ours.png", o.png);
  save("diff-full.png", encode(full.diff));
  const [pa, pb] = full.padded;
  const specs = REGIONS[spec.name] ?? gridRects(pa.width, pa.height);
  const regions: RegionResult[] = specs.map((r) => {
    let rects: [Rect, Rect];
    if ("design" in r) {
      const [rd, ro] = [d.rects[r.name], o.rects[r.name]];
      if (!rd || !ro)
        return {
          name: r.name,
          pct: null,
          mismatched: 0,
          total: 0,
          note: `selector not found on ${rd ? "ours" : "design"}`,
        };
      rects = [rd, ro];
    } else rects = [r, r];
    const [sa, sb] = "design" in r ? [a, b] : [pa, pb];
    const res = diffImages(crop(sa, rects[0]), crop(sb, rects[1]));
    const file = `diff-${r.name}.png`;
    save(file, encode(res.diff));
    return {
      name: r.name,
      pct: res.pct,
      mismatched: res.mismatched,
      total: res.total,
      file,
      note: res.sizeMismatch ? `size ${res.sizeA.join("x")} vs ${res.sizeB.join("x")}` : undefined,
    };
  });
  return {
    page: spec.name,
    viewport: vp,
    theme,
    status: "ok",
    pct: full.pct,
    mismatched: full.mismatched,
    total: full.total,
    designSize: full.sizeA.join("x"),
    oursSize: full.sizeB.join("x"),
    sizeMismatch: full.sizeMismatch,
    regions,
    styleDiffs: Object.keys(d.styles).flatMap((name) => {
      const [sd, so] = [d.styles[name], o.styles[name]];
      if (sd && so) return compareStyles(name, sd, so);
      return [
        {
          region: name,
          element: "(root)",
          prop: "selector",
          design: sd ? "found" : "not found",
          ours: so ? "found" : "not found",
        },
      ];
    }),
    consoleErrors: errors,
    dir,
  };
}

for (const spec of pages) {
  test(`WEB_PARITY capture ${spec.name}`, async ({ browser }) => {
    test.setTimeout(180_000);
    const regions = REGIONS[spec.name] ?? [DEFAULT_STYLE_ROOT];
    for (const vp of VIEWPORTS) {
      const base = {
        page: spec.name,
        viewport: vp.name,
        regions: [],
        consoleErrors: [] as string[],
      };
      const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        reducedMotion: "reduce",
      });
      try {
        const [dPage, oPage] = [await ctx.newPage(), await ctx.newPage()];
        const problems: string[] = [];
        oPage.on(
          "console",
          (m) =>
            (m.type() === "error" || m.type() === "warning") &&
            problems.push(`[${m.type()}] ${m.text()}`),
        );
        oPage.on("pageerror", (e) => problems.push(`[pageerror] ${e.message}`));
        await openDesign(dPage, refOrigin, spec);
        const found = await openOurs(oPage, OURS, spec);
        let seen = 0;
        for (const theme of THEMES) {
          await setTheme(dPage, "design", theme);
          const d = await shoot(dPage, "design", regions);
          if (!found) {
            const dir = `${spec.name}/${vp.name}-${theme}`;
            mkdirSync(join(OUT, dir), { recursive: true });
            writeFileSync(join(OUT, dir, "design.png"), d.png);
            results.push({ ...base, theme, status: "route missing", dir });
            continue;
          }
          await setTheme(oPage, "ours", theme);
          const o = await shoot(oPage, "ours", regions);
          results.push(compare(spec, vp.name, theme, d, o, problems.slice(seen)));
          seen = problems.length;
        }
      } catch (e) {
        for (const theme of THEMES) {
          if (
            !results.some(
              (c) => c.page === spec.name && c.viewport === vp.name && c.theme === theme,
            )
          ) {
            results.push({
              ...base,
              theme,
              status: "error",
              error: String(e).split("\n")[0],
              dir: "",
            });
          }
        }
      } finally {
        await ctx.close();
      }
    }
  });
}
