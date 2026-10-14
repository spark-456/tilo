import { createFixtureApi } from "./fixtureApi";
import type { Api } from "./index";
import { API_METHODS } from "./index";
import { type Identity, NotBuilt, createLiveApi, todayOf, userOf } from "./liveApi";
// Which Api the Park pages use (WEB-1a; plan section 6.1). No VITE_TILO_API_URL (or a blank one) means
// the fixture Api; a url means the live Api (getLedger reads GET /costs; the other methods reject with
// NotBuilt until each endpoint exists), so a configured deployment never shows sample numbers. Same switch as src/api/config.ts (chooseClient).
// LIVE-HOME: a demo (anonymous) session on a configured deployment reads the fixture company instead, labelled as sample
// and with no request (the server only replays for a demo session); a signed-in person gets the live Api plus who they
// are, from the sign-in session.
import { carryOneStep } from "./oneStep";
import { carryQuizReader } from "./quizApps";
import { carrySkillFixer } from "./skillFixes";
import type { ApiResult } from "./types";

export interface SessionView {
  /** True for a demo (anonymous) session. */
  demo: () => boolean;
  identity: () => Identity | null;
  /** The clock (park/api reads none itself). */
  now: () => Date;
}

export function parkApi(
  env: { VITE_TILO_API_URL?: string | undefined },
  appCheckToken?: () => Promise<string | null>,
  authToken?: () => Promise<string | null>,
): Api {
  const baseUrl = env.VITE_TILO_API_URL?.trim();
  // SEC-10, SEC-15: the live Api gets the App Check and sign-in getters (never asked in fixture mode).
  return baseUrl ? createLiveApi({ baseUrl, appCheckToken, authToken }) : createFixtureApi();
}

/** LIVE-HOME: the live Api for one signed-in session. A demo session reads the fixture Api (no request); a Google
 * person reads the live Api, with `getUser` and `getToday` answered from the sign-in session and the clock. */
export function withSession(live: Api, who: SessionView): Api {
  const fixture = createFixtureApi();
  const pick = (): Api => (who.demo() ? fixture : live);
  const calls = API_METHODS.map((m) => [
    m,
    (...args: unknown[]) => (pick()[m] as (...a: unknown[]) => unknown)(...args),
  ]);
  const api = Object.fromEntries(calls) as unknown as Api;
  const demoOr = <T>(
    fromLive: () => Promise<ApiResult<T>>,
    fromFixture: () => Promise<ApiResult<T>>,
  ) => (who.demo() ? fromFixture() : fromLive());
  api.getUser = () =>
    demoOr(
      async () => {
        const id = who.identity();
        const user = id ? userOf(id) : null;
        if (!user) throw new NotBuilt("getUser");
        return { data: user, source: "live" as const };
      },
      () => fixture.getUser(),
    );
  api.getToday = () =>
    demoOr(
      async () => ({ data: todayOf(who.now()), source: "live" as const }),
      () => fixture.getToday(),
    );
  return carrySkillFixer(
    live,
    carryOneStep(
      live,
      carryQuizReader(live, api, () => !who.demo()),
      () => !who.demo(),
    ),
    () => !who.demo(),
  );
}
