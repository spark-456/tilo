// @vitest-environment happy-dom
// SIGNIN-PARK (Opus follow-up): two clicks in one batch start one sign-in, not a Google and a demo one together.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, qa } from "../../test-support/park/componentsHarness";
import { SignInGate } from "./SignInGate";
import type { AuthController } from "./auth";

afterEach(cleanup);

const SIGNED_OUT = { status: "signed_out" } as const; // one object: the store must see a stable snapshot

describe("SIGNIN-PARK the gate starts one sign-in at a time", () => {
  it("SIGNIN-PARK a Google click and a demo click in the same batch start only the first", async () => {
    let release: (() => void) | undefined;
    const pending = new Promise<{ ok: true }>((resolve) => {
      release = () => resolve({ ok: true });
    });
    const auth: AuthController = {
      getState: () => SIGNED_OUT,
      subscribe: () => () => undefined,
      idToken: vi.fn(async () => null),
      signInWithGoogle: vi.fn(() => pending),
      signInAnonymously: vi.fn(async () => ({ ok: true as const })),
      signOut: vi.fn(async () => undefined),
    };
    mount(
      <SignInGate auth={auth}>
        <div />
      </SignInGate>,
    );
    const buttons = qa<HTMLButtonElement>(document.body, "button");
    const google = buttons.find((b) => /google/i.test(b.textContent ?? "")) as HTMLButtonElement;
    const demo = buttons.find((b) => /demo/i.test(b.textContent ?? "")) as HTMLButtonElement;
    await act(async () => {
      google.click();
      demo.click();
    });
    expect(auth.signInWithGoogle).toHaveBeenCalledTimes(1);
    expect(auth.signInAnonymously).not.toHaveBeenCalled();
    release?.();
    await act(async () => undefined);
  });
});
