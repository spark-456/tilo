// @vitest-environment happy-dom
// TILO-T-FOUNDATION (owner priority 16 Oct; HR-1 to HR-7, PRD 9.4): the shared Tilo T base. Tokens exist in both themes, every
// keyframe of the design is defined 1:1, the reduced-motion rule is present, Icon draws every name, Buddy every mood, the three
// states render, the doodle gutter is wide-screen-only and outside the column, and nothing logs a console error.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Buddy, TILO_MOODS, type TiloRole } from "./Buddy";
import { DoodleGutter } from "./DoodleGutter";
import { Icon } from "./Icon";
import { EmptyState, ErrorState, type LoadingLayout, LoadingState } from "./States";
import { ICON_NAMES, ICON_PATHS } from "./iconPaths";
import { useInView, usePauseWhenHidden } from "./loops";
import { EASING, EASING_VAR } from "./motion";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const HERE = __dirname;
const REPO = join(HERE, "..", "..", "..", "..", "..");
const read = (...p: string[]) => readFileSync(join(...p), "utf8");
const css = (f: string) => read(HERE, f);
const spec = (f: string) => read(REPO, "design", "tilo-t", f);
const flat = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\s+/g, "");

let host: HTMLDivElement;
let errors: unknown[][];
beforeEach(() => {
  errors = [];
  vi.spyOn(console, "error").mockImplementation((...a: unknown[]) => {
    errors.push(a);
  });
  host = document.createElement("div");
  document.body.appendChild(host);
});
afterEach(() => {
  host.remove();
  vi.restoreAllMocks();
});

function render(node: React.ReactNode): HTMLDivElement {
  const root = createRoot(host);
  act(() => root.render(node));
  return host;
}

describe("TILO_T_FOUNDATION tokens", () => {
  const tokens = css("tokens.css");
  const block = (sel: RegExp) => {
    const m = sel.exec(tokens);
    if (!m) throw new Error(`no block for ${sel}`);
    return m[1] as string;
  };
  const light = block(/\[data-theme="studio"\]\{([^}]*)\}/);
  const dark = block(/\[data-theme="studioDark"\],\[data-theme="studio"\]\[data-time="night"\]\{([^}]*)\}/);
  const vars = (b: string) => new Map([...b.matchAll(/(--[\w-]+):([^;]+);?/g)].map((m) => [m[1], (m[2] as string).trim()]));

  it("TILO_T_FOUNDATION_tokens_exist_in_both_themes", () => {
    const need = [
      "--bg", "--card", "--sunk", "--ink", "--ink2", "--ink3", "--line", "--line2", "--pri", "--onPri", "--lime", "--amber",
      "--red", "--sh1", "--sh2", "--sh3", "--mono", "--fH", "--fB", "--bp", "--bpLine", "--bpInk", "--cityGround", "--road",
      "--hover", "--sel", "--sceneFx",
    ];
    for (const [name, b] of [["studio", light], ["studioDark", dark]] as const) {
      const v = vars(b);
      for (const k of need) expect(v.has(k), `${name} lacks ${k}`).toBe(true);
    }
  });

  it("TILO_T_FOUNDATION_ink_is_0B0B0C_and_accent_lime_C8F23A", () => {
    expect(vars(light).get("--ink")).toBe("#0B0B0C");
    expect(vars(light).get("--lime")).toBe("#C8F23A");
    expect(vars(dark).get("--pri")).toBe("#C8F23A");
  });

  it("TILO_T_FOUNDATION_values_match_the_design_export", () => {
    const daylight = spec("tilo-daylight.css");
    const t = spec("tilo-t.css");
    const from = (src: string, name: string) => {
      const m = new RegExp(`\\[data-theme="${name}"\\]\\{([^}]*)\\}`).exec(src);
      return vars(m?.[1] ?? "");
    };
    const pairs: [string, Map<string | undefined, string>][] = [
      ["studio", vars(light)],
      ["studioDark", vars(dark)],
    ];
    for (const [name, ours] of pairs) {
      const want = new Map([...from(daylight, name), ...from(t, name), ...from(spec("tilo-studio.css"), name)]);
      for (const [k, v] of want) {
        if (k === "--fH" || k === "--fB" || k === "--mono" || k === "color-scheme") continue; // our font stack names the packaged faces
        const key = k === "--ground" ? "--cityGround" : k; // Park owns --ground
        // the design lists the export's url() doodle in tilo-t.css; ours lives in doodles.css
        if (k === "--doodle") continue;
        expect(ours.get(key), `${name} ${key}`).toBe(v);
      }
    }
  });

  it("TILO_T_FOUNDATION_fonts_are_geist_and_geist_mono", () => {
    expect(css("fonts.ts")).toContain("@fontsource/geist-sans/400.css");
    expect(css("fonts.ts")).toContain("@fontsource/geist-mono/400.css");
    expect(vars(light).get("--fB")).toMatch(/Geist/);
    expect(vars(light).get("--mono")).toMatch(/Geist Mono/);
  });

  it("TILO_T_FOUNDATION_tokens_css_has_no_motion", () => {
    expect(tokens).not.toMatch(/@keyframes|animation|transition/);
  });
});

