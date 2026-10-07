// @vitest-environment happy-dom
// SEC-15 / SIGNIN (PRD 6 platform row "Google sign-in and anonymous demo sessions"; PRD 16.1 "Tilo never handles
// passwords"; PRD supplement SEC-15): what a person sees and can do before they are signed in. Behaviour only, no
// pixels: the look is the Park design's, and Claude Design owns it.
//
// Public interface pinned here, under apps/web/src/auth/:
//   SignInGate.tsx   export function SignInGate(props: { auth: AuthController; children: ReactNode })
//                    - the app is behind it. `auth` is the controller of auth.ts (see auth.SIGNIN.test.ts):
//                      status "unavailable" (a local host, the fixture world, a build with no Firebase config): the
//                      children, no sign-in UI at all, so dev, tests and the fixture deploy work as before (EFF-01);
//                      "unknown" (the SDK has not answered): neither the children nor the sign-in panel, no flash;
//                      "signed_out": the sign-in panel and NOT the children;
//                      "google" or "anonymous": the children and no panel.
//   The panel is rendered by the gate (a separate SignInPanel component is the builder's choice). It offers
//   "Sign in with Google" and a demo session (a control whose accessible name contains "demo"), both real buttons.
//   It has no password or email field and no form: Tilo never handles passwords.
//   `session.ts` exports `session: AuthController`, the one controller for this page (createAuth on the page's host).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../test-support/park/componentsHarness";
import { SignInGate } from "./SignInGate";

type AuthState =
  | { status: "unknown" }
  | { status: "signed_out" }
  | { status: "google"; displayName: string | null; email: string | null }
  | { status: "anonymous" }
  | { status: "unavailable" };
type SignInResult = { ok: true } | { ok: false; reason: "cancelled" | "failed" | "unavailable" };

function fakeAuth(initial: AuthState) {
  let state = initial;
  const listeners = new Set<() => void>();
  const set = (next: AuthState) => {
    state = next;
    act(() => {
      for (const l of [...listeners]) l();
    });
  };
  const auth = {
    getState: () => state,
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    idToken: vi.fn(async () => null),
    signInWithGoogle: vi.fn(async (): Promise<SignInResult> => ({ ok: true })),
    signInAnonymously: vi.fn(async (): Promise<SignInResult> => ({ ok: true })),
    signOut: vi.fn(async () => undefined),
  };
  return { auth, set };
}

afterEach(() => {
  cleanup();
});

const App = () => <div data-testid="app">the app</div>;
const gate = (auth: ReturnType<typeof fakeAuth>["auth"]) => (
  <SignInGate auth={auth}>
    <App />
  </SignInGate>
);
const app = () => document.querySelector('[data-testid="app"]');
const buttons = () => qa<HTMLButtonElement>(document.body, "button");
const named = (re: RegExp) =>
  buttons().find((b) => re.test(`${b.textContent ?? ""} ${b.getAttribute("aria-label") ?? ""}`));
const googleButton = () => named(/sign in with google/i);
const demoButton = () => named(/demo/i);
const alertText = () => document.querySelector('[role="alert"]')?.textContent ?? null;
const settle = async () => {
  await act(async () => undefined);
  await act(async () => undefined);
};

describe("SEC-15 SIGNIN the gate in front of the app", () => {
  it("SEC-15 SIGNIN 'unavailable' (local host, fixture world, no config): the app shows and there is no sign-in UI", () => {
    const { auth } = fakeAuth({ status: "unavailable" });
    mount(gate(auth));
    expect(app()).not.toBeNull();
    expect(googleButton()).toBeUndefined();
    expect(demoButton()).toBeUndefined();
    expect(auth.signInWithGoogle).not.toHaveBeenCalled();
  });

  it("SEC-15 SIGNIN 'unknown' (the SDK has not answered): neither the app nor the sign-in panel, so nothing flashes", () => {
    const { auth, set } = fakeAuth({ status: "unknown" });
    mount(gate(auth));
    expect(app()).toBeNull();
    expect(googleButton()).toBeUndefined();
    set({ status: "signed_out" });
    expect(googleButton()).toBeDefined();
  });

  it("SEC-15 SIGNIN signed out: the sign-in panel offers Google and a demo session, and the app is not mounted", () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    mount(gate(auth));
    expect(app()).toBeNull();
    const google = googleButton() as HTMLButtonElement;
    const demo = demoButton() as HTMLButtonElement;
    expect(google).toBeDefined();
    expect(demo).toBeDefined();
    expect(google).not.toBe(demo);
    expect(google.getAttribute("type")).toBe("button");
    expect(demo.getAttribute("type")).toBe("button");
  });

  it("SEC-15 SIGNIN the panel never asks for a password or an email address (Tilo never handles passwords)", () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    mount(gate(auth));
    expect(
      document.querySelector(
        'input[type="password"], input[type="email"], input[type="text"], textarea',
      ),
    ).toBeNull();
    expect(document.querySelector("form")).toBeNull();
    expect(document.body.textContent ?? "").not.toMatch(/\bpassword\b/i);
  });

  it("SEC-15 SIGNIN signed in with Google, or in a demo session: the app shows and the panel is gone", () => {
    for (const state of [
      { status: "google", displayName: "A Person", email: "person@example.test" } as const,
      { status: "anonymous" } as const,
    ]) {
      const { auth } = fakeAuth(state);
      const m = mount(gate(auth));
      expect(app(), state.status).not.toBeNull();
      expect(googleButton(), state.status).toBeUndefined();
      expect(demoButton(), state.status).toBeUndefined();
      m.unmount();
    }
  });

  it("SEC-15 SIGNIN signing out (from the menu, or from another tab) brings the panel back and removes the app", () => {
    const { auth, set } = fakeAuth({ status: "google", displayName: null, email: null });
    mount(gate(auth));
    expect(app()).not.toBeNull();
    set({ status: "signed_out" });
    expect(app()).toBeNull();
    expect(googleButton()).toBeDefined();
    set({ status: "anonymous" });
    expect(app()).not.toBeNull();
    expect(googleButton()).toBeUndefined();
  });
});

