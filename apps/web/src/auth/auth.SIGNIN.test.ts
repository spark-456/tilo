// SEC-15 / SIGNIN (PRD 6 platform row "Firebase Authentication: Google sign-in and anonymous demo sessions";
// PRD R-06; PRD supplement SEC-15): the web client's sign-in controller, over the Firebase Auth SDK (faked here).
//
// Public interface pinned here (apps/web/src/auth/auth.ts, new):
//   createAuth(env: { hostname: string }): AuthController
//   AuthState = { status: "unknown" }                       // the SDK has not answered yet
//             | { status: "signed_out" }
//             | { status: "google"; displayName: string | null; email: string | null }
//             | { status: "anonymous" }                     // a demo session (SEC-15 visitor path)
//             | { status: "unavailable" }                   // no Firebase here: a local host, or a build with no config
//   SignInResult = { ok: true } | { ok: false; reason: "cancelled" | "failed" | "unavailable" }
//   AuthController {
//     getState(): AuthState                                  // synchronous; "unknown" until the SDK answers
//     subscribe(listener: () => void): () => void            // useSyncExternalStore-shaped; the first subscribe starts the SDK
//     idToken(): Promise<string | null>                      // the current Firebase ID token, or null; never rejects
//     signInWithGoogle(): Promise<SignInResult>              // popup first, redirect when the popup cannot be used; never rejects
//     signInAnonymously(): Promise<SignInResult>             // never rejects
//     signOut(): Promise<void>                               // never rejects
//   }
// Nothing starts at creation: the Firebase SDK is loaded (dynamic import) and initialised by the first subscribe,
// idToken or sign-in call, so a page that never needs it (the fixture world) never loads it (NFR-01).
// The host decides what is local, as in appcheck/appCheck.ts (localhost, *.localhost, 127.0.0.1, ::1): a local host
// makes no SDK call and no network call (EFF-01); status is "unavailable" and every call answers without throwing.
// The token is never logged and never put in a URL. Sign-in asks Google for the basic profile scopes only: the Gmail,
// Drive and Calendar scopes belong to the connector consent flow (infra/ACCESS.md section 6), never to app sign-in.
//
// The SDK is replaced by the fake below (every export the controller may use is listed; a builder who needs another
// export adds it here in the same PR), so nothing touches the network or needs the package.
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FIREBASE_APP_ID } from "../appcheck/config";

interface FakeUser {
  uid: string;
  isAnonymous: boolean;
  displayName: string | null;
  email: string | null;
  getIdToken: ReturnType<typeof vi.fn>;
}

const sdk = vi.hoisted(() => {
  const state = {
    currentUser: null as FakeUser | null,
    authListeners: [] as Array<(u: FakeUser | null) => void>,
    idListeners: [] as Array<(u: FakeUser | null) => void>,
    scopes: [] as string[],
    params: [] as unknown[],
    providers: 0,
  };
  class GoogleAuthProvider {
    constructor() {
      state.providers += 1;
    }
    addScope(scope: string) {
      state.scopes.push(scope);
      return this;
    }
    setCustomParameters(p: unknown) {
      state.params.push(p);
      return this;
    }
    static credentialFromResult() {
      return null;
    }
  }
  const emit = (user: FakeUser | null) => {
    state.currentUser = user;
    for (const l of [...state.authListeners]) l(user);
    for (const l of [...state.idListeners]) l(user);
  };
  const auth = {
    get currentUser() {
      return state.currentUser;
    },
  };
  const api = {
    state,
    emit,
    auth,
    GoogleAuthProvider,
    initializeApp: vi.fn((options: unknown) => ({ name: "[DEFAULT]", options })),
    getApps: vi.fn(() => [] as unknown[]),
    getApp: vi.fn(() => ({ name: "[DEFAULT]", options: {} })),
    getAuth: vi.fn((_app?: unknown) => auth),
    initializeAuth: vi.fn((_app?: unknown, _deps?: unknown) => auth),
    onAuthStateChanged: vi.fn((_auth: unknown, cb: (u: FakeUser | null) => void) => {
      state.authListeners.push(cb);
      queueMicrotask(() => cb(state.currentUser));
      return () => {
        state.authListeners = state.authListeners.filter((l) => l !== cb);
      };
    }),
    onIdTokenChanged: vi.fn((_auth: unknown, cb: (u: FakeUser | null) => void) => {
      state.idListeners.push(cb);
      queueMicrotask(() => cb(state.currentUser));
      return () => {
        state.idListeners = state.idListeners.filter((l) => l !== cb);
      };
    }),
    signInWithPopup: vi.fn(async (_auth: unknown, _provider: unknown, _resolver?: unknown) => ({
      user: null as FakeUser | null,
    })),
    signInWithRedirect: vi.fn(
      async (_auth: unknown, _provider: unknown, _resolver?: unknown) => undefined,
    ),
    getRedirectResult: vi.fn(async (_auth: unknown, _resolver?: unknown) => null as unknown),
    signInAnonymously: vi.fn(async (_auth: unknown) => ({ user: null as FakeUser | null })),
    signOut: vi.fn(async (_auth: unknown) => {
      emit(null);
    }),
    setPersistence: vi.fn(async (_auth: unknown, _p: unknown) => undefined),
    browserLocalPersistence: { type: "LOCAL" },
    browserSessionPersistence: { type: "SESSION" },
    indexedDBLocalPersistence: { type: "INDEXEDDB" },
    inMemoryPersistence: { type: "NONE" },
    browserPopupRedirectResolver: { resolver: true },
  };
  return api;
});

