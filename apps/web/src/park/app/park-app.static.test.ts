// WEB-3a static checks over apps/web/src/park/app and the mount point (plan sections 6, 10; root CLAUDE.md):
// - the honesty scan finds nothing and its ALLOWLIST is unchanged (the allowlist edit is WEB-3b);
// - no transition / animation / keyframes / rAF / setInterval: the only timer is the injected scheduler,
//   whose real implementation is setTimeout in store.ts;
// - no window globals, any, ts-ignore, raw HTML, model ids or support.js;
// - only router.ts reads window.location, anywhere under park/ (pages never do);
// - park/app imports only park/, react, and the shared router and api seams;
// - the park chunk is a dynamic import in the root, never in the landing bundle (NFR-01).
// Test files are excluded from the walk (they name these patterns on purpose).
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ALLOWLIST, scanSource } from "../../../test-support/honestyScan";

// The Park city's ambient scenery (shell and engines) is decoration, not work: its animation entries are
// pinned by src/honesty/park-ambient.allowlist.test.ts. Every other entry stays pinned exactly here.
const AMBIENT = /^src\/(park\/(shell|engines)|landing|design\/tilo-t)\//; // LANDING-2: the landing's own chrome motion; TILO-T-FOUNDATION: the design layer's keyframes

const APP = __dirname;
const PARK = resolve(APP, "..");
const SRC = resolve(PARK, "..");
const WEB = resolve(SRC, "..");

function walk(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "node_modules" ? [] : walk(p);
    return /\.test\.tsx?$/.test(name) ? [] : [p];
  });
}
const rel = (base: string, p: string) => relative(base, p).replaceAll("\\", "/");
const text = (p: string) => readFileSync(p, "utf8");
const code = (p: string) =>
  text(p)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

const appFiles = walk(APP);
const appCode = appFiles.filter((p) => /\.(tsx?|css)$/.test(p));
const appTs = appFiles.filter((p) => /\.tsx?$/.test(p));
const appRel = (p: string) => rel(APP, p);

const WINDOW_ASSIGN: RegExp[] = [
  /\bwindow\s*\.\s*[A-Za-z_$][\w$]*\s*(?:[-+*/|&?]{0,2})=(?!=)/,
  /\bwindow\s*\[[^\]]+\]\s*=(?!=)/,
  /\b(?:globalThis|self|global)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /\(\s*window\s+as\s+[^)]+\)\s*\.\s*[A-Za-z_$][\w$]*\s*=(?!=)/,
  /Object\.(?:assign|defineProperty)\s*\(\s*(?:window|globalThis)\b/,
];
const MODEL_ID = /\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-/i;

describe("WEB_3a_static: the skeleton files exist", () => {
  it("WEB_3a_static_park_app_has_the_skeleton_files", () => {
    for (const f of [
      "AppCtx.ts",
      "router.ts",
      "store.ts",
      "context.tsx",
      "pages.ts",
      "ParkApp.tsx",
    ]) {
      expect(appFiles.map(appRel), `${f} is missing`).toContain(f);
    }
  });

  it("WEB_3a_static_the_root_files_exist", () => {
    expect(existsSync(join(SRC, "Root.tsx")), "src/Root.tsx").toBe(true);
    expect(existsSync(join(SRC, "main.tsx"))).toBe(true);
  });
});

