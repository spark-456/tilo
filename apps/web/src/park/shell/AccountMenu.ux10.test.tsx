// @vitest-environment happy-dom
// FR-UX-10 (docs/prd-supplement-design-2026-10-06.md 1.6): "Account menu. Profile, Connectors, Team, Mobile app
// (concept) and Sign out. Done when: every item navigates; Mobile app opens a placeholder." Sign out goes
// through the ParkAuth seam (shell/auth.tsx), shaped like the sign-in layer's planned `useAuth()`; these tests
// use a FAKE of it. The three links are covered by WEB_3b_acct (Popovers.test.tsx), which carries the FR_UX_10 id.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, pressDocument, q, qa } from "../../../test-support/park/componentsHarness";
import { mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { AppShell } from "./AppShell";
import { type ParkAuth, ParkAuthProvider } from "./auth";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const avatar = () => q<HTMLButtonElement>(document.body, 'button[aria-label="Account menu"]');
const menu = () => document.querySelector<HTMLElement>('[role="menu"][aria-label="Account"]');
const items = () => qa<HTMLButtonElement>(menu() as HTMLElement, '[role="menuitem"]');
const item = (name: string) =>
  items().find((b) => (b.textContent ?? "").startsWith(name)) as HTMLButtonElement | undefined;
const concept = () =>
  document.querySelector<HTMLElement>('[role="dialog"][aria-label="Mobile app"]');

type Status = ParkAuth["status"];
function fakeAuth(status: Status, signOut: () => Promise<void> = () => Promise.resolve()) {
  const user =
    status === "signedIn"
      ? { displayName: "Sam Rivera", email: "sam@example.test", isAnonymous: false }
      : null;
  const auth: ParkAuth = {
    status,
    user,
    signInWithGoogle: vi.fn(() => Promise.resolve()),
    signInAnonymously: vi.fn(() => Promise.resolve()),
    signOut: vi.fn(signOut),
  };
  return auth;
}

async function mountWith(auth: ParkAuth | null) {
  const shell = <AppShell>page</AppShell>;
  const r = mountShell(auth ? <ParkAuthProvider auth={auth}>{shell}</ParkAuthProvider> : shell);
  await settle();
  return r;
}

describe("FR_UX_10 account menu: Mobile app", () => {
  it("FR_UX_10 Mobile app opens a placeholder that says it is a concept, with no navigation", async () => {
    const { navigate } = await mountWith(null);
    expect(concept()).toBeNull();
    click(avatar());
    click(item("Mobile app") as HTMLButtonElement);
    expect(menu()).toBeNull();
    const d = concept() as HTMLElement;
    expect(d).not.toBeNull();
    expect(d.textContent).toMatch(/concept/i);
    expect(navigate).not.toHaveBeenCalled();
    expect(seen.store.getState().wl).toBeNull();
  });

  it("FR_UX_10 the Mobile app placeholder closes with Escape and with its Close button", async () => {
    await mountWith(null);
    click(avatar());
    click(item("Mobile app") as HTMLButtonElement);
    pressDocument("Escape");
    expect(concept()).toBeNull();
    click(avatar());
    click(item("Mobile app") as HTMLButtonElement);
    const close = qa<HTMLButtonElement>(concept() as HTMLElement, "button").find(
      (b) => b.textContent === "Close",
    );
    click(close as HTMLButtonElement);
    expect(concept()).toBeNull();
  });
});

describe("FR_UX_10 account menu: Sign out through the auth seam", () => {
  it("FR_UX_10 Sign out calls the seam's signOut and says nothing until it resolves", async () => {
    let finish: () => void = () => undefined;
    const auth = fakeAuth(
      "signedIn",
      () =>
        new Promise<void>((r) => {
          finish = r;
        }),
    );
    await mountWith(auth);
    click(avatar());
    click(item("Sign out") as HTMLButtonElement);
    expect(auth.signOut).toHaveBeenCalledTimes(1);
    expect(menu()).toBeNull();
    expect(seen.store.getState().toast).toBeNull(); // no success claimed while the call is pending
    await act(async () => {
      finish();
    });
    expect(seen.store.getState().toast?.message).toBe("You are signed out");
  });

  it("FR_UX_10 a failed Sign out says it failed and never claims success", async () => {
    const auth = fakeAuth("signedIn", () => Promise.reject(new Error("network")));
    await mountWith(auth);
    click(avatar());
    click(item("Sign out") as HTMLButtonElement);
    await act(async () => undefined);
    expect(seen.store.getState().toast?.message).toBe("Could not sign out. Try again.");
  });

  it("FR_UX_10 a second Sign out while the first is pending does not call the seam twice", async () => {
    let finish: () => void = () => undefined;
    const auth = fakeAuth(
      "signedIn",
      () =>
        new Promise<void>((r) => {
          finish = r;
        }),
    );
    await mountWith(auth);
    click(avatar());
    click(item("Sign out") as HTMLButtonElement);
    click(avatar());
    click(item("Sign out") as HTMLButtonElement);
    expect(auth.signOut).toHaveBeenCalledTimes(1);
    await act(async () => {
      finish();
    });
  });

  it("FR_UX_10 signed in: the header names the signed-in person from the seam, not a fixture", async () => {
    await mountWith(fakeAuth("signedIn"));
    click(avatar());
    const text = (menu() as HTMLElement).textContent ?? "";
    expect(text).toContain("Sam Rivera");
    expect(text).toContain("sam@example.test");
    expect(text).not.toContain("Alex Morgan");
    expect(avatar().textContent).toBe("SR");
  });

  it("FR_UX_10 signed out: no user name, no Sign out row, the three links and Mobile app remain", async () => {
    await mountWith(fakeAuth("signedOut"));
    click(avatar());
    const text = (menu() as HTMLElement).textContent ?? "";
    expect(text).not.toContain("Alex Morgan");
    expect(text).not.toContain("alex@");
    expect(avatar().textContent).not.toBe("AM");
    expect(items().map((b) => b.textContent)).toEqual([
      "Profile and settings",
      "Connectors6 on",
      "Team and roles",
      "Mobile appConcept",
    ]);
  });
});