vi.mock("firebase/app", () => ({
  initializeApp: sdk.initializeApp,
  getApps: sdk.getApps,
  getApp: sdk.getApp,
}));
vi.mock("firebase/auth", () => ({
  getAuth: sdk.getAuth,
  initializeAuth: sdk.initializeAuth,
  onAuthStateChanged: sdk.onAuthStateChanged,
  onIdTokenChanged: sdk.onIdTokenChanged,
  GoogleAuthProvider: sdk.GoogleAuthProvider,
  signInWithPopup: sdk.signInWithPopup,
  signInWithRedirect: sdk.signInWithRedirect,
  getRedirectResult: sdk.getRedirectResult,
  signInAnonymously: sdk.signInAnonymously,
  signOut: sdk.signOut,
  setPersistence: sdk.setPersistence,
  browserLocalPersistence: sdk.browserLocalPersistence,
  browserSessionPersistence: sdk.browserSessionPersistence,
  indexedDBLocalPersistence: sdk.indexedDBLocalPersistence,
  inMemoryPersistence: sdk.inMemoryPersistence,
  browserPopupRedirectResolver: sdk.browserPopupRedirectResolver,
}));

type AuthState =
  | { status: "unknown" }
  | { status: "signed_out" }
  | { status: "google"; displayName: string | null; email: string | null }
  | { status: "anonymous" }
  | { status: "unavailable" };
type SignInResult = { ok: true } | { ok: false; reason: "cancelled" | "failed" | "unavailable" };
interface AuthController {
  getState(): AuthState;
  subscribe(listener: () => void): () => void;
  idToken(): Promise<string | null>;
  signInWithGoogle(): Promise<SignInResult>;
  signInAnonymously(): Promise<SignInResult>;
  signOut(): Promise<void>;
}

const DEPLOYED = "example-project.web.app";
const LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]", "app.localhost"];
const BASIC_SCOPES = new Set(["openid", "email", "profile"]);

// Fake credentials, assembled at runtime (never a real token, never committed whole).
const fakeToken = (n: number | string = 1) => ["fake", "firebase", "id", String(n)].join(".");
const EMAIL = ["person", "example.test"].join("@");

function userOf(kind: "google" | "anonymous", token = fakeToken()): FakeUser {
  return {
    uid: kind === "google" ? "google-uid-1" : "anon-uid-1",
    isAnonymous: kind === "anonymous",
    displayName: kind === "google" ? "A Person" : null,
    email: kind === "google" ? EMAIL : null,
    getIdToken: vi.fn(async (_force?: boolean) => token),
  };
}

