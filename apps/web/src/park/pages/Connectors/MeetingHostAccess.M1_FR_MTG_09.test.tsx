// @vitest-environment happy-dom
// M1 / FR_MTG_09 / FR_CON_02: "Sign in the meeting host" on the Connectors page. Every state says what is true: the
// button starts the existing connect flow for `meeting_host` (send), nothing shows as connected until the live status
// read says so, a demo or replay session says it needs a real sign-in, and nothing is secret on the page.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { flush, makeApp, renderPage, textOf } from "../../../../test-support/park/connectorsDom";
import type { ConnectFlow } from "../../../api/connect";
import { createLiveApi } from "../../api/liveApi";
import { MeetingHostAccess } from "./MeetingHostAccess";

afterEach(cleanup);

const LINK = "https://accounts.google.com/o/oauth2/v2/auth?state=abcdefghijklmnop";
type Status = Awaited<ReturnType<ConnectFlow["meetingHost"]>>;

function flowOf(status: Status | Error = "available", over: Partial<ConnectFlow> = {}) {
  const flow = {
    meetingHost: vi.fn(async () => {
      if (status instanceof Error) throw status;
      return status;
    }),
    start: vi.fn(async () => ({ kind: "redirect" as const, url: LINK })),
    open: vi.fn(),
    disconnect: vi.fn(async () => "done" as const),
    ...over,
  };
  return flow as unknown as ConnectFlow & typeof flow;
}
const buttons = (c: HTMLElement) => Array.from(c.querySelectorAll("button"));
const byText = (c: HTMLElement, t: string) =>
  buttons(c).find((b) => b.textContent === t) as HTMLButtonElement;

