// SEC-10 (PRD 16 "Rate limits, App Check and spend caps"; PRD 6.2): Firebase App Check for the web client.
//
// `createAppCheckTokenGetter({ hostname })` returns the getter `HttpClient` asks before each request. It
// starts App Check lazily, on the first token request, so a page that never calls the API (the deployed
// fixture world) never loads the Firebase SDK or reCAPTCHA, and the SDK stays out of the landing bundle (NFR-01).
// The host decides what is local, not `import.meta.env.DEV`:
// - a local host (localhost, *.localhost, 127.0.0.1, ::1) makes no reCAPTCHA or Google call (EFF-01) and the
//   getter answers null;
// - a deployed host starts `initializeAppCheck` with `ReCaptchaEnterpriseProvider` and token auto-refresh.
// The Firebase `apiKey` and `projectId` come only from the build (VITE_FIREBASE_API_KEY, VITE_FIREBASE_PROJECT_ID);
// when either is missing App Check is skipped, one line says so, and the app works as it did before.
// The getter never rejects, never throws and never hangs: one overall deadline (TOKEN_TIMEOUT_MS) covers the start
// and the token request together, and no token is null (the API only logs a missing token while enforcement is off).
// After a deadline passes the getter answers null at once for BACKOFF_MS, so a hung SDK does not delay every request
// and every event poll for the life of the page. A dynamic import that failed is retried after that pause; a
// start that failed for a reason that cannot change (no config, the SDK refused to start) is not. The token is never logged.
import type { AppCheck, getToken as GetToken } from "firebase/app-check";
import { FIREBASE_APP_ID, RECAPTCHA_SITE_KEY } from "./config";

/** The longest the start plus one token request may take before the call goes out without a header. */
export const TOKEN_TIMEOUT_MS = 5000;
/** After a deadline passes (or the SDK could not be loaded) no token is asked for this long. */
export const BACKOFF_MS = 60_000;

const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\]|::1|[^/]*\.localhost)$/i;

/** True for a host that is the developer's own machine; a host that merely contains "localhost" is not. */
const isLocalHost = (hostname: string): boolean => LOCAL_HOST.test(hostname.trim());

interface Started {
  readonly appCheck: AppCheck;
  readonly getToken: typeof GetToken;
}

/** The one start of App Check for the page (a second start throws in the SDK); null when it is not available. */
let starting: Promise<Started | null> | undefined;
/** No token is asked for before this time (`Date.now()`). */
let pausedUntil = 0;

const pause = (): void => {
  pausedUntil = Date.now() + BACKOFF_MS;
};

/** The Firebase web config the build supplies, or null when it has none. The one reader of the two variables: sign-in
 * (`auth/auth.ts`, SEC-15) takes the config from here too, so the two never disagree about what the build holds. */
export function firebaseWebConfig(): { apiKey: string; projectId: string } | null {
  const apiKey: unknown = import.meta.env.VITE_FIREBASE_API_KEY;
  const projectId: unknown = import.meta.env.VITE_FIREBASE_PROJECT_ID;
  if (
    typeof apiKey !== "string" ||
    apiKey === "" ||
    typeof projectId !== "string" ||
    projectId === ""
  ) {
    return null;
  }
  return { apiKey, projectId };
}

function start(): Promise<Started | null> {
  starting ??= (async (): Promise<Started | null> => {
    const config = firebaseWebConfig();
    if (config === null) {
      console.info("App Check is off: this build has no Firebase web config.");
      return null; // cannot change for this page
    }
    const { apiKey, projectId } = config;
    let app: typeof import("firebase/app");
    let check: typeof import("firebase/app-check");
    try {
      [app, check] = await Promise.all([import("firebase/app"), import("firebase/app-check")]);
    } catch {
      starting = undefined; // a network failure may pass: try again after the pause
      pause();
      return null;
    }
    try {
      const appCheck = check.initializeAppCheck(
        app.initializeApp({ apiKey, projectId, appId: FIREBASE_APP_ID }),
        {
          provider: new check.ReCaptchaEnterpriseProvider(RECAPTCHA_SITE_KEY),
          isTokenAutoRefreshEnabled: true,
        },
      );
      return { appCheck, getToken: check.getToken };
    } catch {
      return null; // the SDK refused to start (bad config): no token, the app still works
    }
  })();
  return starting;
}

async function fetchToken(): Promise<string | null> {
  const started = await start();
  if (started === null) return null;
  try {
    const result: unknown = await started.getToken(started.appCheck, false);
    const token = (result as { token?: unknown } | null)?.token;
    return typeof token === "string" && token !== "" ? token : null;
  } catch {
    return null;
  }
}

const TIMED_OUT = Symbol("timed out");

/** The token, or null; one deadline for everything, its timer always cleared. */
function tokenWithin(ms: number): Promise<string | null | typeof TIMED_OUT> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(TIMED_OUT), ms);
    fetchToken().then(
      (token) => {
        clearTimeout(timer);
        resolve(token);
      },
      () => {
        clearTimeout(timer);
        resolve(null);
      },
    );
  });
}

export function createAppCheckTokenGetter(env: {
  readonly hostname: string;
}): () => Promise<string | null> {
  if (isLocalHost(env.hostname)) return async () => null;
  return async () => {
    try {
      if (Date.now() < pausedUntil) return null;
      const token = await tokenWithin(TOKEN_TIMEOUT_MS);
      if (token === TIMED_OUT) {
        pause();
        return null;
      }
      return token;
    } catch {
      return null;
    }
  };
}
