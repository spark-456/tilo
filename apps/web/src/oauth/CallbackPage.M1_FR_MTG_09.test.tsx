// @vitest-environment happy-dom
// M1 / FR_MTG_09: the callback page names the meeting host when that is what was connected, and a failed sign-in
// offers one way to try again (the Connectors page, where the sign-in buttons are). It still shows no code or state.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../test-support/park/componentsHarness";
import { type ConnectFlow, HOST_CONNECTED_TEXT, RESULT_TEXT } from "../api/connect";
import CallbackPage from "./CallbackPage";

afterEach(cleanup);
const STATE = "abcdefghijklmnop-_0123";
const settle = async () => {
  await act(async () => undefined);
  await act(async () => undefined);
};
const page = (result: Awaited<ReturnType<ConnectFlow["finish"]>>, back = vi.fn()) =>
  mount(
    <CallbackPage
      params={{ state: STATE, code: "4/abc" }}
      flow={() => ({ finish: vi.fn(async () => result) }) as unknown as ConnectFlow}
      back={back}
    />,
  );

describe("M1_FR_MTG_09_callback_page", () => {
  it("M1_FR_MTG_09_a_connected_meeting_host_is_named_and_the_way_back_is_connectors", async () => {
    const back = vi.fn();
    const m = page(
      {
        kind: "connected",
        lines: ["Create meetings on its own calendar"],
        connector: "meeting_host",
      },
      back,
    );
    await settle();
    const text = m.container.textContent ?? "";
    expect(text).toContain(HOST_CONNECTED_TEXT);
    expect(text).not.toContain(RESULT_TEXT.connected);
    expect(text).toContain("Create meetings on its own calendar");
    expect(text).not.toContain(STATE);
    const button = m.container.querySelector("button") as HTMLButtonElement;
    expect(button.textContent).toBe("Back to Connectors");
    click(button);
    expect(back).toHaveBeenCalledTimes(1);
  });

  it.each(["not_granted", "wrong_account", "start_again", "unavailable"] as const)(
    "M1_FR_MTG_09_%s_offers_try_again_which_goes_to_connectors",
    async (kind) => {
      const back = vi.fn();
      const m = page({ kind }, back);
      await settle();
      expect(m.container.textContent).toContain(RESULT_TEXT[kind]);
      const button = m.container.querySelector("button") as HTMLButtonElement;
      expect(button.textContent).toBe("Try again from Connectors");
      click(button);
      expect(back).toHaveBeenCalledTimes(1);
    },
  );
});
