import { API_METHODS, type Api, type ApiMethod } from "./index";
// Stale-while-revalidate for the live Api's page reads (owner report: every visit loaded everything fresh).
// A read seen before for the same signed-in person answers at once with what it last got; when that answer is older
// than FRESH_MS the same read also runs in the background and, if the data changed, `onChange` tells the app to
// re-read (pages re-run their load effect against the new answer, and the page keeps showing the old data until it
// lands). Only answers the server gave (`source: "live"`) are kept, never fixtures or failures. The cache lives in
// memory, keyed by the person's email: nothing is written to storage, nothing crosses users, and any write the
// person makes clears it, so a page never shows a decision or setting that was just changed as it was before.
import { carryOneStep } from "./oneStep";
import { carryQuizReader } from "./quizApps";
import { carryResultReader } from "./results";
import { carrySkillFixer } from "./skillFixes";
import type { ApiResult } from "./types";

/** The reads a page makes when it opens. `getUser` and `getToday` are answered locally, so they are not kept. */
const READS: readonly ApiMethod[] = [
  "getDecisions",
  "getWorlds",
  "getPlans",
  "getSkills",
  "getLearn",
  "getLedger",
  "getAgenda",
  "getTeam",
  "getTeamLive",
  "getConnectors",
  "getNotifications",
  "getTeamPolicy",
  "getConnectorTerms",
  "getProfileSettings",
  "getUserSettings",
  "getBuildHandoff",
];
const LOCAL: readonly ApiMethod[] = ["getUser", "getToday"];

/** An answer younger than this is returned as it is, with no background read. */
export const FRESH_MS = 5_000;

type AnyCall = (...args: unknown[]) => Promise<ApiResult<unknown>>;
interface Entry {
  readonly at: number;
  readonly json: string;
  readonly result: ApiResult<unknown>;
}

/** A new `Api` object with the same methods, so identity-keyed readers (results, quizzes, skill fixes, the one-step
 * start) carry over. A page whose load effect lists the api re-runs when it gets the new object. */
export function copyApi(api: Api): Api {
  const next = { ...api } as Api;
  carryResultReader(api, carrySkillFixer(api, carryOneStep(api, carryQuizReader(api, next))));
  return next;
}

export function withSwr(
  api: Api,
  who: () => string | null,
  onChange: () => void,
  now: () => number = Date.now,
): Api {
  const cache = new Map<string, Entry>();
  const revalidating = new Set<string>();
  let owner = who();
  const out = { ...api } as unknown as Record<ApiMethod, AnyCall>;
  const calls = api as unknown as Record<ApiMethod, AnyCall>;
  const forgetAll = () => cache.clear();

  for (const method of READS) {
    out[method] = (...args) => {
      const person = who();
      if (person !== owner) {
        forgetAll();
        owner = person;
      }
      let key: string;
      try {
        key = `${method}|${JSON.stringify(args)}`;
      } catch {
        return calls[method](...args);
      }
      const load = (): Promise<ApiResult<unknown>> =>
        calls[method](...args).then((result) => {
          if (result.source === "live" && who() === person) {
            const json = JSON.stringify(result.data);
            const before = cache.get(key);
            cache.set(key, { at: now(), json, result });
            if (before && before.json !== json) onChange();
          }
          return result;
        });
      const hit = person ? cache.get(key) : undefined;
      if (!hit) return load();
      if (now() - hit.at >= FRESH_MS && !revalidating.has(key)) {
        revalidating.add(key);
        void load()
          .catch(() => undefined) // the stale answer stands; the next visit tries again
          .finally(() => revalidating.delete(key));
      }
      return Promise.resolve(hit.result);
    };
  }
  for (const method of API_METHODS) {
    if (READS.includes(method) || LOCAL.includes(method)) continue;
    out[method] = (...args) => {
      forgetAll(); // a write follows: nothing read before it is shown as current again
      return calls[method](...args).finally(forgetAll);
    };
  }
  return copyFrom(api, out as unknown as Api);
}

function copyFrom(from: Api, to: Api): Api {
  carryResultReader(from, carrySkillFixer(from, carryOneStep(from, carryQuizReader(from, to))));
  return to;
}
