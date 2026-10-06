// WEB-2 test support: a small reader for apps/web/src/park/components/park.components.css.
// It understands comments, rules, selector lists and @media/@supports nesting, and answers one question:
// "which declarations apply to an element with these classes (and this pseudo-state)?".
//
// Convention the stylesheet must follow so this reader can see it (pinned in the WEB-2 report):
// - every selector is `[data-park] <compound>` where the compound is `.class.class...` plus an optional
//   pseudo suffix (`:hover`, `:focus-visible`, `:disabled`); a bare `[data-park] :focus-visible` is fine;
// - no descendant or child combinators for anything the spec table pins (use modifier classes instead);
// - literal values, not component-local custom properties (`height: 42px`, not `height: var(--h)`);
// - shorthands as the README writes them (`padding: 0 18px`, `border: 1px solid var(--line)`).
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./css";
import { PARK_DIR } from "./prototype";

export const COMPONENTS_DIR = path.join(PARK_DIR, "components");
export const COMPONENTS_CSS = path.join(COMPONENTS_DIR, "park.components.css");

export interface CssRule {
  /** One selector of the rule's list, whitespace collapsed. */
  readonly selector: string;
  readonly decls: ReadonlyMap<string, string>;
}

export interface OtherAtRule {
  readonly head: string;
}

export function readComponentsCss(): string {
  return fs.readFileSync(COMPONENTS_CSS, "utf8");
}

function splitTop(s: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of s) {
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (ch === sep && depth === 0) {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

function parseDecls(body: string): Map<string, string> {
  const decls = new Map<string, string>();
  for (const d of splitTop(body, ";")) {
    const colon = d.indexOf(":");
    if (colon < 0) continue;
    const name = d.slice(0, colon).trim().toLowerCase();
    if (!name) continue;
    decls.set(
      name,
      d
        .slice(colon + 1)
        .trim()
        .replace(/\s+/g, " "),
    );
  }
  return decls;
}

/** Every plain rule, in file order, with @media and @supports bodies flattened in. `others` lists the
 * at-rules that are neither (keyframes, font-face, import ...), so a test can forbid them. */
export function parseRules(css: string): { rules: CssRule[]; others: OtherAtRule[] } {
  const src = stripComments(css);
  const rules: CssRule[] = [];
  const others: OtherAtRule[] = [];
  const walk = (text: string): void => {
    let i = 0;
    while (i < text.length) {
      const open = text.indexOf("{", i);
      const semi = text.indexOf(";", i);
      if (semi >= 0 && (open < 0 || semi < open) && text.slice(i, semi).trim().startsWith("@")) {
        others.push({ head: text.slice(i, semi).trim() });
        i = semi + 1;
        continue;
      }
      if (open < 0) break;
      const head = text.slice(i, open).trim();
      let depth = 1;
      let j = open + 1;
      while (j < text.length && depth > 0) {
        if (text[j] === "{") depth++;
        else if (text[j] === "}") depth--;
        j++;
      }
      const body = text.slice(open + 1, j - 1);
      if (/^@(media|supports)\b/i.test(head)) walk(body);
      else if (head.startsWith("@")) others.push({ head });
      else {
        const decls = parseDecls(body);
        for (const sel of splitTop(head, ",")) {
          const selector = sel.trim().replace(/\s+/g, " ");
          if (selector) rules.push({ selector, decls });
        }
      }
      i = j;
    }
  };
  walk(src);
  return { rules, others };
}

export interface Compound {
  readonly classes: readonly string[];
  /** Everything after the classes: pseudo-classes, attribute selectors. Empty for a plain class compound. */
  readonly rest: string;
}

/** `[data-park] .a.b:hover` -> { classes: [a, b], rest: ":hover" }; null when the selector is not of
 * that form (no `[data-park]` prefix, or it has a combinator). */
export function compoundOf(selector: string): Compound | null {
  if (!selector.startsWith("[data-park]")) return null;
  const tail = selector.slice("[data-park]".length).trim();
  if (/[\s>+~]/.test(tail.replace(/\([^)]*\)/g, "").replace(/\[[^\]]*\]/g, ""))) return null;
  const m = /^\*?((?:\.[\w-]+)*)(.*)$/.exec(tail);
  if (!m) return null;
  const classes = (m[1] ?? "").split(".").filter(Boolean);
  return { classes, rest: m[2] ?? "" };
}

