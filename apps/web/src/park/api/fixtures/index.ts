// The Park City sample data (WEB-1a): the prototype's `TiloApp.data`, typed. Every value is fixed at
// September 2026; nothing here reads a clock. Data files are generated (scripts/park-fixtures.mjs).
export const gbp = (v: number): string =>
  `£${v < 100 && v % 1 ? v.toFixed(2) : Math.round(v).toLocaleString("en-GB")}`;

export { agenda } from "./agenda";
export { connectors } from "./connectors";
export { connectorTerms } from "./connectorTerms";
export { decisions } from "./decisions";
export { learn } from "./learn";
export { ledger } from "./ledger";
export { notifications } from "./notifications";
export { profileSettings } from "./profileSettings";
export { skills } from "./skills";
export { team } from "./team";
export { teamPolicy } from "./teamPolicy";
export { LEVELS, TIERS } from "./tiers";
export { today, user } from "./user";
export { makeWorld, needsLeft, plans, worlds } from "./worlds";
