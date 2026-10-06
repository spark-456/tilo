// The Park City sample data (WEB-1a): the prototype's `TiloApp.data`, typed. Every value is fixed at
// September 2026; nothing here reads a clock. Data files are generated (scripts/park-fixtures.mjs).
export const gbp = (v: number): string =>
  `£${v < 100 && v % 1 ? v.toFixed(2) : Math.round(v).toLocaleString("en-GB")}`;

import type { Agenda, Decision } from "../types";
import { agendaRules, decisionFacts } from "./additive";
import { agenda as generatedAgenda } from "./agenda";
import { decisions as generatedDecisions } from "./decisions";

/** The prototype's Agenda plus the additive `rules` (additive.ts). */
export const agenda: Agenda = { ...generatedAgenda, rules: agendaRules };
/** The prototype's decisions plus the additive `facts` (additive.ts). */
export const decisions: Decision[] = generatedDecisions.map((d) => ({
  ...d,
  facts: decisionFacts[d.k],
}));

export { connectors } from "./connectors";
export { learn } from "./learn";
export { ledger } from "./ledger";
export { notifications } from "./notifications";
export { skills } from "./skills";
export { team } from "./team";
export { LEVELS, TIERS } from "./tiers";
export { today, user } from "./user";
export { makeWorld, needsLeft, plans, worlds } from "./worlds";
