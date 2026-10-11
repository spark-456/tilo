// @vitest-environment happy-dom
// ADR35_L4 / FR_CON_02 (LC-02, LC-04): the callback route. The code and state leave the address bar and history before
// anything else; the page posts only a matching state, with the person's ID token through the api client, and says the
// result in plain words. It shows neither value and offers the way back to Connectors.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../test-support/park/componentsHarness";
import { type CallbackParams, type ConnectFlow, RESULT_TEXT } from "../api/connect";
import CallbackPage from "./CallbackPage";
import { forgetCallbackParams, takeCallbackParams } from "./capture";
import { isOAuthCallback } from "./paths";

const SECRET = ["4", "0A", "x".repeat(20)].join("/"); // assembled at run time
const STATE = "abcdefghijklmnop-_0123";

beforeEach(() => forgetCallbackParams());
afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
  vi.restoreAllMocks();
});

const settle = async () => {
  await act(async () => undefined);
  await act(async () => undefined);
};

describe("ADR35_L4_FR_CON_02_callback_route", () => {
  it("ADR35_L4_FR_CON_02_the_path_is_exactly_the_callback", () => {
    expect(isOAuthCallback("/oauth/google/callback")).toBe(true);
    expect(isOAuthCallback("/oauth/google/callback/")).toBe(true);
    for (const p of ["/oauth/google", "/oauth/google/callback/x", "/connectors", "/"]) {
      expect(isOAuthCallback(p)).toBe(false);
    }
  });

  it("ADR35_L4_FR_CON_02_the_address_is_replaced_before_the_values_are_returned_and_they_are_held_once", () => {
    window.history.replaceState(
      null,
      "",
      `/oauth/google/callback?code=${encodeURIComponent(SECRET)}&state=${STATE}#frag`,
    );
    const order: string[] = [];
    const real = window.history.replaceState.bind(window.history);
    vi.spyOn(window.history, "replaceState").mockImplementation((...a) => {
      order.push(`replace:${window.location.search.slice(0, 6)}`);
      real(...a);
    });
    const got = takeCallbackParams();
    order.push("returned");
    expect(order).toEqual(["replace:?code=", "returned"]);
    expect(got).toEqual({ state: STATE, code: SECRET });
    expect(window.location.search).toBe("");
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/oauth/google/callback");
    expect(takeCallbackParams()).toBe(got); // a second render gets the same value; the address is not read again
  });

  it("ADR35_L4_FR_CON_02_an_address_with_no_state_gives_null_and_googles_error_word_is_kept", () => {
    window.history.replaceState(null, "", "/oauth/google/callback?code=abc");
    expect(takeCallbackParams()).toBeNull();
    expect(window.location.search).toBe("");
    forgetCallbackParams();
    window.history.replaceState(
      null,
      "",
      `/oauth/google/callback?state=${STATE}&error=access_denied`,
    );
    expect(takeCallbackParams()).toEqual({ state: STATE, error: "access_denied" });
  });

  const page = (params: CallbackParams | null, flow: ConnectFlow | null, back = vi.fn()) =>
    mount(<CallbackPage params={params} flow={() => flow} back={back} />);
  const fake = (result: Awaited<ReturnType<ConnectFlow["finish"]>>) => {
    const finish = vi.fn(async () => result);
    return { finish, flow: { finish } as unknown as ConnectFlow };
  };

  it("ADR35_L4_FR_CON_02_the_page_finishes_once_and_says_what_google_granted", async () => {
    const { finish, flow } = fake({ kind: "connected", lines: ["Read your Gmail messages"] });
    const back = vi.fn();
    const m = page({ state: STATE, code: SECRET }, flow, back);
    await settle();
    expect(finish).toHaveBeenCalledTimes(1);
    expect(finish).toHaveBeenCalledWith({ state: STATE, code: SECRET });
    const text = m.container.textContent ?? "";
    expect(text).toContain(RESULT_TEXT.connected);
    expect(text).toContain("Read your Gmail messages");
    expect(text).not.toContain(SECRET);
    expect(text).not.toContain(STATE);
    click(m.container.querySelector("button") as HTMLButtonElement);
    expect(back).toHaveBeenCalledTimes(1);
  });

  it.each(["not_granted", "wrong_account", "start_again", "unavailable"] as const)(
    "ADR35_L4_FR_CON_02_the_page_says_%s_in_plain_words_with_a_way_back",
    async (kind) => {
      const { flow } = fake({ kind });
      const m = page({ state: STATE, error: "access_denied" }, flow);
      await settle();
      expect(m.container.textContent).toContain(RESULT_TEXT[kind]);
      expect(m.container.querySelector("button")?.textContent).toBe("Back to Connectors");
    },
  );

  it("ADR35_L4_FR_CON_02_no_params_or_no_flow_posts_nothing", async () => {
    const { finish, flow } = fake({ kind: "connected", lines: ["x"] });
    const none = page(null, flow);
    await settle();
    expect(none.container.textContent).toContain(RESULT_TEXT.start_again);
    const noFlow = page({ state: STATE, code: SECRET }, null);
    await settle();
    expect(noFlow.container.textContent).toContain(RESULT_TEXT.unavailable);
    expect(finish).not.toHaveBeenCalled();
  });

  it("ADR35_L4_FR_CON_02_a_flow_that_throws_reads_as_unavailable_not_a_crash", async () => {
    const flow = {
      finish: vi.fn(async () => Promise.reject(new Error(SECRET))),
    } as unknown as ConnectFlow;
    const m = page({ state: STATE, code: SECRET }, flow);
    await settle();
    expect(m.container.textContent).toContain(RESULT_TEXT.unavailable);
    expect(m.container.textContent).not.toContain(SECRET);
  });
});
