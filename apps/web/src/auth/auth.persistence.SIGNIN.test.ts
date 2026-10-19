// SEC-15 / SIGNIN follow-up (BQ-SIGNIN-4): where the Firebase SDK keeps the session. An anonymous demo session is set to
// session persistence (it ends with the tab) before the anonymous sign-in; a Google sign-in is left on the SDK's
// default (IndexedDB, falling back to local storage), so it survives a browser restart, and nothing is awaited between
// the click and the popup. The SDK is faked; nothing touches the network.
import { beforeEach, describe, expect, it, vi } from "vitest";

interface FakeUser {
  uid: string;
  isAnonymous: boolean;
  displayName: string | null;
  email: string | null;
  getIdToken: () => Promise<string>;
}

const sdk = vi.hoisted(() => {
  const state = {
    current: null as FakeUser | null,
    listeners: [] as Array<(u: FakeUser | null) => void>,
  };
  const emit = (user: FakeUser | null) => {
    state.current = user;
    for (const l of [...state.listeners]) l(user);
  };
  const auth = {
    get currentUser() {
      return state.current;
    },
  };
  class GoogleAuthProvider {
    setCustomParameters() {
      return this;
    }
  }
  const user = (anonymous: boolean): FakeUser => ({
    uid: anonymous ? "anon-1" : "google-1",
    isAnonymous: anonymous,
    displayName: anonymous ? null : "A Person",
    email: anonymous ? null : ["person", "example.test"].join("@"),
    getIdToken: async () => ["fake", "id", "token"].join("."),
  });
  return {
    state,
    emit,
    auth,
    GoogleAuthProvider,
    session: { type: "SESSION" },
    indexedDB: { type: "INDEXEDDB" },
    local: { type: "LOCAL" },
    initializeApp: vi.fn((options: unknown) => ({ options })),
    getAuth: vi.fn(() => auth),
    onAuthStateChanged: vi.fn((_a: unknown, cb: (u: FakeUser | null) => void) => {
      state.listeners.push(cb);
      queueMicrotask(() => cb(state.current));
      return () => undefined;
    }),
    getRedirectResult: vi.fn(async () => null),
    setPersistence: vi.fn(async (_a: unknown, _p: unknown) => undefined),
    signInAnonymously: vi.fn(async () => {
      const u = user(true);
      emit(u);
      return { user: u };
    }),
    signInWithPopup: vi.fn(async () => {
      const u = user(false);
      emit(u);
      return { user: u };
    }),
    signInWithRedirect: vi.fn(async () => undefined),
    signOut: vi.fn(async () => emit(null)),
  };
});

vi.mock("firebase/app", () => ({ initializeApp: sdk.initializeApp }));
vi.mock("firebase/auth", () => ({
  getAuth: sdk.getAuth,
  onAuthStateChanged: sdk.onAuthStateChanged,
  GoogleAuthProvider: sdk.GoogleAuthProvider,
  getRedirectResult: sdk.getRedirectResult,
  setPersistence: sdk.setPersistence,
  browserSessionPersistence: sdk.session,
  indexedDBLocalPersistence: sdk.indexedDB,
  browserLocalPersistence: sdk.local,
  signInAnonymously: sdk.signInAnonymously,
  signInWithPopup: sdk.signInWithPopup,
  signInWithRedirect: sdk.signInWithRedirect,
  signOut: sdk.signOut,
}));

async function started() {
  vi.resetModules();
  sdk.state.current = null;
  sdk.state.listeners = [];
  const { createAuth } = await import("./auth");
  const auth = createAuth({ hostname: "example-project.web.app" });
  auth.subscribe(() => undefined);
  await vi.waitFor(() => expect(auth.getState().status).toBe("signed_out"));
  return auth;
}

beforeEach(() => {
  for (const fn of [sdk.setPersistence, sdk.signInAnonymously, sdk.signInWithPopup]) fn.mockClear();
  sdk.setPersistence.mockImplementation(async () => undefined);
});

describe("SEC-15 SIGNIN follow-up session persistence", () => {
  it("SEC-15 SIGNIN an anonymous demo session is set to session persistence before the anonymous sign-in", async () => {
    const auth = await started();
    await expect(auth.signInAnonymously()).resolves.toEqual({ ok: true });
    expect(sdk.setPersistence).toHaveBeenCalledTimes(1);
    expect(sdk.setPersistence.mock.calls[0]?.[1]).toBe(sdk.session);
    const persisted = sdk.setPersistence.mock.invocationCallOrder[0] ?? 0;
    const signedIn = sdk.signInAnonymously.mock.invocationCallOrder[0] ?? 0;
    expect(persisted).toBeLessThan(signedIn);
    expect(auth.getState()).toEqual({ status: "anonymous" });
  });

  it("SEC-15 SIGNIN a refused persistence change still gives the demo session", async () => {
    sdk.setPersistence.mockImplementation(async () => {
      throw Object.assign(new Error("not supported"), { code: "auth/invalid-persistence-type" });
    });
    const auth = await started();
    await expect(auth.signInAnonymously()).resolves.toEqual({ ok: true });
    expect(auth.getState().status).toBe("anonymous");
  });

  it("SEC-15 SIGNIN a Google sign-in is never put on session persistence and opens its popup without waiting on the SDK's storage", async () => {
    const auth = await started();
    const pending = auth.signInWithGoogle();
    await Promise.resolve();
    expect(sdk.signInWithPopup).toHaveBeenCalledTimes(1);
    await expect(pending).resolves.toEqual({ ok: true });
    for (const call of sdk.setPersistence.mock.calls) expect(call[1]).not.toBe(sdk.session);
    expect(auth.getState().status).toBe("google");
  });
});
