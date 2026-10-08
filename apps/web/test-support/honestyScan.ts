// FR-WLD-09 (PRD 9.4 HR-1 to HR-3): the rules and allowlist behind the static check
// src/honesty/animation.static.test.ts. Nothing in the app may start motion except the
// choreographer (src/world/choreographer.ts), which plays recorded events, queues per actor and caps
// movement at 2 s. This module is test support: it is never bundled.
//
// Known limit: a self-rescheduling setTimeout loop is not flagged (runWorld.ts and fixtureClient.ts
// legitimately schedule replay that way, so a rule would need an allowlist as long as the code).

export interface Rule {
  readonly id: string;
  /** Where it applies. "ts" also covers html <script>; "css" also covers html <style> and style
   * attributes, and, for the rules that list both, CSS held in a template literal in .ts/.tsx. */
  readonly kinds: readonly ("ts" | "css")[];
  readonly pattern: RegExp;
  readonly why: string;
}

export const RULES: readonly Rule[] = [
  {
    id: "raf",
    kinds: ["ts"],
    pattern: /\b(?:request|cancel)(?:AnimationFrame|IdleCallback)\b/,
    why: "A frame or idle-time loop is motion the choreographer does not know about (HR-3).",
  },
  {
    id: "interval",
    kinds: ["ts"],
    pattern: /\bsetInterval\s*\(/,
    why: "A repeating timer is how an idle animation implying work gets built (HR-2).",
  },
  {
    id: "waapi",
    kinds: ["ts"],
    pattern: /\.\s*animate\s*\(/,
    why: "Element.animate starts motion with no recorded event (HR-1).",
  },
  {
    id: "waapi-bracket",
    kinds: ["ts"],
    pattern: /\[\s*["'`]animate["'`]\s*\]/,
    why: "Element['animate'] is Element.animate spelled to dodge a search (HR-1).",
  },
  {
    id: "pixi-ticker",
    kinds: ["ts"],
    pattern: /\b(?:Ticker|sharedTicker|AnimatedSprite)\b|\.ticker\b/,
    why: "A Pixi ticker is an always-on loop (HR-2); the stage draws on demand.",
  },
  {
    id: "tween-library",
    kinds: ["ts"],
    pattern:
      /\b(?:from|import|require)\s*\(?\s*["'](?:gsap|animejs?|popmotion|motion|framer-motion|@tweenjs\/tween\.js|@react-spring\/[\w-]+|react-spring|react-transition-group)(?:\/[^"']*)?["']/,
    why: "A tween library animates outside the choreographer (HR-3).",
  },
  {
    id: "inline-motion-style",
    kinds: ["ts"],
    pattern: /\b(?:transition|animation)(?:[A-Z]\w*)?\s*:/,
    why: "Inline transition or animation styles move things with no event (HR-1).",
  },
  {
    id: "style-assign-motion",
    kinds: ["ts"],
    pattern:
      /\.style\s*\.\s*(?:transition|animation)\w*\s*=(?!=)|\.style\s*\[\s*["'](?:transition|animation)|setProperty\s*\(\s*["'](?:transition|animation)/,
    why: "Setting a transition or animation on element.style starts motion with no event (HR-1).",
  },
  {
    id: "smooth-scroll-js",
    kinds: ["ts"],
    pattern: /\bbehavior\s*:\s*["']smooth["']/,
    why: "scrollTo and scrollIntoView with smooth behaviour are timed motion (HR-3).",
  },
  {
    id: "smil",
    kinds: ["ts"],
    pattern: /<animate(?:Transform|Motion)?\b/,
    why: "SVG SMIL animation runs on its own (HR-2).",
  },
  {
    id: "view-transition",
    kinds: ["ts", "css"],
    pattern: /startViewTransition|view-transition-name|@view-transition/,
    why: "View transitions animate the page with no recorded event (HR-1).",
  },
  {
    id: "css-keyframes",
    kinds: ["css", "ts"],
    pattern: /@keyframes\b/,
    why: "Keyframes define motion that is not tied to a recorded event (HR-1).",
  },
  {
    id: "css-animation",
    kinds: ["css", "ts"],
    pattern: /(?:^|[\s{;"'`])animation(?:-[a-z-]+)?\s*:/,
    why: "CSS animation can loop with no event (HR-2).",
  },
  {
    id: "css-transition",
    kinds: ["css", "ts"],
    pattern: /(?:^|[\s{;"'`])transition(?:-[a-z-]+)?\s*:/,
    why: "CSS transitions move UI that no event asked to move (HR-1).",
  },
  {
    id: "css-smooth-scroll",
    kinds: ["css", "ts"],
    pattern: /scroll-behavior\s*:\s*smooth/,
    why: "Smooth scrolling is timed motion outside the choreographer (HR-3).",
  },
];

/** Packages whose only job is animation: none may be a dependency of apps/web. */
export const BANNED_PACKAGES =
  /^(?:gsap|animejs?|popmotion|motion|framer-motion|@tweenjs\/tween\.js|react-spring|@react-spring\/.+|react-transition-group|lottie-web|@lottiefiles\/.+|@pixi\/.*(?:spine|animate).*|pixi-spine)$/;

export interface AllowEntry {
  readonly file: string;
  readonly rule: string;
  readonly reason: string;
}

/** The whole list of animation uses outside choreographer.ts, each with its reason. Keep it small. */
export const ALLOWLIST: readonly AllowEntry[] = [
  {
    file: "src/world/runWorld.ts",
    rule: "raf",
    reason:
      "Runs the choreographer's clock: one frame per advance, scheduled only while a recorded event's move is in flight, then stops (HR-2, HR-3). World content moves only through the choreographer.",
  },
  {
    file: "src/stage/Stage.tsx",
    rule: "raf",
    reason:
      "Camera glide: the person's own pan or zoom key, never an event. One frame per eased step, ends on the target, and is instant under reduced motion (HR-2; PRD 9.7).",
  },
  // The Park city backdrop (WEB-MOTION-1, BQ-WEB-3 decided by the user 6 Oct 2026, ADR-0003a 5): its cars and
  // walkers are ambient scenery: anonymous pedestrians drawn with agent-style art, with no run state, label or
  // link to any run. Nothing that shows Tilo's own agents, worlds or data animates here
  // (src/honesty/park-ambient.allowlist.test.ts pins that); agents animate only from recorded events.
  {
    file: "src/park/engines/park.ts",
    rule: "inline-motion-style",
    reason:
      "Ambient scenery only: the Park city's cars and anonymous pedestrians (drawn with agent-style art) carry looping keyframes (transform and opacity), with no run state, label or link to any run. Agents animate only from recorded events (HR-1).",
  },
  {
    file: "src/park/engines/park.ts",
    rule: "css-animation",
    reason:
      "Same ambient scenery as above, written as the animation shorthand: cars and anonymous agent-styled pedestrians that stand for no run, drawn frozen when still. Agent motion comes only from recorded events (HR-1).",
  },
  // The Park shell's own chrome (WEB-MOTION-2): the boot splash, the page change, the progress bar and the world
  // card. It moves because a person opened the app, clicked a tab or opened a world, never because of an agent or
  // a run state (src/honesty/park-transitions.allowlist.test.ts pins how narrow these entries stay).
  {
    file: "src/park/shell/park.shell.css",
    rule: "css-keyframes",
    reason:
      "Keyframes of the Park shell. The city's ambient scenery, cars and anonymous pedestrians drawn with agent-style art that stand for no run (mvXY, waddle, walkFrame), and non-agent UI chrome that moves when a person acts: the boot splash's bar and fade and the world loader's ring and card fade (tiloSlide, tiloSpin, tiloFade). Transform and opacity only. Agents animate only from recorded events (HR-1).",
  },
  {
    file: "src/park/shell/park.shell.css",
    rule: "css-animation",
    reason:
      "Ambient city scenery and non-agent UI chrome. animation-play-state pauses the city's anonymous cars and pedestrians (they stand for no run) under the veil and in a hidden tab. The boot splash's sliding bar and fade and the world loader's spinning ring and card fade are chrome motion started by a click or by app state (the app booting, a world card opening); the loader card's text ('Waking N agents', step checks, a 30/60/90/100 fill) is a fixed timer ceremony started by a click and is not tied to any run state; the ring only spins while it is up. Reduced motion turns them off. Agents animate only from recorded events (HR-1).",
  },
  {
    file: "src/park/shell/park.shell.css",
    rule: "css-transition",
    reason:
      "UI chrome only, non-agent: the page change fade and slide, the top progress bar and its fill, the enter fade of a toast, popover or menu, and pointer-only hover and press feedback on controls and on page cards, tiles, pins and events under the page outlet (a lift or a press; it carries no run or decision state), plus the slide of a control's thumb or knob. Each starts from a person's pointer or click or from the UI state that click set (menu open, toast shown, switch on), and animates transform and opacity only, never a layout property; reduced motion and the still preference turn them off. Nothing here shows or implies an agent, a run or a decision; agents animate only from recorded events (HR-1).",
  },
];

export interface Violation {
  readonly file: string;
  readonly line: number;
  readonly rule: string;
  readonly text: string;
}

type Kind = "ts" | "css";

const KEYWORDS_BEFORE_REGEX = new Set([
  "return",
  "typeof",
  "case",
  "do",
  "else",
  "in",
  "of",
  "void",
  "delete",
  "throw",
  "new",
  "await",
  "yield",
]);

/**
 * Blanks every comment (keeping newlines, so line numbers hold) and leaves strings, template
 * literals and regexes in place: rules must still see `el["animate"]` or CSS in a template. It walks
 * the text once, so a `//` or `/*` inside a string, template or regex is not a comment, and code
 * after it is still scanned. JSX text is not parsed: an unclosed quote in it ends at the line end.
 */
function blankComments(code: string, kind: Kind): string {
  const ts = kind === "ts";
  const out = code.split("");
  const n = code.length;
  const blank = (from: number, to: number) => {
    for (let k = from; k < to; k++) if (out[k] !== "\n") out[k] = " ";
  };
  const braces: string[] = []; // "{" or "${" (a template expression), innermost last
  let i = 0;

  const quoted = (q: string) => {
    i++;
    while (i < n && code[i] !== q && code[i] !== "\n") i += code[i] === "\\" ? 2 : 1;
    i++;
  };
  /** Reads template text from `i` until the closing backtick or the next `${`. */
  const template = () => {
    while (i < n) {
      const c = code[i];
      if (c === "\\") i += 2;
      else if (c === "`") {
        i++;
        return;
      } else if (c === "$" && code[i + 1] === "{") {
        braces.push("${");
        i += 2;
        return;
      } else i++;
    }
  };
  /** True when a `/` at `i` starts a regex literal rather than a division or a JSX closing tag. */
  const startsRegex = () => {
    if (code[i + 1] === ">") return false;
    let j = i - 1;
    while (j >= 0 && /\s/.test(out[j] ?? "")) j--;
    if (j < 0) return true;
    const ch = out[j] ?? "";
    if (/[\w$]/.test(ch)) {
      let k = j;
      while (k > 0 && /[\w$]/.test(out[k - 1] ?? "")) k--;
      return KEYWORDS_BEFORE_REGEX.has(out.slice(k, j + 1).join(""));
    }
    return !/[)\]"'`<]/.test(ch);
  };
  const regex = () => {
    const start = i;
    let inClass = false;
    i++;
    while (i < n && code[i] !== "\n") {
      const c = code[i];
      if (c === "\\") i++;
      else if (c === "[") inClass = true;
      else if (c === "]") inClass = false;
      else if (c === "/" && !inClass) {
        i++;
        return;
      }
      i++;
    }
    i = start + 1; // no closing slash on the line: it was not a regex
  };

  while (i < n) {
    const c = code[i];
    const d = code[i + 1];
    if (c === "/" && d === "*") {
      const end = code.indexOf("*/", i + 2);
      const to = end < 0 ? n : end + 2;
      blank(i, to);
      i = to;
    } else if (c === "/" && d === "/" && ts) {
      const end = code.indexOf("\n", i);
      const to = end < 0 ? n : end;
      blank(i, to);
      i = to;
    } else if (c === '"' || c === "'") quoted(c);
    else if (ts && c === "`") {
      i++;
      template();
    } else if (ts && c === "/" && startsRegex()) regex();
    else if (ts && c === "{") {
      braces.push("{");
      i++;
    } else if (ts && c === "}") {
      i++;
      if (braces.pop() === "${") template();
    } else i++;
  }
  return out.join("");
}

/** The parts of an html file that hold code: style blocks and attributes as css, scripts as ts. */
function htmlParts(html: string): { kind: Kind; text: string }[] {
  const text = html.replace(/<!--[\s\S]*?-->/g, (m) => m.replace(/[^\n]/g, " "));
  const blanked = text.replace(/[^\n]/g, " ");
  // Each part is the whole file blanked except the code span, so line numbers hold.
  const blocks = (kind: Kind, re: RegExp) =>
    [...text.matchAll(re)].map((m) => {
      const [from, to] = m.indices?.[1] ?? [0, 0];
      return { kind, text: blanked.slice(0, from) + text.slice(from, to) + blanked.slice(to) };
    });
  return [
    ...blocks("css", /<style\b[^>]*>([\s\S]*?)<\/style>/dgi),
    ...blocks("ts", /<script\b[^>]*>([\s\S]*?)<\/script>/dgi),
    ...blocks("css", /\sstyle\s*=\s*"([^"]*)"/dgi),
    ...blocks("css", /\sstyle\s*=\s*'([^']*)'/dgi),
  ];
}

function scanText(file: string, original: string, text: string, kind: Kind): Violation[] {
  const lines = original.split("\n");
  const out: Violation[] = [];
  for (const r of RULES) {
    if (!r.kinds.includes(kind)) continue;
    for (const m of text.matchAll(new RegExp(r.pattern.source, "gm"))) {
      const line = text.slice(0, m.index).split("\n").length;
      out.push({ file, line, rule: r.id, text: (lines[line - 1] ?? "").trim().slice(0, 80) });
    }
  }
  return out;
}

/** Every rule that matches `code`, with line numbers. `file` is the repo-relative path. */
export function scanSource(file: string, code: string): Violation[] {
  if (file.endsWith(".html")) {
    return htmlParts(code).flatMap((p) =>
      scanText(file, code, blankComments(p.text, p.kind), p.kind),
    );
  }
  const kind: Kind = file.endsWith(".css") ? "css" : "ts";
  return scanText(file, code, blankComments(code, kind), kind);
}
