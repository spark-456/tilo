export type TiloRole =
  | "director"
  | "research"
  | "builder"
  | "tester"
  | "browser"
  | "connector"
  | "delivery"
  | "designer"
  | "finance";

export const ROLE_COLOR: Readonly<Record<TiloRole, string>> = {
  director: "#E8643F",
  research: "#3F7FE0",
  builder: "#E57F3E",
  tester: "#C9982A",
  browser: "#2BA3B8",
  connector: "#D9588C",
  delivery: "#76A035",
  designer: "#A45DB8",
  finance: "#3E9A7C",
};

export const roleColor = (role: TiloRole): string => ROLE_COLOR[role];
