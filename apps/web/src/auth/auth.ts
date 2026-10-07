// SEC-15 / SIGNIN (PRD 6 platform row "Firebase Authentication: Google sign-in and anonymous demo sessions"; PRD 16.1:
// Tilo never handles passwords; PRD R-06; BQ-SIGNIN-4): the web client's sign-in controller over the Firebase Auth SDK.
//
// `createAuth({ hostname })` makes nothing happen: the SDK is a dynamic import started by the first subscribe, token
// request or sign-in, so a page that never needs it (the fixture world) never loads it (NFR-01). The host decides what
// is local, as in `appcheck/appCheck.ts`: a local host, or a build with no Firebase web config (`VITE_FIREBASE_API_KEY`,
// `VITE_FIREBASE_PROJECT_ID`), makes no SDK or network call (EFF-01) and the state is "unavailable". The SDK keeps the
// session itself; nothing here copies a token anywhere, logs it, or puts it in a URL. Google sign-in asks for the basic
// profile scopes only: the Gmail, Drive and Calendar scopes belong to the connector consent flow, never to app sign-in.
//
// The Firebase app made here is its own (named), so App Check's default app (`appcheck/appCheck.ts`) keeps its own config.
import type { Auth, User } from "firebase/auth";
import { firebaseWebConfig } from "../appcheck/appCheck";
import { FIREBASE_APP_ID } from "../appcheck/config";

export type AuthState =
  | { status: "unknown" }
  | { status: "signed_out" }
  | { status: "google"; displayName: string | null; email: string | null }
  | { status: "anonymous" }
  | { status: "unavailable" };

export type SignInResult =
  | { ok: true }
  | { ok: false; reason: "cancelled" | "failed" | "unavailable" };

export interface AuthController {
  /** Synchronous; "unknown" until the SDK answers. */
  getState(): AuthState;
  /** `useSyncExternalStore`-shaped; the first subscribe starts the SDK. Returns the unsubscribe. */
  subscribe(listener: () => void): () => void;
  /** The current Firebase ID token, or null. Never rejects, never waits longer than `TOKEN_TIMEOUT_MS`. */
  idToken(): Promise<string | null>;
  /** A Google popup first, a redirect when the popup cannot be used. Never rejects. */
  signInWithGoogle(): Promise<SignInResult>;
  /** A demo session (SEC-15 visitor path). Never rejects. */
  signInAnonymously(): Promise<SignInResult>;
  /** Never rejects. */
  signOut(): Promise<void>;
}

/** True while a person is signed in (Google or a demo session): the account menu's Sign out has something to end. */
export const hasSession = (state: AuthState): boolean =>
  state.status === "google" || state.status === "anonymous";

/** The longest one token request (and the SDK's start, the first time) may take before the call goes out unsigned. */
export const TOKEN_TIMEOUT_MS = 10_000;

const APP_NAME = "tilo-auth";
const LOCAL_HOST = /^(localhost|127\.0\.0\.1|\[::1\]|::1|[^/]*\.localhost)$/i;
/** The person closed the popup, or started another: their choice, not a failure. */
const CANCELLED = new Set([
  "auth/popup-closed-by-user",
  "auth/cancelled-popup-request",
  "auth/user-cancelled",
]);
/** The popup cannot be used here (blocked, or this browser or frame cannot open one): redirect instead. */
const NO_POPUP = new Set([
  "auth/popup-blocked",
  "auth/operation-not-supported-in-this-environment",
]);

interface Sdk {
  readonly auth: Auth;
  readonly lib: typeof import("firebase/auth");
}

/** The SDK's error `code`, read defensively: anything thrown, including a non-object, has one or none. */
function codeOf(error: unknown): string {
  try {
    const code = (error as { code?: unknown } | null)?.code;
    return typeof code === "string" ? code : "";
  } catch {
    return "";
  }
}

const sameState = (a: AuthState, b: AuthState): boolean =>
  a.status === b.status &&
  (a.status !== "google" ||
    (b.status === "google" && a.displayName === b.displayName && a.email === b.email));

