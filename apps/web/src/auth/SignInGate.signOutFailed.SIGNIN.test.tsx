// @vitest-environment happy-dom
// SEC-15 / SIGNIN-FIX: when a sign-out failed the gate still shows the sign-in panel (the controller says signed_out and
// uses no token), and the panel tells the person in plain words that their session may still be open on this device.
// After a sign-out that worked there is no such note.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { SignInGate } from "./SignInGate";

type State = { status: "signed_out"; signOutFailed?: true };

function fakeAuth(initial: State) {
  let state: State = initial;
  const listeners = new Set<() => void>();
  return {
    set: (next: State) => {
      state = next;
      act(() => {
        for (const l of [...listeners]) l();
      });
    },
    auth: {
      getState: () => state,
      subscribe: (l: () => void) => {
        listeners.add(l);
        return () => listeners.delete(l);
      },
      idToken: vi.fn(async () => null),
      signInWithGoogle: vi.fn(async () => ({ ok: true as const })),
      signInAnonymously: vi.fn(async () => ({ ok: true as const })),
      signOut: vi.fn(async () => undefined),
    },
  };
}

afterEach(() => {
  cleanup();
});

const note = () => document.querySelector('[data-testid="sign-out-failed"]');

describe("SEC-15 SIGNIN-FIX the sign-in panel after a failed sign-out", () => {
  it("SEC-15 SIGNIN-FIX it says in plain words that the session may still be open on this device", () => {
    const { auth } = fakeAuth({ status: "signed_out", signOutFailed: true });
    mount(
      <SignInGate auth={auth}>
        <div data-testid="app" />
      </SignInGate>,
    );
    expect(document.querySelector('[data-testid="app"]')).toBeNull();
    expect(note()?.getAttribute("role")).toBe("alert");
    expect(note()?.textContent ?? "").toMatch(/did not finish/i);
  });

  it("SEC-15 SIGNIN-FIX a plain signed-out panel has no such note, and it goes when the state is plain again", () => {
    const { auth, set } = fakeAuth({ status: "signed_out" });
    mount(
      <SignInGate auth={auth}>
        <div data-testid="app" />
      </SignInGate>,
    );
    expect(note()).toBeNull();
    set({ status: "signed_out", signOutFailed: true });
    expect(note()).not.toBeNull();
    set({ status: "signed_out" });
    expect(note()).toBeNull();
  });
});
