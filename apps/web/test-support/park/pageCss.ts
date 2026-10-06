// Park page test support (WEB-10, reusable by every page ticket): what a page stylesheet plus the core
// component stylesheet plus an element's inline style declare for one rendered element, without a browser.
// happy-dom does not load CSS imported by a component, so this reads the files from disk and matches rules
// the way the park convention writes them: `[data-park] .a.b` or `[data-park] .a .b` (descendant: loose,
// any ancestor), no attribute or pseudo suffix on the target (those are states, not the resting style).
// Later rules win; specificity is ignored. Real computed values are checked in the Playwright specs.
import fs from "node:fs";
import { COMPONENTS_CSS, type CssRule, norm, parseRules } from "./componentsCss";

export type Decls = Map<string, string>;

/** The rules of one stylesheet file on disk (empty list when the file does not exist yet). */
export function rulesOf(file: string): CssRule[] {
  if (!fs.existsSync(file)) return [];
  return parseRules(fs.readFileSync(file, "utf8")).rules;
}

interface Part {
  tag: string;
  classes: string[];
  rest: string;
}

function parts(selector: string): Part[] | null {
  if (/[>+~]/.test(selector.replace(/\([^)]*\)/g, "").replace(/\[[^\]]*\]/g, ""))) return null;
  const tail = selector.replace(/^\[data-park\]\s*/, "");
  const out: Part[] = [];
  for (const raw of tail.split(/\s+/).filter(Boolean)) {
    const m = /^([a-z][a-z0-9]*)?((?:\.[\w-]+)*)(.*)$/i.exec(raw);
    if (!m) return null;
    out.push({
      tag: (m[1] ?? "").toLowerCase(),
      classes: (m[2] ?? "").split(".").filter(Boolean),
      rest: m[3] ?? "",
    });
  }
  return out.length > 0 ? out : null;
}

const fits = (p: Part, el: Element): boolean =>
  (p.tag === "" || el.tagName.toLowerCase() === p.tag) &&
  p.classes.every((c) => el.classList.contains(c));

function inline(el: Element): Decls {
  const out: Decls = new Map();
  for (const d of (el.getAttribute("style") ?? "").split(";")) {
    const i = d.indexOf(":");
    if (i > 0) out.set(d.slice(0, i).trim().toLowerCase(), d.slice(i + 1).trim());
  }
  return out;
}

/** Declarations that apply to `el`: components sheet, then the given page rules, then inline style. */
export function declared(el: Element, pageRules: readonly CssRule[]): Decls {
  const merged: Decls = new Map();
  for (const r of [...rulesOf(COMPONENTS_CSS), ...pageRules]) {
    const ps = parts(r.selector);
    const target = ps?.[ps.length - 1];
    if (!ps || !target || target.rest !== "" || !fits(target, el)) continue;
    let up = el.parentElement;
    let ok = true;
    for (let i = ps.length - 2; i >= 0 && ok; i--) {
      const need = ps[i] as Part;
      while (up && !fits(need, up)) up = up.parentElement;
      if (!up) ok = false;
      else up = up.parentElement;
    }
    if (!ok) continue;
    for (const [k, v] of r.decls) merged.set(k, v);
  }
  for (const [k, v] of inline(el)) merged.set(k, v);
  return merged;
}

/** One declared property of `el`, normalised ("" when nothing declares it). */
export function dv(el: Element, pageRules: readonly CssRule[], prop: string): string {
  return norm(declared(el, pageRules).get(prop));
}

/** [row-gap, column-gap] in px from `gap`, `row-gap`, `column-gap` (NaN when not declared). */
export function gaps(el: Element, pageRules: readonly CssRule[]): [number, number] {
  const d = declared(el, pageRules);
  const g = (d.get("gap") ?? "").match(/-?\d*\.?\d+/g)?.map(Number) ?? [];
  const row = d.has("row-gap") ? Number.parseFloat(d.get("row-gap") ?? "") : (g[0] ?? Number.NaN);
  const col = d.has("column-gap")
    ? Number.parseFloat(d.get("column-gap") ?? "")
    : (g[1] ?? g[0] ?? Number.NaN);
  return [row, col];
}
