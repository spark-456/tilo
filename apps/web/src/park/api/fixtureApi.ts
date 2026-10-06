// The fixture Api (WEB-1a): serves the typed sample data with `source: "fixture"`. Reads hand out
// copies, so a caller can never change the shared fixtures. `decide` and `undo` act on this
// instance's own `dec`; started worlds are counted per instance. Writes are acknowledged, nothing more.
import * as fx from "./fixtures";
import type { Api } from "./index";
import type { Ack, ApiResult, Dec, DecisionKey } from "./types";

const ok = <T>(data: T): Promise<ApiResult<T>> =>
  Promise.resolve({ data: structuredClone(data), source: "fixture" });
const ack = (): Promise<ApiResult<Ack>> => ok({ ok: true });

export function createFixtureApi(): Api {
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
    startWorld: (mode, query) => {
      started += 1;
      return ok({ ok: true as const, world: fx.makeWorld(mode, query, started) });
    },
    saveSkill: ack,
    setToolLevel: ack,
    bookSlot: ack,
    addBackup: ack,
    setPref: ack,
  };
}
