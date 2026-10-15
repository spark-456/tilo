// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../test-support/park/componentsHarness";
import { SignInScreen } from "../auth/SignInScreen";
import { RECORDED_RUN } from "./recordedRun";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function landing(busy = false) {
  const onGoogle = vi.fn();
  const onDemo = vi.fn();
  const network = vi.fn();
  vi.stubGlobal("fetch", network);
  mount(
    <SignInScreen
      busy={busy}
      failed={false}
      failedText="Failed."
      onGoogle={onGoogle}
      onDemo={onDemo}
    />,
  );
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  return { onGoogle, onDemo, network };
}

it("LANDING_3 typing in the hero asks for sign-in without starting work or sending the prompt", async () => {
  const { onGoogle, onDemo, network } = await landing();
  const input = q<HTMLInputElement>(document.body, 'input[aria-label="What do you want done?"]');
  expect(input).not.toBeNull();
  act(() => {
    input.value = "Summarise my notes";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(onGoogle).toHaveBeenCalledExactlyOnceWith();
  expect(onDemo).not.toHaveBeenCalled();
  expect(network).not.toHaveBeenCalled();
  expect(qa(document.body, 'input[type="password"]')).toHaveLength(0);
  expect(qa(document.body, ".landing-btn--primary")).toHaveLength(1);
});

it("LANDING_3 Try it and keyboard submission use the existing sign-in callback", async () => {
  const { onGoogle, network } = await landing();
  click(q(document.body, ".landing-prompt button"));
  expect(onGoogle).toHaveBeenCalledExactlyOnceWith();
  act(() => {
    q(document.body, ".landing-prompt").dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
  expect(onGoogle).toHaveBeenCalledTimes(2);
  expect(network).not.toHaveBeenCalled();
});

it("LANDING_3 the prompt and Try it wait while sign-in is busy", async () => {
  const { onGoogle } = await landing(true);
  expect(q<HTMLInputElement>(document.body, ".landing-prompt input").disabled).toBe(true);
  expect(q<HTMLButtonElement>(document.body, ".landing-prompt button").disabled).toBe(true);
  click(q(document.body, ".landing-prompt button"));
  expect(onGoogle).not.toHaveBeenCalled();
});

it("LANDING_3 the static ticker labels the recorded source and uses recorded facts", async () => {
  await landing();
  const ticker = q(document.body, '[aria-label="Highlights from the recorded example"]');
  expect(ticker).not.toBeNull();
  expect(ticker.textContent).toContain("Recorded example");
  expect(ticker.textContent).toContain(RECORDED_RUN.facts.planned);
  expect(ticker.textContent).toContain(RECORDED_RUN.facts.done);
  expect(ticker.getAttribute("aria-live")).toBeNull();
});
