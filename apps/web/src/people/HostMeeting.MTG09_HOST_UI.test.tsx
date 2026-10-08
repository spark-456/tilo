// @vitest-environment happy-dom
// MTG09_HOST_UI (FR-MTG-09, ticket MEETINGS-1): the "Host this meeting" button on S-26. Owner only, one
// POST with body {}, then the T3 gate card for the person to answer. The client never approves; nothing
// is created in the calendar until the person answers the card. Each refusal has its own sentence and
// no card. The HttpClient half is in api/http.MTG09_HOST_UI.test.ts.
import type { Card, Meeting } from "@tilo/contracts";
import { type ReactElement, act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { TiloApiError } from "../api/http";
import { S_26 } from "../screens/S_26";
import { HostMeeting } from "./HostMeeting";
import { ALL_MEETINGS, SIGNED_IN } from "./data";
import { canHostMeeting } from "./host";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SCHEDULED = ALL_MEETINGS.find((m) => m.id === "mt_q4_plan_next") as Meeting;
const GATE: Card = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W9",
  world_id: "w_meet_1",
  run_id: "r_meet_1",
  kind: "gate",
  rung: "gate",
  header: { building: "B1", agent: "A_dir" },
  what_happened: "Tilo is ready to invite 2 people to Q4 planning.",
  why_it_matters: "The invitation is sent from Tilo's calendar.",
  options: [
    { id: "approve", label: "Approve", suggested: false, irreversible: true },
    { id: "edit", label: "Edit first", suggested: false, irreversible: false },
    {
      id: "hold",
      label: "Hold",
      suggested: true,
      reason: "Nothing goes out.",
      irreversible: false,
    },
  ],
  add_context: false,
  actions: [],
  answer_channels: ["web", "mobile_web"],
  created_at: "2026-10-08T04:00:00.000Z",
  timeout: 3600,
  safe_default: "hold",
  gate: {
    id: "G1",
    action: {
      type: "create_meeting_event",
      connector: "meeting_host",
      exact: "Create the calendar event Q4 planning and invite 2 people.",
      item: null,
      destination: null,
    },
    recipients: ["asha@example.com", "priya@example.com"],
    irreversible: true,
    risk_tier: "T3",
  },
  consent: null,
};

interface Fake {
  hostMeeting: ReturnType<typeof vi.fn>;
  listCards: ReturnType<typeof vi.fn>;
  answerCard: ReturnType<typeof vi.fn>;
}
const fake = (over: Partial<Fake> = {}): Fake => ({
  hostMeeting: vi.fn(async () => ({ world_id: "w_meet_1" })),
  listCards: vi.fn(async () => [GATE]),
  answerCard: vi.fn(async () => undefined),
  ...over,
});

async function render(ui: ReactElement, client?: Fake) {
  const box = document.createElement("div");
  document.body.append(box);
  const tree = client ? (
    <ClientProvider client={client as unknown as TiloClient}>{ui}</ClientProvider>
  ) : (
    ui
  );
  await act(async () => createRoot(box).render(tree));
  return box;
}
const settle = () => act(async () => new Promise((r) => setTimeout(r, 150)));
const button = (box: Element) =>
  [...box.querySelectorAll("button")].find((b) => b.textContent === "Host this meeting") as
    | HTMLButtonElement
    | undefined;
const click = (el: Element | null | undefined) =>
  act(async () => {
    (el as HTMLElement).click();
  });
const host = (client: Fake, meeting: Meeting = SCHEDULED, me = SIGNED_IN) =>
  render(<HostMeeting meeting={meeting} me={me} pollMs={1} tries={3} />, client);
const say = (box: Element) => box.querySelector('[data-testid="host-status"]')?.textContent ?? "";

describe("MTG09_HOST_UI who sees the button", () => {
  it("MTG09_HOST_UI only the owner of a scheduled bot meeting can host it", () => {
    expect(canHostMeeting(SCHEDULED, SIGNED_IN)).toBe(true);
    expect(canHostMeeting(SCHEDULED, "u_priya")).toBe(false);
    expect(canHostMeeting({ ...SCHEDULED, status: "live" }, SIGNED_IN)).toBe(false);
    expect(canHostMeeting({ ...SCHEDULED, status: "discarded" }, SIGNED_IN)).toBe(false);
    expect(canHostMeeting({ ...SCHEDULED, source: "upload" }, SIGNED_IN)).toBe(false);
  });

  it("MTG09_HOST_UI the owner sees the button and the sentence that nothing is sent until they approve", async () => {
    const box = await host(fake());
    expect(button(box)).toBeDefined();
    expect(box.textContent).toMatch(/nothing is sent until you approve/i);
    expect(box.querySelectorAll("button.primary")).toHaveLength(1);
  });

  it("MTG09_HOST_UI anyone else sees no button and the page makes no call", async () => {
    const client = fake();
    const box = await host(client, SCHEDULED, "u_priya");
    expect(button(box)).toBeUndefined();
    expect(box.textContent).toBe("");
    await settle();
    expect(client.hostMeeting).not.toHaveBeenCalled();
    expect(client.listCards).not.toHaveBeenCalled();
  });

  it("MTG09_HOST_UI a meeting that is live, ended or uploaded has no button", async () => {
    for (const odd of [{ status: "live" }, { status: "minuted" }, { source: "upload" }] as const) {
      const box = await host(fake(), { ...SCHEDULED, ...odd } as Meeting);
      expect(button(box)).toBeUndefined();
    }
  });
});

