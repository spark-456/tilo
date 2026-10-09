// The fixture Api (WEB-1a): serves the typed sample data with `source: "fixture"`. Reads hand out
// copies, so a caller can never change the shared fixtures. `decide` and `undo` act on this
// instance's own `dec`; started worlds are counted per instance. Writes are acknowledged, nothing more.
import * as fx from "./fixtures";
import type { Api } from "./index";
import type { Ack, ApiResult, Dec, DecisionKey, QuickReply, TierKey } from "./types";

/** The fixture's Quick answer: plainly a sample, with no cost (nothing was spent). */
export const SAMPLE_QUICK =
  "This is a sample answer. No model was asked, and your question was not sent anywhere.";

const ok = <T>(data: T): Promise<ApiResult<T>> =>
  Promise.resolve({ data: structuredClone(data), source: "fixture" });
const ack = (): Promise<ApiResult<Ack>> => ok({ ok: true });

export function createFixtureApi(): Omit<Api, "getProfileSettings"> & {
  getProfileSettings(): Promise<ApiResult<typeof fx.profileSettings>>;
} {
  let dec: Dec = {};
  let started = 0;
  const set = (key: DecisionKey, on: boolean) => {
    dec = { ...dec, [key]: on };
    return ok({ ok: true as const, dec });
  };
  return {
    getUser: () => ok(fx.user),
    getToday: () => ok(fx.today),
    getDecisions: () => ok(fx.decisions),
    getWorlds: (d, added) => ok(fx.worlds(d, added)),
    getPlans: (d) => ok(fx.plans(d)),
    getSkills: () => ok(fx.skills),
    getLearn: () => ok(fx.learn),
    getLedger: () => ok(fx.ledger),
    getAgenda: () => ok(fx.agenda),
    getTeam: () => ok(fx.team),
    getConnectors: () => ok(fx.connectors),
    getNotifications: () => ok(fx.notifications),
    getTeamPolicy: () => ok(fx.teamPolicy),
    getConnectorTerms: () => ok(fx.connectorTerms),
    getProfileSettings: () => ok(fx.profileSettings),
    decide: (key) => set(key, true),
    undo: (key) => set(key, false),
    startWorld: ((mode: TierKey, query: string, effort?: string) => {
      // Quick (COST-FAST-1) makes no world; the fixture answers with a sample, never as if a model had been asked.
      if (effort === "quick")
        return ok<QuickReply>({ kind: "answered", text: SAMPLE_QUICK, cost: null });
      started += 1;
      return ok({ ok: true as const, world: fx.makeWorld(mode, query, started) });
    }) as Api["startWorld"],
    saveSkill: ack,
    // The sample card runs on its own fixture steps and never calls these; they hold nothing to show.
    captureSkill: () => ok({ id: "sample", steps: [] }),
    proposeVersion: () => ok({ steps: [], question: null, estimates: null }),
    setToolLevel: ack,
    bookSlot: ack,
    addBackup: ack,
    setPref: ack,
  };
}
