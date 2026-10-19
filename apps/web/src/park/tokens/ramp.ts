// The Park type ramp (WEB-1a; BQ-WEB-4): the README "Typography" table as plain data, pinned by
// ramp.test.ts. The design's sizes win on Park pages, which differ from PRD 18.2. Sizes are px.
export type RampKey =
  | "pageTitle"
  | "sectionTitle"
  | "cardTitle"
  | "detailTitle"
  | "kpiValue"
  | "body"
  | "rowTitle"
  | "meta"
  | "eyebrow"
  | "logo";

type Num = number | [number, number];

export interface TypeSpec {
  family: "Nunito" | "Nunito Sans";
  weight: Num;
  size: Num;
  letterSpacing?: number;
  lineHeight?: number;
  uppercase?: true;
}

export const TYPE_RAMP: Record<RampKey, TypeSpec> = {
  pageTitle: { family: "Nunito", weight: 900, size: 36, letterSpacing: -0.8, lineHeight: 1.05 },
  sectionTitle: { family: "Nunito", weight: 900, size: 24, letterSpacing: -0.4 },
  cardTitle: { family: "Nunito Sans", weight: 800, size: [17, 18] },
  detailTitle: { family: "Nunito Sans", weight: 800, size: 22, letterSpacing: -0.3 },
  kpiValue: { family: "Nunito Sans", weight: 800, size: 28, letterSpacing: -0.6 },
  body: { family: "Nunito Sans", weight: 600, size: [14.5, 15.5], lineHeight: 1.45 },
  rowTitle: { family: "Nunito Sans", weight: 800, size: 14.5 },
  meta: { family: "Nunito Sans", weight: [600, 700], size: [12.5, 13] },
  eyebrow: { family: "Nunito Sans", weight: 800, size: 12, letterSpacing: 0.6, uppercase: true },
  logo: { family: "Nunito", weight: 900, size: 27, letterSpacing: -0.5 },
};