describe("MTG09_HOST_UI the request", () => {
  it("MTG09_HOST_UI a click sends one request for this meeting, then shows the gate card from the world's cards", async () => {
    const client = fake();
    const box = await host(client);
    await click(button(box));
    await settle();
    expect(client.hostMeeting).toHaveBeenCalledTimes(1);
    expect(client.hostMeeting).toHaveBeenCalledWith("mt_q4_plan_next");
    expect(client.listCards).toHaveBeenCalledWith("w_meet_1");
    const card = box.querySelector('[data-testid="need-card"]');
    expect(card?.textContent).toContain(
      "Create the calendar event Q4 planning and invite 2 people.",
    );
    expect(card?.textContent).toContain("Cannot be undone");
    expect(card?.textContent).toMatch(/T3|a person always decides/i);
    expect(box.textContent).toMatch(/nothing is sent until you approve/i);
  });

  it("MTG09_HOST_UI the client never approves: no option is chosen and no answer is sent until the person acts", async () => {
    const client = fake();
    const box = await host(client);
    await click(button(box));
    await settle();
    expect(client.answerCard).not.toHaveBeenCalled();
    expect(box.querySelectorAll('input[type="radio"]:checked')).toHaveLength(0);
    expect(box.textContent).not.toMatch(/\bwas created\b|\bhas been sent\b|\bapproved\b/i);
    // Only the person's own choice and click answers it.
    const approve = [...box.querySelectorAll('input[type="radio"]')].find((i) =>
      i.closest("label")?.textContent?.startsWith("Approve"),
    ) as HTMLInputElement;
    await click(approve);
    const send = [...box.querySelectorAll("button")].find((b) => b.textContent === "Approve");
    await click(send);
    expect(client.answerCard).toHaveBeenCalledTimes(1);
    expect(client.answerCard).toHaveBeenCalledWith(GATE.id, { option_id: "approve" });
  });

  it("MTG09_HOST_UI the screen keeps one primary button: the host button gives way to the card's", async () => {
    const box = await host(fake());
    await click(button(box));
    await settle();
    expect(button(box)).toBeUndefined();
    expect(box.querySelectorAll("button.primary")).toHaveLength(1);
  });

  it("MTG09_HOST_UI no double submit: the button is disabled and busy while the request is in flight", async () => {
    let release: (v: { world_id: string }) => void = () => undefined;
    const client = fake({
      hostMeeting: vi.fn(
        () =>
          new Promise<{ world_id: string }>((r) => {
            release = r;
          }),
      ),
    });
    const box = await host(client);
    const b = button(box) as HTMLButtonElement;
    await click(b);
    expect(b.disabled).toBe(true);
    expect(b.getAttribute("aria-busy")).toBe("true");
    await click(b);
    await click(b);
    expect(client.hostMeeting).toHaveBeenCalledTimes(1);
    await act(async () => release({ world_id: "w_meet_1" }));
    await settle();
    expect(client.hostMeeting).toHaveBeenCalledTimes(1);
  });

  it("MTG09_HOST_UI the card may arrive a moment after the 200: the page asks again, then shows it", async () => {
    const listCards = vi
      .fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
      .mockResolvedValue([GATE]);
    const client = fake({ listCards });
    const box = await render(
      <HostMeeting meeting={SCHEDULED} me={SIGNED_IN} pollMs={1} tries={5} />,
      client,
    );
    await click(button(box));
    await settle();
    expect(listCards.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(box.querySelector('[data-testid="need-card"]')).not.toBeNull();
  });

  it("MTG09_HOST_UI a card of another action in the world's list is not shown as this gate", async () => {
    const other: Card = {
      ...GATE,
      gate: GATE.gate && { ...GATE.gate, action: { ...GATE.gate.action, type: "send_email" } },
    };
    const client = fake({ listCards: vi.fn(async () => [other]) });
    const box = await host(client);
    await click(button(box));
    await settle();
    expect(box.querySelector('[data-testid="need-card"]')).toBeNull();
    expect(say(box)).toMatch(/approval card has not appeared/i);
  });

  it("MTG09_HOST_UI when no card appears the page says so and points to Needs you; nothing is claimed as done", async () => {
    const client = fake({ listCards: vi.fn(async () => []) });
    const box = await host(client);
    await click(button(box));
    await settle();
    expect(say(box)).toMatch(/approval card has not appeared/i);
    expect(box.querySelector('a[href="/needs-you"]')).not.toBeNull();
    expect(say(box)).not.toMatch(/created|invited|sent\b(?! until)/i);
  });
});

describe("MTG09_HOST_UI every refusal has its own sentence and no card", () => {
  const cases: Array<[string, unknown, RegExp]> = [
    [
      "404",
      new TiloApiError("x", 404, false, true, null, false, "not_found"),
      /meeting was not found/i,
    ],
    [
      "409 not_hostable",
      new TiloApiError("x", 409, false, true, null, false, "not_hostable"),
      /cannot be hosted/i,
    ],
    [
      "409 already_hosted",
      new TiloApiError("x", 409, false, true, null, false, "already_hosted"),
      /already requested/i,
    ],
    ["422 MH-02", new TiloApiError("x", 422, false, true, null, false, "MH-02"), /time/i],
    ["422 MH-03", new TiloApiError("x", 422, false, true, null, false, "MH-03"), /invite/i],
    [
      "422 other",
      new TiloApiError("x", 422, false, true, null, false, null),
      /cannot host this meeting as it stands/i,
    ],
    [
      "403",
      new TiloApiError("x", 403, false, true, null, false, "forbidden"),
      /do not have access/i,
    ],
    [
      "503",
      new TiloApiError("x", 503, true, true, null, false, "not_configured"),
      /Hosting isn't connected yet/,
    ],
    [
      "network",
      new TiloApiError("x", null, true, true),
      /could not be reached.*could not confirm/i,
    ],
  ];

  it.each(cases)("MTG09_HOST_UI %s", async (_name, error, expected) => {
    const client = fake({
      hostMeeting: vi.fn(async () => {
        throw error;
      }),
    });
    const box = await host(client);
    await click(button(box));
    await settle();
    expect(say(box)).toMatch(expected);
    expect(say(box)).not.toContain("not_hostable");
    expect(say(box)).not.toContain("MH-0");
    expect(box.querySelector('[data-testid="need-card"]')).toBeNull();
    expect(client.listCards).not.toHaveBeenCalled();
    expect(button(box)?.disabled).toBe(false); // it can be tried again once the cause is gone
  });

  it("MTG09_HOST_UI the sentences are all different", async () => {
    const seen = new Set<string>();
    for (const [, error] of cases) {
      const client = fake({
        hostMeeting: vi.fn(async () => {
          throw error;
        }),
      });
      const box = await host(client);
      await click(button(box));
      await settle();
      seen.add(say(box));
    }
    expect(seen.size).toBe(cases.length);
  });

  it("MTG09_HOST_UI a client with no host call says hosting is not connected and sends nothing", async () => {
    const bare = { listCards: vi.fn(), answerCard: vi.fn() } as unknown as Fake;
    const box = await host(bare);
    await click(button(box));
    await settle();
    expect(say(box)).toMatch(/Hosting isn't connected yet/);
    expect(bare.listCards).not.toHaveBeenCalled();
    expect(box.querySelector('[data-testid="need-card"]')).toBeNull();
  });
});

describe("MTG09_HOST_UI on S-26", () => {
  it("MTG09_HOST_UI the upcoming bot meeting of the signed-in owner shows the button; a minuted one does not", async () => {
    const upcoming = await render(<S_26 params={["mt_q4_plan_next"]} />);
    expect(button(upcoming)).toBeDefined();
    expect(upcoming.querySelectorAll("button.primary")).toHaveLength(1);
    const minuted = await render(<S_26 params={["mt_q4_plan"]} />);
    expect(button(minuted)).toBeUndefined();
    const live = await render(<S_26 params={["mt_design_review"]} />);
    expect(button(live)).toBeUndefined();
  });

  it("MTG09_HOST_UI the sample (fixture) client shows no gate card: hosting is not connected", async () => {
    const box = await render(<S_26 params={["mt_q4_plan_next"]} />);
    await click(button(box));
    await settle();
    expect(box.textContent).toContain("Hosting isn't connected yet");
    expect(box.querySelector('[data-testid="need-card"]')).toBeNull();
  });

  it("MTG09_HOST_UI through a connected client the S-26 button reaches the gate card", async () => {
    const client = fake();
    const box = await render(<S_26 params={["mt_q4_plan_next"]} />, client);
    await click(button(box));
    await settle();
    expect(client.hostMeeting).toHaveBeenCalledWith("mt_q4_plan_next");
    expect(box.querySelector('[data-testid="need-card"]')).not.toBeNull();
  });
});
