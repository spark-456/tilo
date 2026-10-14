// @vitest-environment happy-dom
// FR-HIL-12: the sign-in never sees a shared link's token. Firebase builds `redirectUrl` from the current address,
// so the token leaves the address before sign-in starts and returns after it, and storage holds it only between.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q } from "../../test-support/park/componentsHarness";
import { SignInGate } from "./SignInGate";
import { restoreShareToken, stashShareToken } from "./pendingShare";

const TOKEN = "Ab_1-".repeat(9); // made here, not a real secret
const KEY = "tilo.share.pending";

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

const go = (path: string) => window.history.replaceState({}, "", path);

describe("FR_HIL_12 the token stays out of the address during sign-in", () => {
  it("FR_HIL_12 stash moves the token to this tab's storage and makes the address /share", () => {
    go(`/share/${TOKEN}`);
    stashShareToken();
    expect(window.location.pathname).toBe("/share");
    expect(window.location.href).not.toContain(TOKEN);
    expect(window.sessionStorage.getItem(KEY)).toContain(TOKEN);
  });

  it("FR_HIL_12 any other address is left alone, and so is a path with a non-token segment", () => {
    for (const p of [
      "/",
      "/worlds",
      "/share",
      "/share/abc",
      `/share/${TOKEN}/answer`,
      "/share/a.b",
    ]) {
      go(p);
      stashShareToken();
      expect(window.location.pathname, p).toBe(p);
      expect(window.sessionStorage.getItem(KEY), p).toBeNull();
    }
  });

  it("FR_HIL_12 restore puts the token back, clears storage, and tells the router", () => {
    go(`/share/${TOKEN}`);
    stashShareToken();
    const seen = vi.fn();
    window.addEventListener("popstate", seen);
    restoreShareToken();
    window.removeEventListener("popstate", seen);
    expect(window.location.pathname).toBe(`/share/${TOKEN}`);
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
    expect(seen).toHaveBeenCalledTimes(1);
  });

  it("FR_HIL_12 a stale or foreign stash is dropped and never restored; restore elsewhere does nothing", () => {
    go(`/share/${TOKEN}`);
    stashShareToken(1_000);
    restoreShareToken(1_000 + 16 * 60 * 1000); // past the keep time
    expect(window.location.pathname).toBe("/share");
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
    window.sessionStorage.setItem(KEY, JSON.stringify({ t: "../x", at: Date.now() }));
    restoreShareToken();
    expect(window.location.pathname).toBe("/share");
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
    go("/worlds");
    window.sessionStorage.setItem(KEY, JSON.stringify({ t: TOKEN, at: Date.now() }));
    restoreShareToken();
    expect(window.location.pathname).toBe("/worlds"); // only /share is rewritten
    expect(window.sessionStorage.getItem(KEY)).toBeNull(); // and a signed-in tab keeps no stash on any path
  });
});

describe("FR_HIL_12 through the sign-in gate", () => {
  function fakeAuth() {
    let state: { status: string } = { status: "signed_out" };
    const listeners = new Set<() => void>();
    const urlsAtSignIn: string[] = [];
    const auth = {
      getState: () => state,
      subscribe: (l: () => void) => {
        listeners.add(l);
        return () => listeners.delete(l);
      },
      idToken: vi.fn(async () => null),
      signInWithGoogle: vi.fn(async () => {
        urlsAtSignIn.push(window.location.href);
        return { ok: true as const };
      }),
      signInAnonymously: vi.fn(async () => {
        urlsAtSignIn.push(window.location.href);
        return { ok: true as const };
      }),
      signOut: vi.fn(async () => undefined),
    };
    const signedIn = () => {
      state = { status: "google" };
      act(() => {
        for (const l of [...listeners]) l();
      });
    };
    return { auth, urlsAtSignIn, signedIn };
  }

  it("FR_HIL_12 the address Google and Firebase can read has no token; after sign-in the link is back and storage is empty", async () => {
    go(`/share/${TOKEN}`);
    const { auth, urlsAtSignIn, signedIn } = fakeAuth();
    const m = mount(
      <SignInGate auth={auth as never}>
        <p data-testid="app">app</p>
      </SignInGate>,
    );
    expect(m.container.querySelector('[data-testid="app"]')).toBeNull();
    const google = [...m.container.querySelectorAll("button")].find((b) =>
      (b.textContent ?? "").includes("Google"),
    );
    if (!google) throw new Error("no Google button");
    await act(async () => {
      click(google);
      await Promise.resolve();
    });
    expect(auth.signInWithGoogle).toHaveBeenCalledTimes(1);
    expect(urlsAtSignIn).toHaveLength(1);
    expect(urlsAtSignIn[0]).not.toContain(TOKEN);
    expect(window.location.href).not.toContain(TOKEN); // still true while the panel waits
    signedIn();
    expect(q(m.container, '[data-testid="app"]')).toBeTruthy();
    expect(window.location.pathname).toBe(`/share/${TOKEN}`);
    expect(window.sessionStorage.getItem(KEY)).toBeNull();
  });

  it("FR_HIL_12 the demo session path hides the token the same way", async () => {
    go(`/share/${TOKEN}`);
    const { auth, urlsAtSignIn } = fakeAuth();
    const m = mount(
      <SignInGate auth={auth as never}>
        <p>app</p>
      </SignInGate>,
    );
    const demo = [...m.container.querySelectorAll("button")].find((b) =>
      (b.textContent ?? "").toLowerCase().includes("demo"),
    );
    if (!demo) throw new Error("no demo button");
    await act(async () => {
      click(demo);
      await Promise.resolve();
    });
    expect(urlsAtSignIn[0]).not.toContain(TOKEN);
  });
});
