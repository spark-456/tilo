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
// The getter never rejects, never throws and never hangs: no token (or a start or token request slower than
// TOKEN_TIMEOUT_MS) is null, and the API only logs a missing token while enforcement is off. The token is never logged.
import type { AppCheck, getToken as GetToken } from "firebase/app-check";
import { FIREBASE_APP_ID, RECAPTCHA_SITE_KEY } from "./config";

/** The longest the start, or one token request, may take before the call goes out without a header. */
export const TOKEN_TIMEOUT_MS = 5000;

const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\]|::1|[^/]*\.localhost)$/i;

/** True for a host that is the developer's own machine; a host that merely contains "localhost" is not. */
const isLocalHost = (hostname: string): boolean => LOCAL_HOST.test(hostname.trim());

interface Started {
  readonly appCheck: AppCheck;
  readonly getToken: typeof GetToken;
}

/** The one start of App Check for the page (a second start throws in the SDK); null when it is not available. */
let starting: Promise<Started | null> | undefined;

function start(): Promise<Started | null> {
  starting ??= (async (): Promise<Started | null> => {
    try {
      const apiKey: unknown = import.meta.env.VITE_FIREBASE_API_KEY;
      const projectId: unknown = import.meta.env.VITE_FIREBASE_PROJECT_ID;
      if (
        typeof apiKey !== "string" ||
        apiKey === "" ||
        typeof projectId !== "string" ||
        projectId === ""
      ) {
        console.info("App Check is off: this build has no Firebase web config.");
        return null;
      }
      const { initializeApp } = await import("firebase/app");
      const sdk = await import("firebase/app-check");
      const app = initializeApp({ apiKey, projectId, appId: FIREBASE_APP_ID });
      const appCheck = sdk.initializeAppCheck(app, {
        provider: new sdk.ReCaptchaEnterpriseProvider(RECAPTCHA_SITE_KEY),
        isTokenAutoRefreshEnabled: true,
      });
      return { appCheck, getToken: sdk.getToken };
    } catch {
      return null; // the SDK could not start (blocked script, bad config): no token, the app still works
    }
  })();
  return starting;
}

/** Resolves `promise`, or null once `ms` has passed or the promise fails. The timer is always cleared. */
function within<T>(promise: Promise<T>, ms: number): Promise<T | null> {
  return new Promise<T | null>((resolve) => {
    const timer = setTimeout(() => resolve(null), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        clearTimeout(timer);
        resolve(null);
      },
    );
  });
}

async function fetchToken(): Promise<string | null> {
  const started = await within(start(), TOKEN_TIMEOUT_MS);
  if (started === null) return null;
  const result: unknown = await within(started.getToken(started.appCheck, false), TOKEN_TIMEOUT_MS);
  const token = (result as { token?: unknown } | null)?.token;
  return typeof token === "string" && token !== "" ? token : null;
}

export function createAppCheckTokenGetter(env: {
  readonly hostname: string;
}): () => Promise<string | null> {
  if (isLocalHost(env.hostname)) return async () => null;
  return async () => {
    try {
      return await fetchToken();
    } catch {
      return null;
    }
  };
}
