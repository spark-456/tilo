// @vitest-environment happy-dom
// SEC-15 / SIGNIN-FIX (BQ-SIGNIN-4): the page is loaded afresh after a sign-out only when the SDK really ended the
// session. A sign-out the controller reports with `signOutFailed` leaves the SDK's user in place: a full load would let
// the SDK restore the person, so nothing reloads. A failure that is not reported that way (a controller that threw)
// reloads nothing either (signOut.SIGNIN.test.ts pins that).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => {
  const session = {
    state: { status: "google" } as Record<string, unknown>,
    getState() {
      return this.state;
    },
    signOut: vi.fn(async () => undefined),
  };
  return session;
});

vi.mock("../auth/session", () => ({ session: fake }));

import { endSession } from "./signOut";

const flush = async () => {
  for (let i = 0; i < 5; i++) await Promise.resolve();
};

let assign: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fake.state = { status: "google" };
  fake.signOut.mockReset();
  assign = vi.spyOn(window.location, "assign").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SEC-15 SIGNIN-FIX no reload when the SDK's sign-out failed", () => {
  it("SEC-15 SIGNIN-FIX a sign-out reported as failed (signOutFailed) loads nothing", async () => {
    fake.signOut.mockImplementation(async () => {
      fake.state = { status: "signed_out", signOutFailed: true };
    });
    expect(endSession()).toBe(true);
    await flush();
    expect(fake.signOut).toHaveBeenCalledTimes(1);
    expect(assign).not.toHaveBeenCalled();
  });

  it("SEC-15 SIGNIN-FIX a sign-out that worked still loads '/' afresh, once", async () => {
    fake.signOut.mockImplementation(async () => {
      fake.state = { status: "signed_out" };
    });
    endSession();
    await flush();
    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith("/");
  });
});