async function load() {
  vi.resetModules();
  return (await import("./auth")) as { createAuth(env: { hostname: string }): AuthController };
}

/** A controller on a deployed host, started (the SDK has answered "nobody is signed in"). */
async function started(): Promise<AuthController> {
  sdk.state.currentUser = null; // a fresh browser each time (a property test calls this many times per test)
  sdk.state.authListeners = [];
  sdk.state.idListeners = [];
  const { createAuth } = await load();
  const auth = createAuth({ hostname: DEPLOYED });
  auth.subscribe(() => undefined);
  await vi.waitFor(() => expect(auth.getState().status).toBe("signed_out"));
  return auth;
}

const flush = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

let fetchSpy: ReturnType<typeof vi.fn>;
let logs: ReturnType<typeof vi.spyOn>[];

beforeEach(() => {
  sdk.state.currentUser = null;
  sdk.state.authListeners = [];
  sdk.state.idListeners = [];
  sdk.state.scopes.length = 0;
  sdk.state.params.length = 0;
  sdk.state.providers = 0;
  for (const fn of [
    sdk.initializeApp,
    sdk.getApps,
    sdk.getApp,
    sdk.getAuth,
    sdk.initializeAuth,
    sdk.onAuthStateChanged,
    sdk.onIdTokenChanged,
    sdk.signInWithPopup,
    sdk.signInWithRedirect,
    sdk.getRedirectResult,
    sdk.signInAnonymously,
    sdk.signOut,
    sdk.setPersistence,
  ])
    fn.mockClear();
  sdk.signInWithPopup.mockImplementation(async () => {
    const user = userOf("google");
    sdk.emit(user);
    return { user };
  });
  sdk.signInAnonymously.mockImplementation(async () => {
    const user = userOf("anonymous");
    sdk.emit(user);
    return { user };
  });
  sdk.signInWithRedirect.mockImplementation(async () => undefined);
  sdk.getRedirectResult.mockImplementation(async () => null);
  sdk.signOut.mockImplementation(async () => {
    sdk.emit(null);
  });
  sdk.initializeApp.mockImplementation((options: unknown) => ({ name: "[DEFAULT]", options }));
  fetchSpy = vi.fn(async () => {
    throw new Error("SIGNIN: the sign-in controller must not call fetch itself");
  });
  vi.stubGlobal("fetch", fetchSpy);
  logs = (["log", "info", "warn", "error", "debug"] as const).map((m) =>
    vi.spyOn(console, m).mockImplementation(() => undefined),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

const loggedText = () => JSON.stringify(logs.flatMap((spy) => spy.mock.calls));

describe("SEC-15 SIGNIN the SDK starts lazily and from the build's Firebase config", () => {
  it("SEC-15 SIGNIN creating the controller loads and calls nothing; the first subscribe starts the SDK once", async () => {
    const { createAuth } = await load();
    const auth = createAuth({ hostname: DEPLOYED });
    expect(sdk.initializeApp).not.toHaveBeenCalled();
    expect(auth.getState()).toEqual({ status: "unknown" });

    const unsubscribe = auth.subscribe(() => undefined);
    auth.subscribe(() => undefined);
    await vi.waitFor(() => expect(auth.getState()).toEqual({ status: "signed_out" }));
    expect(sdk.initializeApp).toHaveBeenCalledTimes(1);
    expect(
      sdk.onAuthStateChanged.mock.calls.length + sdk.onIdTokenChanged.mock.calls.length,
    ).toBeGreaterThanOrEqual(1);
    unsubscribe();
  });

  it("SEC-15 SIGNIN the Firebase app is made from the tilo-web app id, the build's key and project, and its own auth domain", async () => {
    await started();
    const options = (sdk.initializeApp.mock.calls[0] as [Record<string, unknown>])[0];
    expect(options.appId).toBe(FIREBASE_APP_ID);
    expect(options.apiKey).toBe("test-web-api-key"); // apps/web/vitest.config.ts env
    expect(options.projectId).toBe("demo-tilo-web");
    // BQ-SIGNIN-4: the auth domain is `<project>.firebaseapp.com` unless the build says otherwise; the Hosting CSP
    // frame-src is pinned to the same host (tests/repo/test_SEC_15_SIGNIN_docs_and_csp.py).
    expect(options.authDomain).toBe("demo-tilo-web.firebaseapp.com");
  });

  it("SEC-15 SIGNIN a subscriber is told when the state changes and not after it unsubscribes", async () => {
    const auth = await started();
    const heard = vi.fn();
    const unsubscribe = auth.subscribe(heard);
    await auth.signInWithGoogle();
    expect(heard).toHaveBeenCalled();
    expect(auth.getState()).toEqual({ status: "google", displayName: "A Person", email: EMAIL });
    unsubscribe();
    heard.mockClear();
    await auth.signOut();
    expect(heard).not.toHaveBeenCalled();
  });
});

describe("SEC-15 SIGNIN a local host or a build with no Firebase config makes no SDK call and no network call", () => {
  for (const hostname of LOCAL_HOSTS) {
    it(`SEC-15 SIGNIN ${hostname} is "unavailable", answers without throwing and calls nothing`, async () => {
      const { createAuth } = await load();
      const auth = createAuth({ hostname });
      const heard = vi.fn();
      auth.subscribe(heard);
      expect(auth.getState()).toEqual({ status: "unavailable" });
      await expect(auth.idToken()).resolves.toBeNull();
      await expect(auth.signInWithGoogle()).resolves.toEqual({ ok: false, reason: "unavailable" });
      await expect(auth.signInAnonymously()).resolves.toEqual({ ok: false, reason: "unavailable" });
      await expect(auth.signOut()).resolves.toBeUndefined();
      await flush();

      expect(sdk.initializeApp).not.toHaveBeenCalled();
      expect(sdk.getAuth).not.toHaveBeenCalled();
      expect(sdk.initializeAuth).not.toHaveBeenCalled();
      expect(sdk.signInWithPopup).not.toHaveBeenCalled();
      expect(sdk.signInWithRedirect).not.toHaveBeenCalled();
      expect(sdk.signInAnonymously).not.toHaveBeenCalled();
      expect(sdk.state.providers).toBe(0);
      expect(fetchSpy).not.toHaveBeenCalled();
      expect(auth.getState()).toEqual({ status: "unavailable" });
    });
  }

  it("SEC-15 SIGNIN a host that merely contains 'localhost' is not local", async () => {
    const { createAuth } = await load();
    const auth = createAuth({ hostname: "localhost.evil.example" });
    auth.subscribe(() => undefined);
    await vi.waitFor(() => expect(sdk.initializeApp).toHaveBeenCalled());
  });

  it("SEC-15 SIGNIN a build with no apiKey or projectId is 'unavailable' on a deployed host too, and says so once", async () => {
    for (const missing of ["VITE_FIREBASE_API_KEY", "VITE_FIREBASE_PROJECT_ID"]) {
      vi.stubEnv(missing, "");
      sdk.initializeApp.mockClear();
      const { createAuth } = await load();
      const auth = createAuth({ hostname: DEPLOYED });
      auth.subscribe(() => undefined);
      await flush();
      expect(auth.getState(), missing).toEqual({ status: "unavailable" });
      await expect(auth.signInWithGoogle()).resolves.toEqual({ ok: false, reason: "unavailable" });
      await expect(auth.idToken()).resolves.toBeNull();
      expect(sdk.initializeApp).not.toHaveBeenCalled();
      vi.unstubAllEnvs();
    }
  });

  it("SEC-15 SIGNIN an SDK that refuses to start leaves the app working: 'unavailable', null token, a failed sign-in", async () => {
    sdk.initializeApp.mockImplementation(() => {
      throw new Error("bad config");
    });
    const { createAuth } = await load();
    const auth = createAuth({ hostname: DEPLOYED });
    auth.subscribe(() => undefined);
    await vi.waitFor(() => expect(auth.getState().status).toBe("unavailable"));
    await expect(auth.idToken()).resolves.toBeNull();
    const result = await auth.signInWithGoogle();
    expect(result.ok).toBe(false);
    await expect(auth.signOut()).resolves.toBeUndefined();
  });
});

describe("SEC-15 SIGNIN the ID token", () => {
  it("SEC-15 SIGNIN nobody signed in: no token", async () => {
    const auth = await started();
    await expect(auth.idToken()).resolves.toBeNull();
  });

  it("SEC-15 SIGNIN a signed-in person: the SDK's token, asked for each time, never force-refreshed on every call", async () => {
    const auth = await started();
    await auth.signInWithGoogle();
    const user = sdk.state.currentUser as FakeUser;
    await expect(auth.idToken()).resolves.toBe(fakeToken());
    user.getIdToken.mockImplementation(async () => fakeToken(2)); // the SDK refreshed it near expiry
    await expect(auth.idToken()).resolves.toBe(fakeToken(2));
    expect(user.getIdToken.mock.calls.every(([force]) => force !== true)).toBe(true);
  });

  it("SEC-15 SIGNIN an anonymous demo session has a token too", async () => {
    const auth = await started();
    await auth.signInAnonymously();
    await expect(auth.idToken()).resolves.toBe(fakeToken());
  });

  it("SEC-15 SIGNIN a token request that rejects is null, one that never answers is null within a deadline", async () => {
    const auth = await started();
    await auth.signInWithGoogle();
    const user = sdk.state.currentUser as FakeUser;
    user.getIdToken.mockImplementation(async () => {
      throw new Error("auth/network-request-failed");
    });
    await expect(auth.idToken()).resolves.toBeNull();

    vi.useFakeTimers();
    user.getIdToken.mockImplementation(() => new Promise(() => undefined)); // hangs forever
    const pending = auth.idToken();
    await vi.advanceTimersByTimeAsync(30_000);
    await expect(pending).resolves.toBeNull();
  });

  it("SEC-15 SIGNIN a getIdToken that returns something that is not a non-empty string is null", async () => {
    const auth = await started();
    await auth.signInWithGoogle();
    const user = sdk.state.currentUser as FakeUser;
    for (const odd of [undefined, null, 5, "", {}, ["a"], true]) {
      user.getIdToken.mockImplementation(async () => odd);
      await expect(auth.idToken(), String(odd)).resolves.toBeNull();
    }
  });
});

describe("SEC-15 SIGNIN Sign in with Google: popup first, redirect when the popup cannot be used", () => {
  it("SEC-15 SIGNIN one popup with the Google provider, basic profile scopes only, and the person is signed in", async () => {
    const auth = await started();
    await expect(auth.signInWithGoogle()).resolves.toEqual({ ok: true });

    expect(sdk.signInWithPopup).toHaveBeenCalledTimes(1);
    const [, provider] = sdk.signInWithPopup.mock.calls[0] as [unknown, unknown];
    expect(provider).toBeInstanceOf(sdk.GoogleAuthProvider);
    expect(sdk.signInWithRedirect).not.toHaveBeenCalled();
    for (const scope of sdk.state.scopes) {
      expect(
        BASIC_SCOPES.has(scope),
        `scope ${scope}: Gmail, Drive and Calendar scopes are the connectors' consent, not sign-in`,
      ).toBe(true);
    }
    expect(auth.getState()).toEqual({ status: "google", displayName: "A Person", email: EMAIL });
  });

  for (const code of ["auth/popup-blocked", "auth/operation-not-supported-in-this-environment"]) {
    it(`SEC-15 SIGNIN ${code}: falls back to one redirect with the same provider, and does not throw`, async () => {
      sdk.signInWithPopup.mockImplementation(async () => {
        throw Object.assign(new Error("popup"), { code });
      });
      const auth = await started();
      const result = await auth.signInWithGoogle();

      expect(typeof result.ok).toBe("boolean");
      expect(sdk.signInWithRedirect).toHaveBeenCalledTimes(1);
      const popupProvider = (sdk.signInWithPopup.mock.calls[0] as [unknown, unknown])[1];
      const redirectProvider = (sdk.signInWithRedirect.mock.calls[0] as [unknown, unknown])[1];
      expect(redirectProvider).toBeInstanceOf(sdk.GoogleAuthProvider);
      expect(redirectProvider).toBe(popupProvider);
    });
  }

  for (const code of [
    "auth/popup-closed-by-user",
    "auth/cancelled-popup-request",
    "auth/user-cancelled",
  ]) {
    it(`SEC-15 SIGNIN ${code}: the person chose to stop, so it is 'cancelled' and no redirect starts`, async () => {
      sdk.signInWithPopup.mockImplementation(async () => {
        throw Object.assign(new Error("closed"), { code });
      });
      const auth = await started();
      await expect(auth.signInWithGoogle()).resolves.toEqual({ ok: false, reason: "cancelled" });
      expect(sdk.signInWithRedirect).not.toHaveBeenCalled();
      expect(auth.getState()).toEqual({ status: "signed_out" });
    });
  }

  for (const code of [
    "auth/network-request-failed",
    "auth/unauthorized-domain",
    "auth/internal-error",
    "auth/too-many-requests",
    "weird",
  ]) {
    it(`SEC-15 SIGNIN ${code}: a failed sign-in, no redirect, nothing thrown, still signed out`, async () => {
      sdk.signInWithPopup.mockImplementation(async () => {
        throw Object.assign(new Error(`${code} raw sdk text`), { code });
      });
      const auth = await started();
      await expect(auth.signInWithGoogle()).resolves.toEqual({ ok: false, reason: "failed" });
      expect(sdk.signInWithRedirect).not.toHaveBeenCalled();
      expect(auth.getState()).toEqual({ status: "signed_out" });
    });
  }

  it("SEC-15 SIGNIN a second click while the popup is open does not open a second popup", async () => {
    let release: (() => void) | undefined;
    sdk.signInWithPopup.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = () => {
            const user = userOf("google");
            sdk.emit(user);
            resolve({ user });
          };
        }),
    );
    const auth = await started();
    const first = auth.signInWithGoogle();
    const second = auth.signInWithGoogle();
    await flush();
    expect(sdk.signInWithPopup).toHaveBeenCalledTimes(1);
    release?.();
    await Promise.all([first, second]);
    expect(sdk.signInWithPopup).toHaveBeenCalledTimes(1);
  });

  it("SEC-15 SIGNIN a redirect that came back is completed when the SDK starts, and a failure there is swallowed", async () => {
    sdk.getRedirectResult.mockImplementation(async () => {
      throw Object.assign(new Error("redirect failed"), { code: "auth/unauthorized-domain" });
    });
    const { createAuth } = await load();
    const auth = createAuth({ hostname: DEPLOYED });
    auth.subscribe(() => undefined);
    await vi.waitFor(() => expect(auth.getState().status).toBe("signed_out"));
    expect(sdk.getRedirectResult).toHaveBeenCalledTimes(1);
  });
});

