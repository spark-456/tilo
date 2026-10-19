// @vitest-environment happy-dom
// FR-UX-10 / SEC-15 (BQ-WEB-UX10): `useSessionAuth()` is the Park shell's view of the page's one sign-in controller
// (`auth/session`). It has the shape of the shell's `ParkAuth` seam: null when there is no sign-in here (a local
// host, the fixture world, a build with no config: "unavailable", or the SDK has not answered), else a status, the
// person to show and a `signOut()` that resolves only when the session really ended and rejects when it did not.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";

type State = Record<string, unknown>;

const fake = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const session = {
    state: { status: "unavailable" } as State,
    getState() {
      return session.state;
    },
    subscribe(l: () => void) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    set(next: State) {
      session.state = next;
      for (const l of [...listeners]) l();
    },
    idToken: vi.fn(async () => null),
    signInWithGoogle: vi.fn(async () => ({ ok: true })),
    signInAnonymously: vi.fn(async () => ({ ok: true })),
    signOut: vi.fn(async () => undefined),
  };
  return session;
});

vi.mock("../auth/session", () => ({ session: fake }));

import { type SessionAuth, useSessionAuth } from "./sessionAuth";

let seen: SessionAuth | null = null;
function Probe() {
  seen = useSessionAuth();
  return null;
}

let assign: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  seen = null;
  fake.state = { status: "unavailable" };
  fake.signOut.mockReset();
  fake.signOut.mockImplementation(async () => {
    act(() => fake.set({ status: "signed_out" }));
  });
  fake.signInWithGoogle.mockClear();
  fake.signInAnonymously.mockClear();
  assign = vi.spyOn(window.location, "assign").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const show = () => {
  mount(<Probe />);
  return () => seen;
};

describe("FR-UX-10 useSessionAuth: the shell's seam over the page's sign-in", () => {
  for (const status of ["unavailable", "unknown"] as const) {
    it(`FR-UX-10 with a '${status}' session there is no seam, so the shell keeps its prototype behaviour`, () => {
      fake.state = { status };
      const get = show();
      expect(get()).toBeNull();
    });
  }

  it("FR-UX-10 a Google session is signedIn with the person's name and email", () => {
    fake.state = { status: "google", displayName: "Sam Rivera", email: "sam@example.test" };
    const auth = show()();
    expect(auth?.status).toBe("signedIn");
    expect(auth?.user).toEqual({
      displayName: "Sam Rivera",
      email: "sam@example.test",
      isAnonymous: false,
    });
  });

  it("FR-UX-10 an anonymous session is signedIn and is shown as 'Demo session'", () => {
    fake.state = { status: "anonymous" };
    const auth = show()();
    expect(auth?.status).toBe("signedIn");
    expect(auth?.user?.isAnonymous).toBe(true);
    expect(auth?.user?.displayName).toBe("Demo session");
    expect(auth?.user?.email).toBeNull();
  });

  it("FR-UX-10 a signed-out session is signedOut with no person", () => {
    fake.state = { status: "signed_out" };
    const auth = show()();
    expect(auth?.status).toBe("signedOut");
    expect(auth?.user).toBeNull();
  });

  it("FR-UX-10 the seam follows the controller", () => {
    fake.state = { status: "anonymous" };
    const get = show();
    expect(get()?.status).toBe("signedIn");
    act(() => fake.set({ status: "signed_out" }));
    expect(get()?.status).toBe("signedOut");
    act(() => fake.set({ status: "unavailable" }));
    expect(get()).toBeNull();
  });

  it("FR-UX-10 sign-in calls go to the controller", async () => {
    fake.state = { status: "signed_out" };
    const auth = show()();
    await auth?.signInWithGoogle();
    await auth?.signInAnonymously();
    expect(fake.signInWithGoogle).toHaveBeenCalledTimes(1);
    expect(fake.signInAnonymously).toHaveBeenCalledTimes(1);
  });

  it("FR-UX-10 signOut() signs the controller out once, then loads '/' afresh, and resolves", async () => {
    fake.state = { status: "google", displayName: "Sam", email: "sam@example.test" };
    const auth = show()();
    await expect(auth?.signOut()).resolves.toBeUndefined();
    expect(fake.signOut).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith("/");
  });

  it("FR-UX-10 signOut() rejects, and loads nothing, when the SDK's sign-out failed", async () => {
    fake.state = { status: "anonymous" };
    fake.signOut.mockImplementation(async () => {
      act(() => fake.set({ status: "signed_out", signOutFailed: true }));
    });
    const auth = show()();
    await expect(auth?.signOut()).rejects.toBeInstanceOf(Error);
    expect(assign).not.toHaveBeenCalled();
  });

  it("FR-UX-10 signOut() rejects when the controller throws", async () => {
    fake.state = { status: "anonymous" };
    fake.signOut.mockImplementation(async () => {
      throw new Error("boom");
    });
    const auth = show()();
    await expect(auth?.signOut()).rejects.toBeInstanceOf(Error);
    expect(assign).not.toHaveBeenCalled();
  });
});
