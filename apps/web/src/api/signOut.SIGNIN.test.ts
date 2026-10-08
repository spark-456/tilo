// @vitest-environment happy-dom
// SEC-15 / SIGNIN follow-up (BQ-SIGNIN-4): after a successful sign-out the page is loaded afresh at "/", so the
// module-level HTTP client of the person who left cannot serve the next person on a shared machine. With no session
// (status "unavailable": a local host, the fixture world) nothing is signed out and nothing reloads; a sign-out that
// did not end the session reloads nothing.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fake = vi.hoisted(() => {
  const session = {
    status: "google" as "google" | "anonymous" | "unavailable" | "signed_out",
    getState() {
      return { status: this.status };
    },
    signOut: vi.fn(async () => {
      session.status = "signed_out";
    }),
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
  fake.status = "google";
  fake.signOut.mockClear();
  fake.signOut.mockImplementation(async () => {
    fake.status = "signed_out";
  });
  assign = vi.spyOn(window.location, "assign").mockImplementation(() => undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SEC-15 SIGNIN follow-up full page load after sign-out", () => {
  for (const status of ["google", "anonymous"] as const) {
    it(`SEC-15 SIGNIN a ${status} sign-out that ends the session loads "/" afresh, once`, async () => {
      fake.status = status;
      expect(endSession()).toBe(true);
      await flush();
      expect(fake.signOut).toHaveBeenCalledTimes(1);
      expect(assign).toHaveBeenCalledTimes(1);
      expect(assign).toHaveBeenCalledWith("/");
    });
  }

  it("SEC-15 SIGNIN no session (unavailable): returns false, signs nothing out, reloads nothing", async () => {
    fake.status = "unavailable";
    expect(endSession()).toBe(false);
    await flush();
    expect(fake.signOut).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("SEC-15 SIGNIN a sign-out that did not end the session reloads nothing and does not throw", async () => {
    fake.signOut.mockImplementation(async () => {
      throw new Error("auth/network-request-failed");
    });
    expect(endSession()).toBe(true);
    await flush();
    expect(assign).not.toHaveBeenCalled();
  });

  it("SEC-15 SIGNIN the page is not loaded before the sign-out has finished", async () => {
    let finish: (() => void) | undefined;
    fake.signOut.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = () => {
            fake.status = "signed_out";
            resolve();
          };
        }),
    );
    endSession();
    await flush();
    expect(assign).not.toHaveBeenCalled();
    finish?.();
    await flush();
    expect(assign).toHaveBeenCalledTimes(1);
  });
});