describe("SEC-15 SIGNIN anonymous demo sessions and sign out", () => {
  it("SEC-15 SIGNIN a demo session is one anonymous sign-in, shown as 'anonymous'", async () => {
    const auth = await started();
    await expect(auth.signInAnonymously()).resolves.toEqual({ ok: true });
    expect(sdk.signInAnonymously).toHaveBeenCalledTimes(1);
    expect(auth.getState()).toEqual({ status: "anonymous" });
  });

  it("SEC-15 SIGNIN an anonymous sign-in the SDK refuses is a failed result, not a throw", async () => {
    sdk.signInAnonymously.mockImplementation(async () => {
      throw Object.assign(new Error("admin-restricted-operation"), {
        code: "auth/admin-restricted-operation",
      });
    });
    const auth = await started();
    await expect(auth.signInAnonymously()).resolves.toEqual({ ok: false, reason: "failed" });
    expect(auth.getState()).toEqual({ status: "signed_out" });
  });

  it("SEC-15 SIGNIN sign out calls the SDK once, the state is signed out and there is no token afterwards", async () => {
    const auth = await started();
    await auth.signInWithGoogle();
    await expect(auth.signOut()).resolves.toBeUndefined();
    expect(sdk.signOut).toHaveBeenCalledTimes(1);
    expect(auth.getState()).toEqual({ status: "signed_out" });
    await expect(auth.idToken()).resolves.toBeNull();
  });

  it("SEC-15 SIGNIN sign out while signed out, or when the SDK throws, still resolves and ends signed out", async () => {
    const auth = await started();
    await expect(auth.signOut()).resolves.toBeUndefined();
    await auth.signInAnonymously();
    sdk.signOut.mockImplementation(async () => {
      throw new Error("auth/network-request-failed");
    });
    await expect(auth.signOut()).resolves.toBeUndefined();
    await expect(
      auth.idToken(),
      "a failed sign-out must not leave a token in use",
    ).resolves.toBeNull();
    expect(auth.getState().status).toBe("signed_out");
  });
});

