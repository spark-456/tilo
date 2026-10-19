// @vitest-environment happy-dom
// SEC-15 / SIGNIN + FR-UX-10 (docs/prd-supplement-design-2026-10-06.md 1.6: "Account menu. Profile, Connectors, Team,
// Mobile app (concept) and Sign out"): Sign out in the Park account menu really signs out when there is a session.
// Behaviour only; the menu's look and rows are pinned by Popovers.test.tsx (WEB-3b) and the design.
//
// The one page-wide controller is `session` from apps/web/src/auth/session.ts (see SignInGate.SIGNIN.test.tsx); the
// shell reads it, so it is replaced here. With a session ("google" or "anonymous"):
//   Sign out calls `session.signOut()` exactly once and closes the menu; the "prototype" toast is gone.
// Without one (status "unavailable": a local host, the fixture world, a build with no Firebase config) the menu is the
// WEB-3b prototype as before: the toast says "This is a prototype, so you stay signed in" and nothing is called, so
// the existing Popovers.test.tsx test `WEB_3b_acct_Sign_out_toasts_that_this_is_a_prototype_and_stays_put` stays green
// without a change.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp, seen } from "../../../test-support/park/shellHarness";

const fake = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const session = {
    status: "google" as "google" | "anonymous" | "unavailable" | "signed_out",
    getState() {
      return this.status === "google"
        ? { status: "google", displayName: "A Person", email: "person@example.test" }
        : { status: this.status };
    },
    subscribe(l: () => void) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    idToken: vi.fn(async () => null),
    signInWithGoogle: vi.fn(async () => ({ ok: true })),
    signInAnonymously: vi.fn(async () => ({ ok: true })),
    signOut: vi.fn(async () => {
      session.status = "signed_out";
      for (const l of [...listeners]) l();
    }),
  };
  return session;
});

vi.mock("../../auth/session", () => ({ session: fake }));
vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

const PROTOTYPE = "This is a prototype, so you stay signed in";

beforeEach(() => {
  fake.status = "google";
  fake.signOut.mockClear();
});

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const avatar = () => q<HTMLButtonElement>(document.body, 'button[aria-label="Account menu"]');
const menu = () => document.querySelector<HTMLElement>('[role="menu"][aria-label="Account"]');
const signOutItem = () =>
  qa<HTMLButtonElement>(menu() as HTMLElement, '[role="menuitem"]').find((b) =>
    (b.textContent ?? "").startsWith("Sign out"),
  ) as HTMLButtonElement;

describe("FR-UX-10 SIGNIN Sign out in the account menu", () => {
  for (const status of ["google", "anonymous"] as const) {
    it(`FR-UX-10 SIGNIN with a ${status} session, Sign out signs out once, closes the menu and shows no prototype toast`, async () => {
      fake.status = status;
      await mountApp();
      click(avatar());
      expect(signOutItem()).toBeDefined();
      click(signOutItem());

      expect(fake.signOut).toHaveBeenCalledTimes(1);
      expect(menu()).toBeNull();
      expect(seen.store.getState().toast?.message).not.toBe(PROTOTYPE);
    });
  }

  it("FR-UX-10 SIGNIN a sign-out that fails still closes the menu and leaves the page running", async () => {
    fake.signOut.mockImplementationOnce(async () => {
      throw new Error("auth/network-request-failed");
    });
    await mountApp();
    click(avatar());
    click(signOutItem());
    expect(fake.signOut).toHaveBeenCalledTimes(1);
    expect(menu()).toBeNull();
  });

  it("FR-UX-10 SIGNIN with no session (local host, fixture world) it is still the prototype toast and nothing is signed out", async () => {
    fake.status = "unavailable";
    await mountApp();
    click(avatar());
    click(signOutItem());
    expect(fake.signOut).not.toHaveBeenCalled();
    expect(seen.store.getState().toast?.message).toBe(PROTOTYPE);
    expect(menu()).toBeNull();
  });
});
