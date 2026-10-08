// @vitest-environment happy-dom
// SEC-15 / SIGNIN-FIX (BQ-SIGNIN-4): a sign-out the SDK refused must be told apart from one that worked. The controller
// still answers `signed_out` and still uses no token for the person (the verified SIGNIN properties), but the state now
// says `signOutFailed: true`, so the page is not loaded afresh (a reload would let the SDK restore the person) and the
// sign-in panel can say so. A sign-out that worked has exactly the state it always had, `{ status: "signed_out" }`.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface FakeUser {
  uid: string;
  isAnonymous: boolean;
  displayName: string | null;
  email: string | null;
  getIdToken: () => Promise<string>;
}

const sdk = vi.hoisted(() => {
  const state = {
    currentUser: null as FakeUser | null,
    listeners: [] as Array<(u: FakeUser | null) => void>,
  };
  const emit = (user: FakeUser | null) => {
    state.currentUser = user;
    for (const l of [...state.listeners]) l(user);
  };
  const auth = {
    get currentUser() {
      return state.currentUser;
    },
  };
  class GoogleAuthProvider {
    setCustomParameters() {
      return this;
    }
  }
  return {
    state,
    emit,
    auth,
    GoogleAuthProvider,
    initializeApp: vi.fn((options: unknown) => ({ name: "x", options })),
    getAuth: vi.fn(() => auth),
    onAuthStateChanged: vi.fn((_auth: unknown, cb: (u: FakeUser | null) => void) => {
      state.listeners.push(cb);
      queueMicrotask(() => cb(state.currentUser));
      return () => undefined;
    }),
    getRedirectResult: vi.fn(async () => null),
    signInWithPopup: vi.fn(async (): Promise<void> => undefined),
    signInWithRedirect: vi.fn(async (): Promise<void> => undefined),
    signInAnonymously: vi.fn(async (): Promise<void> => undefined),
    signOut: vi.fn(async (_auth: unknown): Promise<void> => undefined),
    setPersistence: vi.fn(async (): Promise<void> => undefined),
    browserSessionPersistence: { type: "SESSION" },
  };
});

vi.mock("firebase/app", () => ({ initializeApp: sdk.initializeApp }));
vi.mock("firebase/auth", () => ({
  getAuth: sdk.getAuth,
  onAuthStateChanged: sdk.onAuthStateChanged,
  GoogleAuthProvider: sdk.GoogleAuthProvider,
  getRedirectResult: sdk.getRedirectResult,
  signInWithPopup: sdk.signInWithPopup,
  signInWithRedirect: sdk.signInWithRedirect,
  signInAnonymously: sdk.signInAnonymously,
  signOut: sdk.signOut,
  setPersistence: sdk.setPersistence,
  browserSessionPersistence: sdk.browserSessionPersistence,
}));

const fakeToken = () => ["fake", "id", "token"].join(".");
const userOf = (isAnonymous: boolean): FakeUser => ({
  uid: isAnonymous ? "anon-1" : "google-1",
  isAnonymous,
  displayName: isAnonymous ? null : "A Person",
  email: isAnonymous ? null : ["person", "example.test"].join("@"),
  getIdToken: async () => fakeToken(),
});

async function started(reload?: () => void) {
  vi.resetModules();
  sdk.state.currentUser = null;
  sdk.state.listeners = [];
  const { createAuth } = await import("./auth");
  const auth = createAuth({ hostname: "example-project.web.app", ...(reload ? { reload } : {}) });
  auth.subscribe(() => undefined);
  await vi.waitFor(() => expect(auth.getState().status).toBe("signed_out"));
  return auth;
}