describe("M1_FR_MTG_09_meeting_host_access", () => {
  it("M1_FR_MTG_09_not_connected_offers_the_sign_in_and_it_starts_the_send_flow", async () => {
    const flow = flowOf("available");
    const m = mount(<MeetingHostAccess flow={flow} />);
    await flush();
    expect(textOf(m.container)).toContain("Not connected");
    click(byText(m.container, "Sign in the meeting host"));
    await flush();
    expect(flow.start).toHaveBeenCalledWith("meeting_host", ["send"]);
    expect(flow.open).toHaveBeenCalledWith(LINK);
  });

  it("M1_FR_MTG_09_the_copy_says_to_sign_in_as_the_bot_and_that_tilo_never_sees_the_password", async () => {
    const m = mount(<MeetingHostAccess flow={flowOf("available")} />);
    await flush();
    const text = textOf(m.container);
    expect(text).toContain("meeting bot's own Google account");
    expect(text).toContain("not your own");
    expect(text).toContain("never sees");
    expect(text).not.toMatch(/password:|<input/i);
    expect(m.container.querySelector("input")).toBeNull();
  });

  it("M1_FR_MTG_09_connecting_disables_the_button_and_says_so", async () => {
    const held: { release: (v: { kind: "failed" }) => void } = { release: () => undefined };
    const flow = flowOf("available", {
      start: vi.fn(
        () =>
          new Promise((r) => {
            held.release = r;
          }),
      ) as never,
    });
    const m = mount(<MeetingHostAccess flow={flow} />);
    await flush();
    click(byText(m.container, "Sign in the meeting host"));
    await flush();
    const busy = buttons(m.container)[0] as HTMLButtonElement;
    expect(busy.disabled).toBe(true);
    expect(busy.textContent).toBe("Opening Google");
    held.release({ kind: "failed" });
    await flush();
  });

  it("M1_FR_MTG_09_a_start_that_fails_says_so_opens_nothing_and_offers_a_retry", async () => {
    const flow = flowOf("available", { start: vi.fn(async () => ({ kind: "failed" as const })) });
    const m = mount(<MeetingHostAccess flow={flow} />);
    await flush();
    click(byText(m.container, "Sign in the meeting host"));
    await flush();
    expect(flow.open).not.toHaveBeenCalled();
    expect(textOf(m.container)).toContain("could not start the meeting host sign-in");
    expect(byText(m.container, "Sign in the meeting host").disabled).toBe(false);
  });

  it("M1_FR_MTG_09_a_blocked_redirect_says_the_browser_did_not_open_google", async () => {
    const flow = flowOf("available", {
      open: vi.fn(() => {
        throw new Error("blocked");
      }),
    });
    const m = mount(<MeetingHostAccess flow={flow} />);
    await flush();
    click(byText(m.container, "Sign in the meeting host"));
    await flush();
    const text = textOf(m.container);
    expect(text).toContain("browser did not open Google");
    expect(text).not.toContain("Connected");
    expect(byText(m.container, "Sign in the meeting host").disabled).toBe(false);
  });

  it("M1_FR_MTG_09_connected_shows_only_after_the_status_read_and_disconnect_waits_for_confirmation", async () => {
    const flow = flowOf("connected");
    const m = mount(<MeetingHostAccess flow={flow} />);
    expect(textOf(m.container)).not.toContain("Connected"); // before the read: not claimed
    await flush();
    expect(textOf(m.container)).toContain("Connected");
    expect(buttons(m.container).some((b) => b.textContent === "Sign in the meeting host")).toBe(
      false,
    );
    click(byText(m.container, "Disconnect"));
    await flush();
    expect(flow.disconnect).not.toHaveBeenCalled();
    expect(textOf(m.container)).toContain("will not be sent");
    click(byText(m.container, "Keep connected"));
    await flush();
    expect(flow.disconnect).not.toHaveBeenCalled();
    click(byText(m.container, "Disconnect"));
    await flush();
    click(byText(m.container, "Disconnect the meeting host"));
    await flush();
    expect(flow.disconnect).toHaveBeenCalledWith("meeting_host");
    expect(textOf(m.container)).toContain("The meeting host is disconnected");
  });

  it("M1_FR_MTG_09_an_unconfirmed_revoke_is_never_shown_as_done", async () => {
    const flow = flowOf("connected", { disconnect: vi.fn(async () => "revoke_pending" as const) });
    const m = mount(<MeetingHostAccess flow={flow} />);
    await flush();
    click(byText(m.container, "Disconnect"));
    await flush();
    click(byText(m.container, "Disconnect the meeting host"));
    await flush();
    const text = textOf(m.container);
    expect(text).toContain("did not confirm");
    expect(text).toContain("Third-party access");
    expect(text).not.toContain("is disconnected");
  });

  it("M1_FR_MTG_09_a_failed_disconnect_says_nothing_changed", async () => {
    const flow = flowOf("connected", { disconnect: vi.fn(async () => "failed" as const) });
    const m = mount(<MeetingHostAccess flow={flow} />);
    await flush();
    click(byText(m.container, "Disconnect"));
    await flush();
    click(byText(m.container, "Disconnect the meeting host"));
    await flush();
    expect(textOf(m.container)).toContain("could not disconnect the meeting host");
    expect(textOf(m.container)).not.toContain("is disconnected");
  });

  it("M1_FR_MTG_09_an_expired_sign_in_says_needs_attention_and_offers_signing_in_again", async () => {
    const m = mount(<MeetingHostAccess flow={flowOf("attention")} />);
    await flush();
    expect(textOf(m.container)).toContain("Needs attention");
    expect(byText(m.container, "Sign in again")).toBeTruthy();
  });

  it.each([["unknown" as const], [new Error("down")]])(
    "M1_FR_MTG_09_an_unconfirmed_state_claims_nothing_and_offers_a_check_again_%#",
    async (status) => {
      const flow = flowOf(status);
      const m = mount(<MeetingHostAccess flow={flow} />);
      await flush();
      const text = textOf(m.container);
      expect(text).toContain("could not confirm");
      expect(text).not.toMatch(/Connected|Not connected/);
      expect(buttons(m.container).some((b) => b.textContent === "Sign in the meeting host")).toBe(
        false,
      );
      click(byText(m.container, "Check again"));
      await flush();
      expect(flow.meetingHost).toHaveBeenCalledTimes(2);
    },
  );

  it("M1_FR_MTG_09_with_no_live_flow_a_demo_or_replay_session_says_it_needs_a_real_sign_in", () => {
    const m = mount(<MeetingHostAccess flow={null} />);
    const text = textOf(m.container);
    expect(text).toContain("needs a real Tilo sign-in");
    expect(buttons(m.container)).toHaveLength(0);
  });

  it("M1_FR_MTG_09_the_connectors_page_shows_the_demo_note_on_live_data_and_the_button_with_a_flow", async () => {
    const body = {
      connectors: [
        {
          id: "crm",
          name: "Actual CRM",
          state: "connected",
          state_known: true,
          scopes: [],
          expires_at: null,
        },
      ],
    };
    const fetch = vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
    const api = createLiveApi({ baseUrl: "https://api.test", fetch });
    const demo = await renderPage(makeApp(), api);
    expect(textOf(demo.container)).toContain("needs a real Tilo sign-in");
    cleanup();
    const flow = flowOf("available", { list: vi.fn(async () => []) } as never);
    const { ConnectorsPage } = await import("./ConnectorsPage");
    const { ParkProvider } = await import("../../app/context");
    const { fakeScheduler } = await import("../../../../test-support/park/appHarness");
    const sch = fakeScheduler();
    const m = mount(
      <ParkProvider api={api} schedule={sch.schedule} viewport={{ vw: 1440, vh: 900 }}>
        <ConnectorsPage app={makeApp()} flow={flow} />
      </ParkProvider>,
    );
    await flush();
    expect(byText(m.container, "Sign in the meeting host")).toBeTruthy();
  });
});
