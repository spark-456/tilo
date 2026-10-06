// WEB-PARITY: computed-style comparison of a region's root elements (design-critic reads styles first).
export const STYLE_PROPS = [
  "fontSize",
  "fontWeight",
  "lineHeight",
  "color",
  "backgroundColor",
  "borderRadius",
  "padding",
  "gap",
] as const;

export interface StyleNode {
  /** `tag` plus the first words of its own text, for the report. */
  label: string;
  tag: string;
  styles: Record<string, string>;
}
export interface StyleDiff {
  region: string;
  element: string;
  prop: string;
  design: string;
  ours: string;
}

/** The properties that differ between two same-position nodes lists; a length or tag mismatch is one row. */
export function compareStyles(region: string, design: StyleNode[], ours: StyleNode[]): StyleDiff[] {
  const out: StyleDiff[] = [];
  if (design.length !== ours.length) {
    out.push({
      region,
      element: "(structure)",
      prop: "element count",
      design: String(design.length),
      ours: String(ours.length),
    });
  }
  for (let i = 0; i < Math.min(design.length, ours.length); i++) {
    const [d, o] = [design[i], ours[i]];
    if (!d || !o) continue;
    if (d.tag !== o.tag) {
      out.push({ region, element: d.label, prop: "tag", design: d.tag, ours: o.tag });
      continue;
    }
    for (const prop of STYLE_PROPS) {
      if (d.styles[prop] !== o.styles[prop]) {
        out.push({
          region,
          element: d.label,
          prop,
          design: d.styles[prop] ?? "",
          ours: o.styles[prop] ?? "",
        });
      }
    }
  }
  return out;
}