describe("TILO_T_FOUNDATION motion", () => {
  const motion = css("motion.css");
  const kfs = (src: string) =>
    new Map(
      [...src.matchAll(/@keyframes\s+(\w+)\s*(\{(?:[^{}]|\{[^{}]*\})*\})/g)].map((m) => [m[1], flat(m[2] as string)]),
    );

  it("TILO_T_FOUNDATION_every_keyframe_of_tilo_t_css_and_tilo_studio_css_is_defined_1to1", () => {
    const ours = kfs(motion);
    for (const f of ["tilo-t.css", "tilo-studio.css"]) {
      const theirs = kfs(spec(f));
      expect(theirs.size).toBeGreaterThan(40);
      for (const [name, body] of theirs) {
        expect(ours.has(name), `@keyframes ${name} (${f}) is missing`).toBe(true);
        expect(ours.get(name), `@keyframes ${name} differs`).toBe(body);
      }
    }
  });

  it("TILO_T_FOUNDATION_easing_tokens_are_css_custom_properties_and_ts_constants", () => {
    expect(EASING).toEqual({
      standard: "cubic-bezier(.2,.8,.2,1)",
      walk: "cubic-bezier(.45,0,.2,1)",
      leap: "cubic-bezier(.5,0,.5,1)",
    });
    expect(motion).toContain(`--tt-ease-standard:${EASING.standard}`);
    expect(motion).toContain(`--tt-ease-walk:${EASING.walk}`);
    expect(motion).toContain(`--tt-ease-leap:${EASING.leap}`);
    expect(EASING_VAR.walk).toBe("var(--tt-ease-walk)");
  });

  it("TILO_T_FOUNDATION_reduced_motion_rule_is_present_and_loops_stop", () => {
    const m = /@media \(prefers-reduced-motion:reduce\)\{([\s\S]*?)\n\.tt-bd/.exec(motion);
    expect(m, "no prefers-reduced-motion block").not.toBeNull();
    const rule = flat(m?.[1] ?? "");
    expect(rule).toContain("animation-duration:.01ms!important");
    expect(rule).toContain("animation-iteration-count:1!important");
    expect(rule).toContain("transition:opacity.2s!important");
    expect(flat(motion)).toContain(".tt-bd,.tt-bd*,.tt-shim,.tt-dotsspan{animation:none!important}");
    expect(flat(motion)).toContain('[data-motion="still"].tt-bd');
  });

  it("TILO_T_FOUNDATION_only_transform_opacity_filter_are_animated_by_our_classes", () => {
    const own = motion.slice(motion.indexOf("Component motion classes"));
    expect(own).not.toMatch(/\b(?:left|top|width|height|margin)\s*:/);
  });
});

describe("TILO_T_FOUNDATION loop pausing", () => {
  function Probe() {
    const hidden = usePauseWhenHidden();
    return <i data-hidden={String(hidden)} />;
  }
  it("TILO_T_FOUNDATION_usePauseWhenHidden_follows_visibilitychange", () => {
    let hiddenNow = false;
    vi.spyOn(document, "hidden", "get").mockImplementation(() => hiddenNow);
    render(<Probe />);
    expect(host.querySelector("i")?.getAttribute("data-hidden")).toBe("false");
    hiddenNow = true;
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(host.querySelector("i")?.getAttribute("data-hidden")).toBe("true");
    expect(errors).toEqual([]);
  });

  it("TILO_T_FOUNDATION_useInView_follows_an_intersection_observer", () => {
    let cb: IntersectionObserverCallback = () => undefined;
    class IO {
      constructor(c: IntersectionObserverCallback) {
        cb = c;
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal("IntersectionObserver", IO);
    function V() {
      const ref = { current: null as HTMLElement | null };
      return (
        <b
          ref={(el) => {
            ref.current = el;
          }}
        >
          <W r={ref} />
        </b>
      );
    }
    function W({ r }: { r: { current: HTMLElement | null } }) {
      const v = useInView(r);
      return <i data-in={String(v)} />;
    }
    render(<V />);
    expect(host.querySelector("i")?.getAttribute("data-in")).toBe("true");
    act(() => cb([{ isIntersecting: false } as IntersectionObserverEntry], {} as IntersectionObserver));
    vi.unstubAllGlobals();
    expect(errors).toEqual([]);
  });
});

describe("TILO_T_FOUNDATION icons", () => {
  const src = spec("tilo-t.js");
  const names = [...src.slice(src.indexOf("const P={"), src.indexOf("const C=")).matchAll(/^ (\w+):'/gm)].map((m) => m[1]);

  it("TILO_T_FOUNDATION_Icon_names_equal_the_design_set", () => {
    expect(names.length).toBeGreaterThanOrEqual(60);
    expect([...ICON_NAMES].sort()).toEqual([...(names as string[])].sort());
  });

  it("TILO_T_FOUNDATION_Icon_renders_every_name_on_a_24px_grid_with_1_8_stroke", () => {
    for (const n of ICON_NAMES) {
      const el = document.createElement("div");
      act(() => createRoot(el).render(<Icon name={n} size={24} />));
      const svg = el.querySelector("svg");
      expect(svg?.getAttribute("viewBox"), n).toBe("0 0 24 24");
      expect(svg?.getAttribute("stroke-width"), n).toBe("1.8");
      expect(svg?.getAttribute("stroke-linecap"), n).toBe("round");
      expect(svg?.getAttribute("aria-hidden"), n).toBe("true");
      expect(svg?.querySelector("path")?.getAttribute("d"), n).toBe(ICON_PATHS[n]);
    }
    expect(errors).toEqual([]);
  });

  it("TILO_T_FOUNDATION_Icon_with_a_title_is_an_image_for_screen_readers", () => {
    render(<Icon name="check" title="Done" />);
    const svg = host.querySelector("svg");
    expect(svg?.getAttribute("role")).toBe("img");
    expect(svg?.getAttribute("aria-label")).toBe("Done");
    expect(svg?.getAttribute("aria-hidden")).toBeNull();
  });
});

describe("TILO_T_FOUNDATION Buddy", () => {
  it("TILO_T_FOUNDATION_Buddy_renders_every_mood", () => {
    expect([...TILO_MOODS].sort()).toEqual(
      ["hand", "happy", "idle", "listen", "sad", "swim", "talk", "think", "work"].sort(),
    );
    for (const mood of TILO_MOODS) {
      const el = document.createElement("div");
      act(() => createRoot(el).render(<Buddy mood={mood} size={128} />));
      const bd = el.querySelector(".tt-bd");
      expect(bd?.getAttribute("data-mood"), mood).toBe(mood);
      expect(bd?.getAttribute("aria-hidden"), mood).toBe("true");
      expect(bd?.querySelectorAll(".tt-bd__armL, .tt-bd__armR").length, mood).toBe(2);
      // think shows the three dots; happy and swim draw smiling eyes instead of the blinking pair
      expect(bd?.querySelectorAll(".tt-bd__dots span").length, mood).toBe(mood === "think" ? 3 : 0);
      expect(bd?.querySelectorAll(".tt-bd__eye").length, mood).toBe(mood === "happy" || mood === "swim" ? 0 : 2);
    }
    expect(errors).toEqual([]);
  });

  it("TILO_T_FOUNDATION_Buddy_static_poses_are_inline_so_reduced_motion_shows_a_pose", () => {
    const tf = (mood: (typeof TILO_MOODS)[number]) => {
      const el = document.createElement("div");
      act(() => createRoot(el).render(<Buddy mood={mood} />));
      return [".tt-bd__armL", ".tt-bd__armR"].map((s) => (el.querySelector(s) as HTMLElement).style.transform);
    };
    expect(tf("hand")).toEqual(["rotate(8deg)", "rotate(-170deg)"]);
    expect(tf("happy")).toEqual(["rotate(155deg)", "rotate(-150deg)"]);
    expect(tf("idle")).toEqual(["rotate(8deg)", "rotate(-8deg)"]);
  });

  it("TILO_T_FOUNDATION_Buddy_loops_are_classes_in_motion_css_and_stop_when_still", () => {
    const motion = flat(css("motion.css"));
    for (const m of ["talk", "work", "hand", "happy", "swim"]) expect(motion).toContain(`.tt-bd[data-mood="${m}"]`);
    expect(motion).toContain(".tt-bd__bob{animation:tsBobvar(--tt-bob,3.2s)");
    expect(motion).toContain("animation:tHand1.6sease-in-outinfinite");
    expect(flat(read(HERE, "Buddy.tsx"))).not.toMatch(/animation\w*:|transition\w*:/);
  });

  it("TILO_T_FOUNDATION_Buddy_renders_every_role_in_its_colour", () => {
    const roles: TiloRole[] = ["director", "research", "builder", "tester", "browser", "connector", "delivery", "designer", "finance"];
    const seen = new Set<string>();
    for (const role of roles) {
      const el = document.createElement("div");
      act(() => createRoot(el).render(<Buddy role={role} />));
      expect(el.querySelector(".tt-bd")?.getAttribute("data-role")).toBe(role);
      seen.add(el.innerHTML);
    }
    expect(seen.size).toBe(roles.length);
  });
});

describe("TILO_T_FOUNDATION shared states", () => {
  it("TILO_T_FOUNDATION_EmptyState_renders_title_body_and_actions", () => {
    render(<EmptyState title="No worlds yet" body="Describe some work." action={<button type="button">Start</button>} />);
    expect(host.querySelector("h2")?.textContent).toBe("No worlds yet");
    expect(host.textContent).toContain("Describe some work.");
    expect(host.querySelector("button")?.textContent).toBe("Start");
    expect(host.querySelector(".tt-bd")).not.toBeNull();
    expect(errors).toEqual([]);
  });

  it("TILO_T_FOUNDATION_ErrorState_is_an_alert_with_a_sad_helper_and_a_code", () => {
    render(<ErrorState title="Could not load" body="Try again." code="HTTP 503" />);
    const e = host.querySelector('[role="alert"]');
    expect(e).not.toBeNull();
    expect(e?.querySelector(".tt-bd")?.getAttribute("data-mood")).toBe("sad");
    expect(e?.textContent).toContain("HTTP 503");
    expect(errors).toEqual([]);
  });

  it("TILO_T_FOUNDATION_LoadingState_renders_every_layout_busy_with_a_caption", () => {
    const layouts: LoadingLayout[] = ["grid", "list", "split", "calendar", "world", "chat"];
    for (const layout of layouts) {
      const el = document.createElement("div");
      act(() => createRoot(el).render(<LoadingState layout={layout} caption="Loading worlds" />));
      const s = el.querySelector('[role="status"]');
      expect(s?.getAttribute("aria-busy"), layout).toBe("true");
      expect(s?.getAttribute("data-layout"), layout).toBe(layout);
      expect(s?.textContent, layout).toContain("Loading worlds");
      expect(el.querySelectorAll(".tt-sk").length, layout).toBeGreaterThan(0);
    }
    expect(errors).toEqual([]);
  });

  it("TILO_T_FOUNDATION_state_styles_hold_no_motion", () => {
    expect(css("states.css")).not.toMatch(/@keyframes|animation|transition/);
  });
});

describe("TILO_T_FOUNDATION doodle gutter", () => {
  it("TILO_T_FOUNDATION_gutter_is_decorative_wide_screens_only_and_outside_the_column", () => {
    render(<DoodleGutter />);
    const g = host.querySelector(".tt-doodles");
    expect(g?.getAttribute("aria-hidden")).toBe("true");
    const d = css("doodles.css");
    expect(d).toMatch(/\.tt-doodles\{display:none\}/);
    expect(d).toMatch(/@media \(min-width:1200px\)/);
    expect(d).toContain("mask-image:linear-gradient(to right");
    expect(d).toContain("var(--tt-column)");
    expect(d).toContain("pointer-events:none");
    expect(d).not.toMatch(/@keyframes|animation|transition/);
    expect(read(HERE, "assets", "tilo-doodles.svg")).toContain('stroke="#0B0B0C"');
    expect(read(HERE, "assets", "tilo-doodles-dark.svg")).toContain('stroke="#F4F4F2"');
  });
});

describe("TILO_T_FOUNDATION docs and licence", () => {
  it("TILO_T_FOUNDATION_doc_is_at_most_40_lines_and_names_the_trigger_rule", () => {
    const md = read(HERE, "..", "TILO-T.md");
    expect(md.trimEnd().split("\n").length).toBeLessThanOrEqual(40);
    expect(md).toMatch(/trigger event/);
    expect(md).toMatch(/support\.js/);
  });

  it("TILO_T_FOUNDATION_licences_record_design_tilo_t_as_our_own_export", () => {
    const l = read(REPO, "docs", "licences.md");
    expect(l).toMatch(/design\/tilo-t/);
    expect(l).toMatch(/our own Claude Design export/);
  });

  it("TILO_T_FOUNDATION_support_js_is_never_imported", () => {
    for (const f of ["Buddy.tsx", "Icon.tsx", "States.tsx", "styles.ts", "index.ts", "DoodleGutter.tsx", "loops.ts", "motion.ts"]) {
      expect(read(HERE, f), f).not.toMatch(/support\.js|from ["'][^"']*design\/tilo-t\/support/);
    }
  });
});
