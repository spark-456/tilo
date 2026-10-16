// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { flush } from "../../../../test-support/park/connectorsDom";
import { type ConnectFlow, type ConnectionRow, createConnectFlow } from "../../../api/connect";
import { GoogleAccess } from "./GoogleAccess";

afterEach(cleanup);

const rows: ConnectionRow[] = [
  { id: "gmail", name: "Gmail", state: "available" },
  { id: "google_drive", name: "Google Drive", state: "available" },
  { id: "google_calendar", name: "Google Calendar", state: "available" },
];

const flow = (list: ConnectionRow[] = rows) =>
  ({
    list: vi.fn(async () => list),
    start: vi.fn(async () => ({ kind: "failed" as const })),
    open: vi.fn(),
  }) as unknown as ConnectFlow & {
    start: ReturnType<typeof vi.fn>;
  };

describe("WORKSPACE_TOOLS_WT_06 connector read grants", () => {
  it("WORKSPACE_TOOLS_WT_06 keeps only server-reported scopes in the connection view", async () => {
    const f = createConnectFlow({
      getJson: async () => ({
        connectors: [
          {
            id: "gmail",
            name: "Gmail",
            state: "connected",
            scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
          },
          { id: "google_drive", name: "Google Drive", state: "connected", scopes: "not a list" },
        ],
      }),
      postJson: async () => ({}),
    });
    expect(await f.list()).toEqual([
      {
        id: "gmail",
        name: "Gmail",
        state: "connected",
        scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
      },
      { id: "google_drive", name: "Google Drive", state: "connected" },
    ]);
  });

  it.each([
    ["Read mail", "gmail", ["read", "search"]],
    ["Read Drive", "google_drive", ["read", "list"]],
    ["Read calendar", "google_calendar", ["read"]],
  ])(
    "WORKSPACE_TOOLS_WT_06 %s requests only its declared capabilities",
    async (label, id, caps) => {
      const f = flow();
      const m = mount(<GoogleAccess flow={f} />);
      await flush();
      const button = [...m.container.querySelectorAll("button")].find(
        (b) => b.textContent === label,
      );
      expect(button).toBeDefined();
      click(button as HTMLButtonElement);
      await flush();
      expect(f.start).toHaveBeenCalledWith(id, caps);
    },
  );

  it("WORKSPACE_TOOLS_WT_01 explains own-world access before connecting", async () => {
    const m = mount(<GoogleAccess flow={flow()} />);
    await flush();
    expect(m.container.textContent).toContain("only in your own worlds");
    expect(m.container.textContent).toContain("search and read your mail");
    expect(m.container.textContent).toContain("read your calendar");
    expect(m.container.textContent).toContain("files you pick");
  });

  it("WORKSPACE_TOOLS_WT_06 shows each read grant from server scopes", async () => {
    const m = mount(
      <GoogleAccess
        flow={flow([
          {
            id: "gmail",
            name: "Gmail",
            state: "connected",
            scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
          },
          {
            id: "google_drive",
            name: "Google Drive",
            state: "connected",
            scopes: ["https://www.googleapis.com/auth/drive.file"],
          },
          { id: "google_calendar", name: "Google Calendar", state: "connected", scopes: [] },
        ])}
      />,
    );
    await flush();
    const cards = [...m.container.querySelectorAll(".park-connectors-avail")];
    expect(cards[0]?.textContent).toContain("Read mail granted");
    expect(cards[1]?.textContent).toContain("Read Drive granted");
    expect(cards[2]?.textContent).toContain("Read calendar not granted");
    expect(cards[2]?.textContent).toContain("Read calendar");
  });
});
