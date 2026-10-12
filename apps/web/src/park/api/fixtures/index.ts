// The Park City sample data (WEB-1a): the prototype's `TiloApp.data`, typed. Every value is fixed at
// September 2026; nothing here reads a clock. Data files are generated (scripts/park-fixtures.mjs).
export const gbp = (v: number): string =>
  `£${v < 100 && v % 1 ? v.toFixed(2) : Math.round(v).toLocaleString("en-GB")}`;

import type { Agenda, Decision, Ledger } from "../types";
import {
  HELPER_SUMMARY_FIXTURE,
  agendaRules,
  decisionFacts,
  ledgerCopy,
  ledgerMemoryUp,
} from "./additive";
import { agenda as generatedAgenda } from "./agenda";
import { decisions as generatedDecisions } from "./decisions";
import { ledger as generatedLedger } from "./ledger";

export { HELPER_SUMMARY_FIXTURE };

/** The prototype's Agenda plus the additive `rules` (additive.ts). */
export const agenda: Agenda = { ...generatedAgenda, rules: agendaRules };
/** The prototype's decisions plus the additive `facts` (additive.ts). */
export const decisions: Decision[] = generatedDecisions.map((d) => ({
  ...d,
  facts: decisionFacts[d.k],
}));
/** The prototype's Ledger plus the additive `memoryUp` and designed copy (additive.ts). */
export const ledger: Ledger = {
  ...generatedLedger,
  memoryUp: ledgerMemoryUp,
  spike: ledgerCopy.spike,
  runLabels: ledgerCopy.runLabels,
  memoryWeeks: ledgerCopy.memoryWeeks,
  waits: { ...generatedLedger.waits, ...ledgerCopy.waits },
};

export { buildHandoffs } from "./buildHandoff";
export { connectors } from "./connectors";
export { connectorTerms } from "./connectorTerms";
export { learn } from "./learn";
export { notifications } from "./notifications";
export { profileSettings } from "./profileSettings";
export { skills } from "./skills";
export { team } from "./team";
export { teamPolicy } from "./teamPolicy";
export { LEVELS, TIERS } from "./tiers";
export { today, user } from "./user";
export { makeWorld, needsLeft, plans, worlds } from "./worlds";
