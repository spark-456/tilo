// WEB-1a test support: a tiny CSS reader for the token files. It understands comments, top-level
// rules and at-rules (with nested braces); that is all tokens.css and park.css contain.

export interface CssBlock {
  /** Selector text with whitespace removed and quotes normalised to ", e.g. [data-time="night"]. */
  selector: string;
  atRule: boolean;
  body: string;
}

export function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

export function normSelector(sel: string): string {
  return sel.replace(/\s+/g, "").replace(/'/g, '"');
}

export function parseBlocks(css: string, normalizeSelectors = true): CssBlock[] {
  const src = stripComments(css);
  const out: CssBlock[] = [];
  let i = 0;
  while (i < src.length) {
    const open = src.indexOf("{", i);
    if (open < 0) break;
    const head = src.slice(i, open).trim();
    let depth = 1;
    let j = open + 1;
    while (j < src.length && depth > 0) {
      if (src[j] === "{") depth++;
      else if (src[j] === "}") depth--;
      j++;
    }
    out.push({
      selector: normalizeSelectors ? normSelector(head) : head,
      atRule: head.startsWith("@"),
      body: src.slice(open + 1, j - 1),
    });
    i = j;
  }
  return out;
}

/** Custom properties (--name: value) of a declaration body; values have whitespace collapsed. */
export function customProps(body: string): Map<string, string> {
  const props = new Map<string, string>();
  for (const decl of body.split(";")) {
    const colon = decl.indexOf(":");
    if (colon < 0) continue;
    const name = decl.slice(0, colon).trim();
    if (!name.startsWith("--")) continue;
    props.set(
      name,
      decl
        .slice(colon + 1)
        .trim()
        .replace(/\s+/g, " "),
    );
  }
  return props;
}

/** Merged custom properties of every plain rule whose selector list is exactly `selector`. */
export function propsFor(css: string, selector: string): Map<string, string> {
  const merged = new Map<string, string>();
  for (const b of parseBlocks(css)) {
    if (b.atRule || b.selector !== normSelector(selector)) continue;
    for (const [k, v] of customProps(b.body)) merged.set(k, v);
  }
  return merged;
}
