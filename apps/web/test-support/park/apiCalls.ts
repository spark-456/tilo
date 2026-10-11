// WEB-1a test support: one valid call (arguments) per Api method, typed against the Api interface.
// A new method added to API_METHODS and the Api type fails to compile here until it has an entry,
// and fails the "every method is covered" tests at runtime, so it cannot ship without a live stub.
import type { Api, ApiMethod } from "../../src/park/api";
import * as fx from "../../src/park/api/fixtures";

export type CallTable = { [K in ApiMethod]: Parameters<Api[K]> };

export const DEC_COMBOS = [
  { depot: false, mail: false },
  { depot: true, mail: false },
  { depot: false, mail: true },
  { depot: true, mail: true },
] as const;

export function callTable(): CallTable {
  const skill = fx.skills[0];
  const slot = fx.agenda.slots[0];
  if (!skill || !slot) throw new Error("fixtures must hold at least one skill and one agenda slot");
  const added = [fx.makeWorld("quick", "Compare three suppliers", 1)];
  return {
    getUser: [],
    getToday: [],
    getDecisions: [],
    getWorlds: [{ depot: true, mail: false }, added],
    getPlans: [{ depot: false, mail: true }],
    getSkills: [],
    getLearn: [],
    getLedger: [],
    getAgenda: [],
    getTeam: [],
    getConnectors: [],
    getNotifications: [],
    getTeamPolicy: [],
    getConnectorTerms: [],
    getProfileSettings: [],
    decide: ["depot"],
    undo: ["depot"],
    startWorld: ["workspace", "Plan the offsite"],
    saveSkill: [skill],
    setToolLevel: ["email", 2],
    bookSlot: [slot],
    addBackup: ["ps"],
    setPref: ["backup", "ps"],
    submitFeedback: ["Honest words."],
  };
}

/** Invoke a method with its table arguments. A synchronous throw is returned, not thrown, so the
 * "returns a Promise" check can see it. */
export function invoke(api: Api, method: ApiMethod, args: CallTable = callTable()): unknown {
  const fn = api[method] as (...a: unknown[]) => unknown;
  try {
    return fn.apply(api, args[method] as unknown[]);
  } catch (e) {
    return { syncThrow: e };
  }
}
