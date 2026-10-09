// @vitest-environment happy-dom
// ADR35_L4 / FR_CON_02 (LC-01, LC-06): the Connect and Disconnect buttons of the person's Google account on the
// Connectors page. Live only: with no ConnectFlow the page is exactly as before.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { flush, makeApp, renderPage } from "../../../../test-support/park/connectorsDom";
import type { ConnectFlow, ConnectionRow } from "../../../api/connect";
import { GoogleAccess } from "./GoogleAccess";

afterEach(cleanup);

const ROWS: ConnectionRow[] = [
  { id: "gmail", name: "Gmail", state: "available" },
  { id: "google_drive", name: "Google Drive", state: "available" },
  { id: "google_calendar", name: "Google Calendar", state: "available" },
];
const LINK = "https://accounts.google.com/o/oauth2/v2/auth?state=abcdefghijklmnop";

function flowOf(over: Partial<ConnectFlow> = {}) {
  const flow = {
    list: vi.fn(async () => ROWS),
    start: vi.fn(async () => ({ kind: "redirect" as const, url: LINK })),
    finish: vi.fn(),
    open: vi.fn(),
    disconnect: vi.fn(async () => true),
    ...over,
  };
  return flow as unknown as ConnectFlow & typeof flow;
}
const buttons = (c: HTMLElement) => Array.from(c.querySelectorAll("button"));
const byText = (c: HTMLElement, t: string) =>
  buttons(c).find((b) => b.textContent === t) as HTMLButtonElement;

describe("ADR35_L4_FR_CON_02_google_access", () => {
  it("ADR35_L4_FR_CON_02_connect_asks_for_read_then_opens_the_link", async () => {
    const flow = flowOf();
    const m = mount(<GoogleAccess flow={flow} />);
    await flush();
    const first = buttons(m.container)[0] as HTMLButtonElement;
    expect(first.textContent).toBe("Connect");
    click(first);
    await flush();
    expect(flow.start).toHaveBeenCalledWith("gmail", ["read"]);
    expect(flow.open).toHaveBeenCalledWith(LINK);
  });

  it("ADR35_L4_FR_CON_02_a_connect_that_cannot_start_says_so_and_opens_nothing", async () => {
    const flow = flowOf({ start: vi.fn(async () => ({ kind: "failed" as const })) });
    const m = mount(<GoogleAccess flow={flow} />);
    await flush();
    click(buttons(m.container)[0] as HTMLButtonElement);
    await flush();
    expect(flow.open).not.toHaveBeenCalled();
    expect(m.container.textContent).toContain("could not start the Google sign-in");
  });

  it("ADR35_L4_FR_CON_02_disconnect_warns_that_all_three_end_together_and_waits_for_confirmation", async () => {
    const rows: ConnectionRow[] = ROWS.map((r) => ({ ...r, state: "connected" }));
    const flow = flowOf({ list: vi.fn(async () => rows) });
    const m = mount(<GoogleAccess flow={flow} />);
    await flush();
    click(buttons(m.container)[1] as HTMLButtonElement);
    await flush();
    expect(m.container.textContent).toContain(
      "Disconnecting any one of them disconnects all three",
    );
    expect(flow.disconnect).not.toHaveBeenCalled(); // not until the person confirms
    click(byText(m.container, "Keep connected"));
    await flush();
    expect(flow.disconnect).not.toHaveBeenCalled();
    click(buttons(m.container)[1] as HTMLButtonElement);
    await flush();
    click(byText(m.container, "Disconnect all three"));
    await flush();
    expect(flow.disconnect).toHaveBeenCalledWith("google_drive");
    expect(m.container.textContent).toContain("Google is disconnected");
  });

  it("ADR35_L4_FR_CON_02_a_failed_disconnect_is_never_shown_as_done", async () => {
    const rows: ConnectionRow[] = [{ id: "gmail", name: "Gmail", state: "connected" }];
    const flow = flowOf({ list: vi.fn(async () => rows), disconnect: vi.fn(async () => false) });
    const m = mount(<GoogleAccess flow={flow} />);
    await flush();
    click(byText(m.container, "Disconnect"));
    await flush();
    click(byText(m.container, "Disconnect all three"));
    await flush();
    const text = m.container.textContent ?? "";
    expect(text).toContain("could not disconnect Google");
    expect(text).not.toContain("Google is disconnected");
  });

  it("ADR35_L4_FR_CON_02_an_unreadable_list_says_so", async () => {
    const flow = flowOf({ list: vi.fn(async () => Promise.reject(new Error("x"))) });
    const m = mount(<GoogleAccess flow={flow} />);
    await flush();
    expect(m.container.textContent).toContain("Could not read your Google connections");
  });

  it("ADR35_L4_FR_CON_02_the_page_shows_the_section_only_with_a_live_flow", async () => {
    const fixture = await renderPage(makeApp());
    await flush();
    expect(fixture.container.textContent).not.toContain("Your Google account");
  });
});
