// WEB-PARITY: the nine Park pages, where the design shows each and where ours lives.
export interface PageSpec {
  name: string;
  /** Hash on `Tilo App.dc.html` (the design's own deep link, README "Routes"). */
  designHash: string;
  /** Route on our app server. */
  path: string;
}

const page = (name: string, suffix = ""): PageSpec => ({
  name,
  designHash: `${name}${suffix}`,
  path: `/park/${name}${suffix}`,
});

// The World page is only reachable with a world id; k1 is the City in the design's data.
export const PAGES: PageSpec[] = [
  page("home"),
  page("worlds"),
  page("world", "/k1"),
  page("skills"),
  page("ledger"),
  page("agenda"),
  page("team"),
  page("profile"),
  page("connectors"),
];

export const VIEWPORTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "390", width: 390, height: 844 },
] as const;
export const THEMES = ["day", "night"] as const;
export type Theme = (typeof THEMES)[number];