describe("WEB_3a_static: honesty (HR-1..HR-7; the scan and its allowlist are untouched)", () => {
  it("WEB_3a_static_ALLOWLIST_is_unchanged", () => {
    expect(
      ALLOWLIST.filter((e) => !AMBIENT.test(e.file)).map((e) => `${e.file}:${e.rule}`),
    ).toEqual(["src/world/runWorld.ts:raf", "src/stage/Stage.tsx:raf"]);
  });

  it("WEB_3a_static_the_honesty_scan_finds_nothing_in_park_app", () => {
    expect(appCode.length).toBeGreaterThanOrEqual(6);
    const hits = appCode.flatMap((p) => scanSource(`src/park/app/${appRel(p)}`, text(p)));
    expect(hits.map((v) => `${v.file}:${v.line} ${v.rule}`)).toEqual([]);
  });

  it("WEB_3a_static_no_transition_animation_keyframes_raf_or_interval", () => {
    const banned =
      /\btransition\b|\banimation\b|@keyframes|requestAnimationFrame|cancelAnimationFrame|setInterval|\.animate\s*\(/;
    expect(appCode.filter((p) => banned.test(code(p))).map(appRel)).toEqual([]);
  });

  it("WEB_3a_static_the_only_real_timer_is_setTimeout_in_store_ts", () => {
    const withTimer = appTs.filter((p) => /\bsetTimeout\b/.test(code(p))).map(appRel);
    expect(withTimer).toEqual(["store.ts"]);
    expect(code(join(APP, "store.ts"))).toMatch(/\bclearTimeout\b/);
  });
});

describe("WEB_3a_static: code hygiene", () => {
  it("WEB_3a_static_no_window_global_is_assigned", () => {
    const hits = appCode.flatMap((p) =>
      code(p)
        .split(/\r?\n/)
        .map((line, i) => ({ file: appRel(p), line: i + 1, text: line.trim() }))
        .filter((l) => WINDOW_ASSIGN.some((re) => re.test(l.text)))
        .map((l) => `${l.file}:${l.line} ${l.text}`),
    );
    expect(hits).toEqual([]);
  });

  it("WEB_3a_static_no_any_no_ts_ignore_no_raw_html_no_dynamic_code", () => {
    const bad = {
      any: /:\s*any\b|\bas\s+any\b|<any>|\bany\[\]|Array<any>|Record<[^>]*\bany\b/,
      tsIgnore: /@ts-ignore|@ts-nocheck/,
      html: /dangerouslySetInnerHTML|\.innerHTML\s*=|\binsertAdjacentHTML\b/,
      dyn: /\beval\s*\(|new\s+Function\s*\(/,
    };
    for (const [name, re] of Object.entries(bad)) {
      expect(appTs.filter((p) => re.test(text(p))).map(appRel), name).toEqual([]);
    }
  });

  it("WEB_3a_static_no_model_id_and_no_support_js", () => {
    expect(appCode.filter((p) => MODEL_ID.test(text(p))).map(appRel)).toEqual([]);
    expect(appFiles.filter((p) => /support\.js/i.test(text(p))).map(appRel)).toEqual([]);
  });

  it("WEB_3a_static_css_in_park_app_is_scoped_to_data_park", () => {
    for (const p of appFiles.filter((f) => f.endsWith(".css"))) {
      const selectorLines = code(p)
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => /[,{]$/.test(l) && !l.startsWith("@"));
      for (const sel of selectorLines) expect(sel, appRel(p)).toMatch(/^\[data-park\]/);
    }
  });
});

describe("WEB_3a_static: pages never read the address bar", () => {
  it("WEB_3a_static_only_router_ts_reads_window_location_or_history_under_park", () => {
    const hits = walk(PARK)
      .filter((p) => /\.tsx?$/.test(p))
      .filter((p) => rel(PARK, p) !== "app/router.ts")
      .filter((p) =>
        /\bwindow\s*\.\s*location\b|\bdocument\s*\.\s*location\b|\bwindow\s*\.\s*history\b|\bhistory\s*\.\s*(?:push|replace)State\b|\blocation\s*\.\s*(?:pathname|search|href|hash)\b/.test(
          code(p),
        ),
      )
      .map((p) => rel(PARK, p));
    expect(hits).toEqual([]);
  });
});

describe("WEB_3a_static: imports", () => {
  const importsOf = (p: string): string[] =>
    [...code(p).matchAll(/(?:\bfrom|\bimport)\s*\(?\s*["']([^"']+)["']/g)].map((m) => m[1] ?? "");

  it("WEB_3a_static_park_app_imports_only_park_react_and_the_shared_seams", () => {
    const bad: string[] = [];
    for (const p of appTs) {
      for (const spec of importsOf(p)) {
        if (!spec.startsWith(".")) {
          if (!/^react(\/|$)|^react-dom(\/|$)/.test(spec)) bad.push(`${appRel(p)} imports ${spec}`);
          continue;
        }
        const target = resolve(dirname(p), spec);
        if (target.startsWith(PARK)) continue;
        const inSrc = rel(SRC, target);
        const ok =
          inSrc === "router" ||
          inSrc === "api" ||
          inSrc.startsWith("api/") ||
          inSrc.startsWith("design/tilo-t/"); // TILO-T-FOUNDATION: tokens, motion and the doodle gutter
        if (!ok) bad.push(`${appRel(p)} imports ${spec}`);
      }
    }
    expect(bad).toEqual([]);
  });

  it("WEB_3a_static_from_src_router_only_usePathname_and_navigateFlow", () => {
    for (const p of appTs) {
      for (const m of code(p).matchAll(
        /import\s*\{([^}]*)\}\s*from\s*["']((?:\.\.\/)+router)["']/g,
      )) {
        const names = (m[1] ?? "")
          .split(",")
          .map((s) => s.trim().replace(/^type\s+/, ""))
          .filter(Boolean);
        for (const n of names) {
          expect(["usePathname", "navigateFlow"], `${appRel(p)} imports ${n}`).toContain(n);
        }
      }
    }
  });

  it("WEB_3a_static_ParkApp_imports_the_tokens_and_the_component_styles", () => {
    const src = code(join(APP, "ParkApp.tsx"));
    expect(src).toMatch(/import\s+["']\.\.\/tokens\/park\.css["']/);
    expect(src).toMatch(
      // QA-DEMO-1 M2: NotFound moved to ./NotFound, which is what imports the components barrel
      /from\s+["']\.\.\/components(?:\/index)?["']|\.\.\/components\/park\.components\.css|from\s+["']\.\/NotFound["']/,
    );
  });
});

describe("WEB_3a_static: the mount point keeps the landing bundle free of the park app (NFR-01)", () => {
  const rootSrc = () => code(join(SRC, "Root.tsx"));
  const mainSrc = () => code(join(SRC, "main.tsx"));
  const staticImports = (src: string): string[] =>
    [...src.matchAll(/^\s*import\s+(?!\()[^;]*?from\s*["']([^"']+)["']/gm)].map((m) => m[1] ?? "");

  it("WEB_3a_static_Root_lazy_imports_ParkApp_with_a_dynamic_import", () => {
    expect(rootSrc()).toMatch(/import\(\s*["']\.\/park\/app\/ParkApp["']\s*\)/);
    expect(rootSrc()).toMatch(/\blazy\s*\(/);
    expect(rootSrc()).toMatch(/<Suspense\b/);
  });

  it("WEB_3a_static_no_static_import_of_ParkApp_or_anything_in_park_but_the_pure_router", () => {
    for (const src of [rootSrc(), mainSrc()]) {
      const parkImports = staticImports(src).filter((s) => /(^|\/)park(\/|$)/.test(s));
      // the pure router, and the pure redirect table for retired bookmarks (adminRedirect)
      for (const spec of parkImports)
        expect(["./park/app/router", "./park/app/adminRedirect"]).toContain(spec);
    }
  });

  it("WEB_3a_static_Root_uses_the_shared_usePathname_and_has_no_old_app", () => {
    expect(rootSrc()).toMatch(/\busePathname\b/);
    // OLD-UI-OUT Final: the old app and its kept-address predicate are deleted; Root loads only Park
    expect(rootSrc()).not.toMatch(/\bisKeptPath\b|keptPaths|import\(\s*["']\.\/App["']\s*\)/);
  });

  it("WEB_3a_static_main_still_renders_through_Root_with_the_old_boot_steps", () => {
    const src = text(join(SRC, "main.tsx"));
    expect(src).toMatch(/from\s*["']\.\/Root["']/);
    expect(src).toMatch(/<Root\s*\/>/);
    expect(src).toContain("initDensity()");
    expect(src).toContain("document.fonts.load");
    expect(src).toContain('import "./styles/app.css"');
  });

  it("WEB_3a_static_apps_web_CLAUDE_md_is_not_edited_by_this_ticket", () => {
    let porcelain = "";
    try {
      porcelain = execFileSync("git", ["status", "--porcelain", "--", "apps/web/CLAUDE.md"], {
        cwd: WEB,
        encoding: "utf8",
      });
    } catch {
      return; // no git here: nothing to compare
    }
    expect(porcelain.trim()).toBe("");
  });
});