describe("SEC-15 SIGNIN the token and the person's details are never logged", () => {
  it("SEC-15 SIGNIN no console call during sign-in, token reads, failures and sign-out contains the token or the email", async () => {
    sdk.signInWithPopup.mockImplementationOnce(async () => {
      throw Object.assign(new Error(`failed for ${EMAIL} with ${fakeToken()}`), {
        code: "auth/internal-error",
      });
    });
    const auth = await started();
    await auth.signInWithGoogle(); // fails
    await auth.signInWithGoogle(); // succeeds
    await auth.idToken();
    await auth.signOut();
    await auth.signInAnonymously();
    await auth.idToken();
    await flush();
    const text = loggedText();
    expect(text).not.toContain(fakeToken());
    expect(text).not.toContain(EMAIL);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("SEC-15 SIGNIN properties", () => {
  it("SEC-15 SIGNIN property: whatever error the popup throws, sign-in answers with a result and never throws", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.oneof(
          fc.string({ maxLength: 60 }).map((code) => Object.assign(new Error("x"), { code })),
          fc.string({ maxLength: 60 }).map((m) => new Error(m)),
          fc.anything(),
        ),
        async (error) => {
          sdk.signInWithPopup.mockImplementation(async () => {
            throw error;
          });
          sdk.signInWithRedirect.mockImplementation(async () => {
            throw error;
          });
          const auth = await started();
          const result = await auth.signInWithGoogle();
          expect(typeof result.ok).toBe("boolean");
          if (!result.ok) expect(["cancelled", "failed", "unavailable"]).toContain(result.reason);
        },
      ),
      { numRuns: 40 },
    );
  });

  it("SEC-15 SIGNIN property: the token is either the SDK's exact string or null, never a throw", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.oneof(fc.string(), fc.constant(undefined), fc.constant(null), fc.integer()),
        async (value) => {
          const auth = await started();
          await auth.signInWithGoogle();
          (sdk.state.currentUser as FakeUser).getIdToken.mockImplementation(async () => value);
          const token = await auth.idToken();
          if (typeof value === "string" && value !== "") expect(token).toBe(value);
          else expect(token).toBeNull();
        },
      ),
      { numRuns: 40 },
    );
  });

  it("SEC-15 SIGNIN property: any sequence of sign-in, sign-out and SDK events leaves a valid state and never throws", async () => {
    const step = fc.constantFrom("google", "anonymous", "out", "emit_google", "emit_null", "token");
    await fc.assert(
      fc.asyncProperty(fc.array(step, { maxLength: 12 }), async (steps) => {
        const auth = await started();
        for (const s of steps) {
          if (s === "google") await auth.signInWithGoogle();
          else if (s === "anonymous") await auth.signInAnonymously();
          else if (s === "out") await auth.signOut();
          else if (s === "emit_google") sdk.emit(userOf("google"));
          else if (s === "emit_null") sdk.emit(null);
          else await auth.idToken();
          await flush();
          expect(["signed_out", "google", "anonymous"]).toContain(auth.getState().status);
        }
        // the state always agrees with who the SDK says is signed in
        const user = sdk.state.currentUser;
        const expected = user === null ? "signed_out" : user.isAnonymous ? "anonymous" : "google";
        await vi.waitFor(() => expect(auth.getState().status).toBe(expected));
      }),
      { numRuns: 30 },
    );
  });
});