export function createAuth(env: { readonly hostname: string }): AuthController {
  const config = firebaseWebConfig();
  const hostname = env.hostname.trim();
  const local = hostname === "" || LOCAL_HOST.test(hostname);

  let state: AuthState = local || !config ? { status: "unavailable" } : { status: "unknown" };
  const listeners = new Set<() => void>();
  let starting: Promise<Sdk | null> | undefined;
  /** A user whose sign-out failed: no token is used for them and the state says signed out. */
  let refused: User | null = null;
  let said = false;

  const set = (next: AuthState): void => {
    if (sameState(state, next)) return;
    state = next;
    for (const listener of [...listeners]) listener();
  };
  const unavailable = (): boolean => state.status === "unavailable";

  const apply = (user: User | null): void => {
    if (user === null || user === refused) {
      if (user === null) refused = null;
      set({ status: "signed_out" });
    } else if (user.isAnonymous) {
      set({ status: "anonymous" });
    } else {
      set({ status: "google", displayName: user.displayName ?? null, email: user.email ?? null });
    }
  };

  function start(): Promise<Sdk | null> {
    if (unavailable() || !config) return Promise.resolve(null);
    starting ??= (async (): Promise<Sdk | null> => {
      try {
        const [app, lib] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
        const firebase = app.initializeApp(
          { ...config, appId: FIREBASE_APP_ID, authDomain: `${config.projectId}.firebaseapp.com` },
          APP_NAME,
        );
        const auth = lib.getAuth(firebase);
        lib.onAuthStateChanged(auth, apply);
        void Promise.resolve(lib.getRedirectResult(auth)).catch(() => undefined); // a redirect that came back
        return { auth, lib };
      } catch {
        set({ status: "unavailable" }); // the SDK could not start: the app works as it did, the API answers 401
        return null;
      }
    })();
    return starting;
  }

  const within = <T>(work: Promise<T>, fallback: T, ms: number): Promise<T> =>
    new Promise((resolve) => {
      const timer = setTimeout(() => resolve(fallback), ms);
      work.then(
        (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        () => {
          clearTimeout(timer);
          resolve(fallback);
        },
      );
    });

  async function token(): Promise<string | null> {
    const sdk = await start();
    const user = sdk?.auth.currentUser ?? null;
    if (user === null || user === refused) return null;
    const value: unknown = await user.getIdToken();
    return typeof value === "string" && value !== "" ? value : null;
  }

  /** An anonymous demo session is kept in session storage, so it ends with the tab (BQ-SIGNIN-4). A Google sign-in
   * keeps the SDK's default (IndexedDB, falling back to local storage), so it survives a restart; nothing is awaited
   * before the Google popup opens, so the browser still counts it as the click's. A refusal here keeps the default. */
  async function keepForTheTabOnly(sdk: Sdk): Promise<void> {
    try {
      await sdk.lib.setPersistence(sdk.auth, sdk.lib.browserSessionPersistence);
    } catch {
      // the demo session goes ahead with the SDK's default persistence
    }
  }

  async function popupThenRedirect(sdk: Sdk): Promise<SignInResult> {
    const provider = new sdk.lib.GoogleAuthProvider();
    provider.setCustomParameters({ prompt: "select_account" });
    try {
      await sdk.lib.signInWithPopup(sdk.auth, provider);
      return { ok: true };
    } catch (error) {
      const code = codeOf(error);
      if (CANCELLED.has(code)) return { ok: false, reason: "cancelled" };
      if (!NO_POPUP.has(code)) return { ok: false, reason: "failed" };
    }
    try {
      await sdk.lib.signInWithRedirect(sdk.auth, provider); // the page leaves for Google and comes back signed in
      return { ok: true };
    } catch {
      return { ok: false, reason: "failed" };
    }
  }

  const inFlight = new Map<string, Promise<SignInResult>>();

  /** One sign-in of each kind at a time: a second click joins the first. */
  function signIn(kind: string, run: (sdk: Sdk) => Promise<SignInResult>): Promise<SignInResult> {
    const running = inFlight.get(kind);
    if (running) return running;
    const call = (async (): Promise<SignInResult> => {
      try {
        const sdk = await start();
        if (sdk === null) return { ok: false, reason: "unavailable" };
        const result = await run(sdk);
        if (result.ok) {
          refused = null;
          apply(sdk.auth.currentUser);
        }
        return result;
      } catch {
        return { ok: false, reason: "failed" };
      }
    })();
    inFlight.set(kind, call);
    const done = (): void => {
      inFlight.delete(kind);
    };
    call.then(done, done);
    return call;
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      if (!said && !local && !config) {
        said = true;
        console.info("Sign-in is off: this build has no Firebase web config.");
      }
      void start();
      return () => {
        listeners.delete(listener);
      };
    },
    idToken: async () => {
      if (unavailable()) return null;
      try {
        return await within(token(), null, TOKEN_TIMEOUT_MS);
      } catch {
        return null;
      }
    },
    signInWithGoogle: () => signIn("google", popupThenRedirect),
    signInAnonymously: () =>
      signIn("anonymous", async (sdk) => {
        await keepForTheTabOnly(sdk);
        try {
          await sdk.lib.signInAnonymously(sdk.auth);
          return { ok: true };
        } catch {
          return { ok: false, reason: "failed" };
        }
      }),
    async signOut() {
      try {
        const sdk = await start();
        if (sdk === null) return;
        try {
          await sdk.lib.signOut(sdk.auth);
        } catch {
          // fall through: whoever is still the SDK's current user is not used
        }
        const left = sdk.auth.currentUser;
        if (left !== null) refused = left;
        set({ status: "signed_out" });
      } catch {
        // never rejects
      }
    },
  };
}