beforeEach(() => {
  sdk.signOut.mockReset();
  sdk.signOut.mockImplementation(async () => sdk.emit(null));
  sdk.signInAnonymously.mockReset();
  sdk.signInAnonymously.mockImplementation(async () => sdk.emit(userOf(true)));
  sdk.signInWithPopup.mockReset();
  sdk.signInWithPopup.mockImplementation(async () => sdk.emit(userOf(false)));
  for (const m of ["log", "info", "warn", "error", "debug"] as const)
    vi.spyOn(console, m).mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SEC-15 SIGNIN-FIX the controller says when the SDK's sign-out did not work", () => {
  it("SEC-15 SIGNIN-FIX a sign-out that worked leaves exactly { status: 'signed_out' }", async () => {
    const auth = await started();
    await auth.signInAnonymously();
    await auth.signOut();
    expect(auth.getState()).toEqual({ status: "signed_out" });
  });

  it("SEC-15 SIGNIN-FIX a sign-out the SDK threw on, with the person still current, is signed_out with signOutFailed and no token", async () => {
    const auth = await started();
    await auth.signInAnonymously();
    sdk.signOut.mockImplementation(async () => {
      throw new Error("auth/network-request-failed");
    });
    await expect(auth.signOut()).resolves.toBeUndefined();
    expect(auth.getState()).toEqual({ status: "signed_out", signOutFailed: true });
    await expect(auth.idToken()).resolves.toBeNull();
  });

  it("SEC-15 SIGNIN-FIX a Google person whose sign-out failed is flagged the same way", async () => {
    const auth = await started();
    await auth.signInWithGoogle();
    sdk.signOut.mockImplementation(async () => {
      throw new Error("auth/internal-error");
    });
    await auth.signOut();
    expect(auth.getState()).toEqual({ status: "signed_out", signOutFailed: true });
  });

  it("SEC-15 SIGNIN-FIX an SDK that threw but really ended the session is a plain sign-out, not a failed one", async () => {
    const auth = await started();
    await auth.signInAnonymously();
    sdk.signOut.mockImplementation(async () => {
      sdk.emit(null);
      throw new Error("auth/network-request-failed");
    });
    await auth.signOut();
    expect(auth.getState()).toEqual({ status: "signed_out" });
  });

  it("SEC-15 SIGNIN-FIX a new sign-in after a failed sign-out clears the flag", async () => {
    const auth = await started();
    await auth.signInAnonymously();
    sdk.signOut.mockImplementation(async () => {
      throw new Error("auth/network-request-failed");
    });
    await auth.signOut();
    expect(auth.getState()).toMatchObject({ signOutFailed: true });
    sdk.signOut.mockImplementation(async () => sdk.emit(null));
    await auth.signInWithGoogle();
    expect(auth.getState().status).toBe("google");
    await auth.signOut();
    expect(auth.getState()).toEqual({ status: "signed_out" });
  });

  it("SEC-15 SIGNIN-FIX subscribers hear the change from signed_out to signed_out with the flag", async () => {
    const auth = await started();
    await auth.signInAnonymously();
    const heard = vi.fn();
    auth.subscribe(heard);
    sdk.signOut.mockImplementation(async () => {
      throw new Error("auth/network-request-failed");
    });
    heard.mockClear();
    await auth.signOut();
    expect(heard).toHaveBeenCalled();
  });
});

describe("SEC-15 SIGNIN-FIX r2: the refused person is matched by uid, and a new person reloads the page", () => {
  const refuseSignOut = () =>
    sdk.signOut.mockImplementation(async () => {
      throw new Error("auth/network-request-failed");
    });

  it("SEC-15 SIGNIN-FIX a fresh User object for the refused uid still gets no token and keeps the flag", async () => {
    const auth = await started(vi.fn());
    await auth.signInAnonymously();
    refuseSignOut();
    await auth.signOut();
    sdk.emit(userOf(true)); // the SDK swaps the object, same uid
    expect(auth.getState()).toEqual({ status: "signed_out", signOutFailed: true });
    await expect(auth.idToken()).resolves.toBeNull();
  });

  it("SEC-15 SIGNIN-FIX a sign-in after a refused sign-out loads the page afresh, once", async () => {
    const reload = vi.fn();
    const auth = await started(reload);
    await auth.signInAnonymously();
    refuseSignOut();
    await auth.signOut();
    expect(reload).not.toHaveBeenCalled();
    await auth.signInAnonymously(); // the same person again: the caches still go
    expect(reload).toHaveBeenCalledTimes(1);
    await auth.signInWithGoogle(); // another person too, but one reload is already on its way
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("SEC-15 SIGNIN-FIX another uid taking over the page reloads it; the first sign-in does not", async () => {
    const reload = vi.fn();
    const auth = await started(reload);
    await auth.signInAnonymously();
    expect(reload).not.toHaveBeenCalled();
    sdk.emit(userOf(false)); // e.g. another tab signed a Google person in
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