describe("SEC-15 SIGNIN the two ways in", () => {
  it("SEC-15 SIGNIN 'Sign in with Google' starts exactly one Google sign-in", async () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    mount(gate(auth));
    click(googleButton() as HTMLButtonElement);
    await settle();
    expect(auth.signInWithGoogle).toHaveBeenCalledTimes(1);
    expect(auth.signInAnonymously).not.toHaveBeenCalled();
  });

  it("SEC-15 SIGNIN the demo button starts exactly one anonymous session and no Google sign-in", async () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    mount(gate(auth));
    click(demoButton() as HTMLButtonElement);
    await settle();
    expect(auth.signInAnonymously).toHaveBeenCalledTimes(1);
    expect(auth.signInWithGoogle).not.toHaveBeenCalled();
  });

  it("SEC-15 SIGNIN while a sign-in is in progress both buttons are disabled, so a second click cannot open a second popup", async () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    let finish: ((r: SignInResult) => void) | undefined;
    auth.signInWithGoogle.mockImplementation(
      () =>
        new Promise<SignInResult>((resolve) => {
          finish = resolve;
        }),
    );
    mount(gate(auth));
    const google = googleButton() as HTMLButtonElement;
    click(google);
    await settle();
    for (const b of [googleButton(), demoButton()] as HTMLButtonElement[]) {
      expect(b.disabled || b.getAttribute("aria-disabled") === "true").toBe(true);
    }
    click(google);
    expect(auth.signInWithGoogle).toHaveBeenCalledTimes(1);
    await act(async () => finish?.({ ok: false, reason: "cancelled" }));
    for (const b of [googleButton(), demoButton()] as HTMLButtonElement[]) {
      expect(b.disabled || b.getAttribute("aria-disabled") === "true").toBe(false);
    }
  });

  it("SEC-15 SIGNIN a failed sign-in says so in a plain alert (no SDK text, no codes) and can be tried again", async () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    auth.signInWithGoogle.mockResolvedValueOnce({ ok: false, reason: "failed" });
    mount(gate(auth));
    click(googleButton() as HTMLButtonElement);
    await settle();
    const text = alertText();
    expect(text).not.toBeNull();
    expect((text ?? "").trim().length).toBeGreaterThan(10);
    expect(text ?? "").not.toMatch(/auth\/|firebase|undefined|\[object|error:/i);
    click(googleButton() as HTMLButtonElement);
    await settle();
    expect(auth.signInWithGoogle).toHaveBeenCalledTimes(2);
  });

  it("SEC-15 SIGNIN closing the popup is the person's choice: no alert", async () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    auth.signInWithGoogle.mockResolvedValueOnce({ ok: false, reason: "cancelled" });
    mount(gate(auth));
    click(googleButton() as HTMLButtonElement);
    await settle();
    expect(alertText()).toBeNull();
    expect(googleButton()).toBeDefined();
  });

  it("SEC-15 SIGNIN a failed demo session is reported the same way", async () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    auth.signInAnonymously.mockResolvedValueOnce({ ok: false, reason: "failed" });
    mount(gate(auth));
    click(demoButton() as HTMLButtonElement);
    await settle();
    expect((alertText() ?? "").length).toBeGreaterThan(10);
  });

  it("SEC-15 SIGNIN a controller call that rejects anyway does not crash the page", async () => {
    const { auth } = fakeAuth({ status: "signed_out" });
    auth.signInWithGoogle.mockRejectedValueOnce(new Error("raw sdk failure with a token"));
    mount(gate(auth));
    click(googleButton() as HTMLButtonElement);
    await settle();
    expect(googleButton()).toBeDefined();
    expect(document.body.textContent ?? "").not.toContain("raw sdk failure");
    expect(document.body).toBeDefined(); // the page is still mounted (q() only searches descendants of body)
  });
});
