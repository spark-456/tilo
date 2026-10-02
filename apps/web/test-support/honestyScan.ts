// FR-WLD-09 (PRD 9.4 HR-1 to HR-3): the rules and allowlist behind the static check
// src/honesty/animation.static.test.ts. Nothing in the app may start motion except the
// choreographer (src/world/choreographer.ts), which plays recorded events, queues per actor and caps
// movement at 2 s. This module is test support: it is never bundled.

export interface Rule {
  readonly id: string;
  readonly kinds: readonly ("ts" | "css")[];
  readonly pattern: RegExp;
  readonly why: string;
}

export const RULES: readonly Rule[] = [
  {
    id: "raf",
    kinds: ["ts"],
    pattern: /\b(?:request|cancel)AnimationFrame\b/,
    why: "A frame loop is motion the choreographer does not know about (HR-3).",
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
    pattern: /\.animate\s*\(/,
    why: "Element.animate starts motion with no recorded event (HR-1).",
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
      /from\s+["'](?:gsap|animejs?|popmotion|motion|framer-motion|@tweenjs\/tween\.js|@react-spring\/[\w-]+|react-spring|react-transition-group)["']/,
    why: "A tween library animates outside the choreographer (HR-3).",
  },
  {
    id: "inline-motion-style",
    kinds: ["ts"],
    pattern: /\b(?:transition|animation)(?:[A-Z]\w*)?\s*:/,
    why: "Inline transition or animation styles move things with no event (HR-1).",
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
    kinds: ["css"],
    pattern: /@keyframes\b/,
    why: "Keyframes define motion that is not tied to a recorded event (HR-1).",
  },
  {
    id: "css-animation",
    kinds: ["css"],
    pattern: /(?:^|[\s{;])animation(?:-[a-z-]+)?\s*:/,
    why: "CSS animation can loop with no event (HR-2).",
  },
  {
    id: "css-transition",
    kinds: ["css"],
    pattern: /(?:^|[\s{;])transition(?:-[a-z-]+)?\s*:/,
    why: "CSS transitions move UI that no event asked to move (HR-1).",
  },
  {
    id: "css-smooth-scroll",
    kinds: ["css"],
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
];

export interface Violation {
  readonly file: string;
  readonly line: number;
  readonly rule: string;
  readonly text: string;
}

/** Removes comments but keeps line numbers (`//` after a colon or quote is left alone: URLs). */
function stripComments(code: string, kind: "ts" | "css"): string {
  const blocks = code.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "));
  return kind === "css" ? blocks : blocks.replace(/(?<![:"'`\\])\/\/.*$/gm, "");
}

/** Every rule that matches `code`, with line numbers. `file` is the repo-relative path. */
export function scanSource(file: string, code: string): Violation[] {
  const kind = file.endsWith(".css") ? "css" : "ts";
  const out: Violation[] = [];
  stripComments(code, kind)
    .split("\n")
    .forEach((text, i) => {
      for (const r of RULES) {
        if (r.kinds.includes(kind) && r.pattern.test(text)) {
          out.push({ file, line: i + 1, rule: r.id, text: text.trim().slice(0, 80) });
        }
      }
    });
  return out;
}