/** `[data-park] .a .b:hover` -> { ancestor: {classes: [a]}, target: {classes: [b], rest: ":hover"} }: exactly one
 * descendant combinator between two class compounds, nothing else. Null for any other shape. */
export function descendantOf(selector: string): { ancestor: Compound; target: Compound } | null {
  if (!selector.startsWith("[data-park]")) return null;
  const tail = selector.slice("[data-park]".length).trim();
  if (/[>+~]/.test(tail)) return null;
  const parts = tail.split(/\s+/);
  if (parts.length !== 2) return null;
  const parse = (t: string): Compound | null => {
    const m = /^\*?((?:\.[\w-]+)*)(.*)$/.exec(t);
    return m ? { classes: (m[1] ?? "").split(".").filter(Boolean), rest: m[2] ?? "" } : null;
  };
  const ancestor = parse(parts[0] ?? "");
  const target = parse(parts[1] ?? "");
  return ancestor && target ? { ancestor, target } : null;
}

/** Declarations that apply to an element carrying exactly `classes`, merged in file order (later wins; no
 * specificity). `state` "" is the resting state (rules with no pseudo suffix); ":hover" or ":focus-visible"
 * selects the rules whose suffix contains it (those declarations only, not merged over the base).
 * `ancestors` are the classes of an ancestor element (a tone modifier on a tile, say): rules of the form
 * `.ancestor .target` then apply too. With no ancestors, descendant rules never match. */
export function declsFor(
  rules: readonly CssRule[],
  classes: readonly string[],
  state = "",
  ancestors: readonly string[] = [],
): Map<string, string> {
  const have = new Set(classes);
  const above = new Set(ancestors);
  const merged = new Map<string, string>();
  const fits = (c: Compound): boolean =>
    c.classes.every((k) => have.has(k)) && (state === "" ? c.rest === "" : c.rest.includes(state));
  for (const r of rules) {
    const c = compoundOf(r.selector);
    if (c) {
      if (!fits(c)) continue;
    } else if (ancestors.length > 0) {
      const d = descendantOf(r.selector);
      if (!d || d.ancestor.rest !== "" || !d.ancestor.classes.every((k) => above.has(k))) continue;
      if (!fits(d.target)) continue;
    } else continue;
    for (const [k, v] of r.decls) merged.set(k, v);
  }
  return merged;
}

/** Whitespace, case, hex and leading-zero normalisation, so `#FFF`, `#ffffff` and `0.16` vs `.16` agree. */
export function norm(v: string | undefined): string {
  if (v === undefined) return "";
  return v
    .trim()
    .toLowerCase()
    .replace(/\s*!important$/, "")
    .replace(/\s+/g, " ")
    .replace(/\s*,\s*/g, ",")
    .replace(/#([0-9a-f])([0-9a-f])([0-9a-f])\b/g, "#$1$1$2$2$3$3")
    .replace(/\b0px\b/g, "0")
    .replace(/\b0\./g, ".");
}

/** The first of `names` that is declared, normalised (`background` falls back to `background-color`). */
export function pick(decls: ReadonlyMap<string, string>, ...names: string[]): string {
  for (const n of names) {
    const v = decls.get(n);
    if (v !== undefined) return norm(v);
  }
  return "";
}

/** Every number in a value, in order: `0 18px` -> [0, 18]; `16px 18px` -> [16, 18]. */
export function numbers(v: string): number[] {
  return [...v.matchAll(/-?\d*\.?\d+/g)].map((m) => Number.parseFloat(m[0]));
}
