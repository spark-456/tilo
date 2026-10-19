// @vitest-environment happy-dom
// FR-UX-10 / SEC-15 (closes BQ-WEB-UX10): <ParkApp/> hands the account menu the page's real sign-in. The menu shows the
// person who is signed in (a Google person by name and email, a demo session as "Demo session"), Sign out really signs
// out (once; "You are signed out" only after it worked, "Could not sign out. Try again." when it did not), and with no
// sign-in here ("unavailable") nothing changes: the fixture user and the prototype toast.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../test-support/park/componentsHarness";

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

vi.mock("../../auth/session", () => ({ session: fake }));
vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

import { ParkApp } from "./ParkApp";

const PROTOTYPE = "This is a prototype, so you stay signed in";
let assign: ReturnType<typeof vi.spyOn>;

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
  await act(async () => undefined);
};

async function open() {
  window.history.pushState({}, "", "/park/home");
  mount(<ParkApp />);
  await settle();
  click(q<HTMLButtonElement>(document.body, 'button[aria-label="Account menu"]'));
  await settle();
}

const menu = () => document.querySelector<HTMLElement>('[role="menu"][aria-label="Account"]');
const signOutItem = () =>
  qa<HTMLButtonElement>(menu() as HTMLElement, '[role="menuitem"]').find((b) =>
    (b.textContent ?? "").startsWith("Sign out"),
  );
const toastText = () =>
  document.querySelector('[role="status"], [role="alert"]')?.textContent ?? "";

beforeEach(() => {
  fake.state = { status: "unavailable" };
  fake.signOut.mockReset();
  fake.signOut.mockImplementation(async () => {
    fake.set({ status: "signed_out" });
  });
  assign = vi.spyOn(window.location, "assign").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

describe("FR-UX-10 ParkApp wires the account menu to the page's sign-in", () => {
  it("FR-UX-10 a Google person is shown by name and email", async () => {
    fake.state = { status: "google", displayName: "Sam Rivera", email: "sam@example.test" };
    await open();
    const text = menu()?.textContent ?? "";
    expect(text).toContain("Sam Rivera");
    expect(text).toContain("sam@example.test");
    expect(signOutItem()).toBeDefined();
  });

  it("FR-UX-10 a demo session is shown as 'Demo session'", async () => {
    fake.state = { status: "anonymous" };
    await open();
    expect(menu()?.textContent ?? "").toContain("Demo session");
    expect(signOutItem()).toBeDefined();
  });

  it("FR-UX-10 Sign out signs the page's session out once and loads '/' afresh", async () => {
    fake.state = { status: "google", displayName: "Sam Rivera", email: "sam@example.test" };
    await open();
    click(signOutItem() as HTMLButtonElement);
    await settle();
    expect(fake.signOut).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith("/");
  });

  it("FR-UX-10 a sign-out the SDK refused says so in plain words and loads nothing", async () => {
    fake.state = { status: "anonymous" };
    fake.signOut.mockImplementation(async () => {
      // the controller keeps the person's tokens unused; the page (a test with no gate) stays mounted
      fake.state = { status: "anonymous" };
      throw new Error("auth/network-request-failed");
    });
    await open();
    click(signOutItem() as HTMLButtonElement);
    await settle();
    expect(toastText()).toContain("Could not sign out. Try again.");
    expect(assign).not.toHaveBeenCalled();
  });

  it("FR-UX-10 with no sign-in here the fixture user and the prototype toast stay", async () => {
    fake.state = { status: "unavailable" };
    await open();
    click(signOutItem() as HTMLButtonElement);
    await settle();
    expect(fake.signOut).not.toHaveBeenCalled();
    expect(toastText()).toContain(PROTOTYPE);
  });
});
