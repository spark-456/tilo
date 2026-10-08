// Which Api the Park pages use (WEB-1a; plan section 6.1). No VITE_TILO_API_URL (or a blank one) means
// the fixture Api; a url means the live Api (getLedger reads GET /costs; the other methods reject with
// NotBuilt until each endpoint exists), so a configured deployment never shows sample numbers. Same switch as src/api/config.ts (chooseClient).
import { createFixtureApi } from "./fixtureApi";
import type { Api } from "./index";
import { createLiveApi } from "./liveApi";

export function parkApi(
  env: { VITE_TILO_API_URL?: string | undefined },
  appCheckToken?: () => Promise<string | null>,
  authToken?: () => Promise<string | null>,
): Api {
  const baseUrl = env.VITE_TILO_API_URL?.trim();
  // SEC-10, SEC-15: the live Api gets the App Check and sign-in getters (never asked in fixture mode).
  return baseUrl ? createLiveApi({ baseUrl, appCheckToken, authToken }) : createFixtureApi();
}
