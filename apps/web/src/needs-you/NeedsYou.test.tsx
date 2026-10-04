// @vitest-environment happy-dom
// AGW-05 S-06 card and S-07 gate sheet (FR-HIL-01 UI side, FR-WLD-09, PRD 18.4, 9.4 HR-1, HR-7).
import type { Card, Event } from "@tilo/contracts";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  GATE_REPLY,
  GATE_SAVE,
  QUESTION,
  RUN_A,
  RUN_B,
  answered,
  liveClient,
  policyApplied,
  requested,
  resolved,
  routed,
} from "../../test-support/needsYou";
import { ClientProvider } from "../api/ClientProvider";
import { CARDS_VALID } from "../api/fixtures/cards";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { S_06 } from "../screens/S_06";
import { S_07 } from "../screens/S_07";
import { CONFIRM_MS, CardView } from "./CardView";
import { GateSheet } from "./GateSheet";
import { gatesOf } from "./gates";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
  window.history.replaceState({}, "", "/");
  vi.useRealTimers();
});

async function draw(node: React.ReactElement): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(node));
  return container;
}

const labels = (c: HTMLElement) =>
  [...c.querySelectorAll('[role="radiogroup"] b')].map((b) => b.textContent);
const radio = (c: HTMLElement, value: string) =>
  [...c.querySelectorAll<HTMLInputElement>("input[type=radio]")].find((r) => r.value === value);
const primary = (c: HTMLElement) => c.querySelector<HTMLButtonElement>("button.primary");
const sheet = (c: HTMLElement) => c.querySelector('[data-testid="gate-sheet"]');
const choose = (c: HTMLElement, value: string) => act(async () => radio(c, value)?.click());
const press = (c: HTMLElement) => act(async () => primary(c)?.click());

const view = (card: Card = GATE_REPLY, events: Event[] = [requested(1)]) => {
  const record = gatesOf(events)[0];
  if (!record) throw new Error("no gate");
  return <GateSheet record={record} card={card} layout={LAYOUT_VILLAGE_BASIC} answer={null} />;
};
const SECOND = "01JB5VQ0000000000000009003";
const saveRequest = (seq: number, data: object = {}) =>
  requested(seq, GATE_SAVE.id, "G2", RUN_A, {
    action_type: "save_file",
    risk_tier: "T1",
    irreversible: false,
    ...data,
  });

/** S-07 on a live client whose cards are `cards`; `url` is the address the sheet reads at mount. */
async function sheetPage(cards: Card[], url = "/needs-you/gate") {
  window.history.replaceState({}, "", url);
  const live = liveClient(cards);
  const c = await draw(
    <ClientProvider client={live.client}>
      <S_07 />
    </ClientProvider>,
  );
  return { ...live, c };
}

describe("FR-HIL-01 S-06: renders every card fixture in contracts/fixtures/card/valid", () => {
  for (const [i, card] of CARDS_VALID.entries()) {
    it(`card ${i + 1} (${card.rung}) shows header, what happened, why it matters and options`, async () => {
      const c = await draw(<CardView card={card} layout={LAYOUT_VILLAGE_BASIC} answer={null} />);
      expect(c.querySelector(".need-head")?.textContent).toMatch(/\S · \S/); // rung, then building · agent
      expect(c.querySelector(".need-head")?.textContent).not.toMatch(/\bA_[a-z0-9]+\b|\bB\d\b/); // names, not ids
      expect(c.textContent).toContain(card.what_happened);
      expect(c.textContent).toContain(card.why_it_matters);
      expect(labels(c)).toEqual(card.options.map((o) => o.label));
      expect(c.textContent).toContain("Suggested"); // exactly one option is marked
      expect(c.querySelectorAll(".btag[data-tone=suggested]")).toHaveLength(1);
      expect(c.querySelector("button.primary")).toBeNull(); // read-only: nothing to send
    });
  }
});

describe("FR-HIL-01 S-07: the gate sheet names the exact action, the recipient and the irreversibility", () => {
  it("shows the card's exact action, its recipient and that a send can't be unsent", async () => {
    const c = await draw(view());
    expect(c.textContent).toContain(GATE_REPLY.gate?.action.exact);
    expect(c.textContent).toContain("orders@example.com");
    expect(c.textContent).toContain("Once sent, it can't be unsent.");
  });
  it("says a reversible save can be undone and has no recipient", async () => {
    const c = await draw(view(GATE_SAVE, [saveRequest(1)]));
    expect(c.textContent).toContain(GATE_SAVE.gate?.action.exact);
    expect(c.textContent).toContain("Yes, you can undo it afterwards.");
    expect(c.textContent).not.toContain("can't be unsent");
  });
  it("FR-HIL-01 S-07: gate options are exactly Approve, Edit first, Hold", async () => {
    expect(labels(await draw(view()))).toEqual(["Approve", "Edit first", "Hold"]);
  });
  it("shows the stricter of the card's and the request's tier and irreversibility", async () => {
    const c = await draw(
      view(GATE_SAVE, [saveRequest(1, { risk_tier: "T3", irreversible: true })]),
    );
    expect(c.textContent).toContain("T3: a person always decides this.");
    expect(c.textContent).toContain("Once done, it can't be undone.");
  });
});

describe("CL-INT-3 HR-1 FR-HIL-01: a gate that does not say what it holds is never answerable", () => {
  it("draws no approve path when neither the card nor the request names the item", async () => {
    const noItem: Card = {
      ...GATE_REPLY,
      gate: GATE_REPLY.gate && {
        ...GATE_REPLY.gate,
        action: { ...GATE_REPLY.gate.action, item: null },
      },
    };
    const c = await draw(view(noItem, [{ ...requested(1), item: null }]));
    expect(c.querySelector('[data-testid="gate-item-missing"]')).not.toBeNull();
    expect(radio(c, "approve")).toBeUndefined();
    expect(primary(c)).toBeNull();
    expect(c.textContent).not.toContain("What it holds");
  });
  it("still answers a gate whose card names the item", async () => {
    const c = await draw(view());
    expect(c.textContent).toContain("What it holds");
    expect(radio(c, "approve")).toBeDefined();
  });
});

describe("FR-HIL-01 S-07: a T3 or irreversible gate preselects nothing", () => {
  it("leaves every option unchosen on an irreversible T3 gate, and the button says to choose", async () => {
    const { c, push } = await sheetPage([GATE_REPLY]);
    await push(requested(1));
    expect(c.querySelector("input:checked")).toBeNull();
    expect(primary(c)?.disabled).toBe(true);
    expect(primary(c)?.textContent).toBe("Choose an option");
  });
  it("preselects the suggested option on a reversible gate", async () => {
    const c = await draw(view(GATE_SAVE, [saveRequest(1)]));
    expect(c.querySelector<HTMLInputElement>("input:checked")?.value).toBe("approve");
  });
  it("stricter request: a reversible card under a T3 request preselects nothing", async () => {
    const c = await draw(view(GATE_SAVE, [saveRequest(1, { risk_tier: "T3" })]));
    expect(c.querySelector("input:checked")).toBeNull();
  });
});

describe("FR-WLD-09 HR-7: a policy-opened gate shows the policy stamp and colour; a person-opened gate does not", () => {
  it("shows the stamp, the rule's name, the undo window and a link to the authorisation", async () => {
    const c = await draw(view(GATE_REPLY, [policyApplied(5)]));
    expect(sheet(c)?.getAttribute("data-opened-by")).toBe("policy");
    expect(c.querySelector('[data-testid="policy-stamp"]')?.textContent).toContain("Policy");
    expect(c.textContent).toContain("Sent under your rule 'Autopilot L2'. Undo within 60 s.");
    expect(c.querySelector("a")?.getAttribute("href")).toMatch(/\/trace$/);
  });
  it("leaves out a part the event did not record, never printing undefined or NaN", async () => {
    const e = policyApplied(5, "G1", RUN_A, {}, { undo_window_s: undefined, policy_id: undefined });
    const text = (await draw(view(GATE_REPLY, [e]))).textContent ?? "";
    expect(text).toContain("Sent under your rule.");
    expect(text).not.toMatch(/undefined|NaN/);
  });
  it("shows no stamp and no rule line for a gate a person approved, and links the authorisation", async () => {
    const c = await draw(view(GATE_REPLY, [requested(1), resolved(2, "approve")]));
    expect(sheet(c)?.getAttribute("data-opened-by")).toBe("person");
    expect(c.querySelector('[data-testid="policy-stamp"]')).toBeNull();
    expect(c.textContent).not.toContain("under your rule");
    expect(c.textContent).toContain("Opened. You approved this at");
    expect(c.querySelector("a")?.getAttribute("href")).toMatch(/\/trace$/);
  });
  it("says team_lead for a Team Lead's approval", async () => {
    const lead = {
      authz: { by: "team_lead" as const, ref: "u_lead", at: "2026-09-29T09:32:09.500Z" },
    };
    const c = await draw(
      view(GATE_REPLY, [requested(1), resolved(2, "approve", GATE_REPLY.id, "G1", RUN_A, lead)]),
    );
    expect(sheet(c)?.getAttribute("data-opened-by")).toBe("team_lead");
    expect(c.textContent).toContain("A Team Lead approved this");
  });
  it("keeps a gate shut for Hold and Edit first", async () => {
    const c = await draw(view(GATE_REPLY, [requested(1), resolved(2, "hold")]));
    expect(sheet(c)?.getAttribute("data-opened-by")).toBe("none");
    expect(c.textContent).toContain("Kept closed. You chose Hold");
  });
  it("shows a gate as waiting when the answer carries the wrong authz", async () => {
    const byPolicy = {
      authz: { by: "policy" as const, ref: "pol_x", at: "2026-09-29T09:32:09.500Z" },
    };
    for (const authz of [{ authz: null }, byPolicy]) {
      const c = await draw(
        view(GATE_REPLY, [requested(1), resolved(2, "approve", GATE_REPLY.id, "G1", RUN_A, authz)]),
      );
      expect(sheet(c)?.getAttribute("data-gate-state")).toBe("waiting");
      expect(sheet(c)?.getAttribute("data-opened-by")).toBe("none");
      act(() => root?.unmount());
      document.body.replaceChildren();
    }
  });
  it("shows no stamp for a policy.applied that is not by a policy", async () => {
    const c = await draw(
      view(GATE_REPLY, [requested(1), policyApplied(2, "G1", RUN_A, { authz: null })]),
    );
    expect(c.querySelector('[data-testid="policy-stamp"]')).toBeNull();
    expect(sheet(c)?.getAttribute("data-gate-state")).toBe("waiting");
  });
});

describe("FR-WLD-09 HR-1: after Approve, the gate is not shown opened until approval.resolved arrives", () => {
  it("sends the answer, waits for confirmation, and opens only on the recorded event", async () => {
    const { sent, push, c } = await sheetPage([GATE_REPLY]);
    await push(requested(1));
    expect(sheet(c)?.getAttribute("data-gate-state")).toBe("waiting");
    await choose(c, "approve");
    expect(primary(c)?.textContent).toBe("Approve");
    await press(c);

    expect(sent).toEqual([[GATE_REPLY.id, { option_id: "approve" }]]);
    expect(c.textContent).toContain("Waiting for confirmation…");
    expect(sheet(c)?.getAttribute("data-gate-state")).toBe("waiting"); // not opened by the click
    expect(sheet(c)?.getAttribute("data-opened-by")).toBe("none");
    expect(c.textContent).not.toContain("Opened.");
    expect(primary(c)?.disabled).toBe(true);

    await push(resolved(2, "approve"));
    expect(sheet(c)?.getAttribute("data-gate-state")).toBe("decided");
    expect(sheet(c)?.getAttribute("data-opened-by")).toBe("person");
    expect(c.textContent).toContain("Opened. You approved this");
    expect(c.textContent).not.toContain("Waiting for confirmation");
  });

  it("frees the button and says what happened when the client rejects the answer", async () => {
    const { client, push, c } = await sheetPage([GATE_REPLY]);
    client.answerCard = async () => {
      throw new Error("the service is down");
    };
    await push(requested(1));
    await choose(c, "edit");
    await press(c);
    expect(c.querySelector('[role="alert"]')?.textContent).toContain("the service is down");
    expect(primary(c)?.disabled).toBe(false);
    expect(c.textContent).not.toContain("Waiting for confirmation…");
  });

  it("FR-HIL-01 HR-1: after Edit first and a redraft, the new request can be answered again", async () => {
    const { sent, push, c } = await sheetPage([GATE_REPLY, { ...GATE_REPLY, id: SECOND }]);
    await push(requested(1));
    await choose(c, "edit");
    await press(c);
    expect(sent).toEqual([[GATE_REPLY.id, { option_id: "edit" }]]);
    expect(c.textContent).toContain("Waiting for confirmation…");

    await push(resolved(2, "edit"));
    expect(c.textContent).toContain("Kept closed. You chose Edit first");

    await push(requested(3, SECOND)); // the redraft: a new proposal with a new card
    expect(sheet(c)?.getAttribute("data-gate-state")).toBe("waiting");
    expect(c.textContent).not.toContain("Waiting for confirmation");
    expect(radio(c, "approve")?.disabled).toBe(false);
    await choose(c, "approve");
    expect(primary(c)?.disabled).toBe(false);
    await press(c);
    expect(sent[1]).toEqual([SECOND, { option_id: "approve" }]);
  });

  it("says no confirmation was recorded after a bounded wait, and lets the person answer again", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { sent, push, c } = await sheetPage([GATE_REPLY]);
    await push(requested(1));
    await choose(c, "hold");
    await press(c);
    expect(c.textContent).toContain("Waiting for confirmation…");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(CONFIRM_MS + 1);
    });
    expect(c.textContent).toContain("No confirmation has been recorded for your answer yet.");
    expect(c.textContent).not.toContain("Waiting for confirmation…");
    expect(sheet(c)?.getAttribute("data-opened-by")).toBe("none");
    expect(primary(c)?.disabled).toBe(false);
    await press(c);
    expect(sent).toHaveLength(2);
  });

  it("closes a question only when question.answered arrives", async () => {
    const { client, sent, push } = liveClient([QUESTION]);
    const c = await draw(
      <ClientProvider client={client}>
        <S_06 />
      </ClientProvider>,
    );
    await push(routed(1));
    await act(async () => c.querySelector<HTMLButtonElement>("button[aria-pressed]")?.click());
    await press(c);
    expect(sent[0]?.[1]).toEqual({ option_id: "per_kwh" });
    expect(c.textContent).toContain("Waiting for confirmation…");
    expect(c.querySelectorAll('[data-testid="needs-queue"] li')).toHaveLength(1);
    await push(answered(2));
    expect(c.querySelectorAll('[data-testid="needs-queue"] li')).toHaveLength(0);
    expect(c.textContent).not.toContain("Waiting for confirmation");
  });

  it("answers a question card only, never a gate's card from the queue", async () => {
    const { client, push } = liveClient([GATE_REPLY]);
    const c = await draw(
      <ClientProvider client={client}>
        <S_06 />
      </ClientProvider>,
    );
    await push(routed(1, GATE_REPLY.id));
    await act(async () => c.querySelector<HTMLButtonElement>("button[aria-pressed]")?.click());
    expect(c.textContent).toContain("did not record the card for this question");
    expect(primary(c)).toBeNull();
  });
});

describe("FR-HIL-01 S-07: which gate the sheet shows", () => {
  it("names the run too: two runs sharing G1 show their own gate", async () => {
    const events = [
      requested(1),
      requested(2, SECOND, "G1", RUN_B),
      resolved(3, "approve", SECOND, "G1", RUN_B),
    ];
    const a = await sheetPage([], `/needs-you/gate?run=${RUN_A}&gate=G1`);
    for (const e of events) await a.push(e);
    expect(sheet(a.c)?.getAttribute("data-gate-state")).toBe("waiting");
    act(() => root?.unmount());
    document.body.replaceChildren();
    const b = await sheetPage([], `/needs-you/gate?run=${RUN_B}&gate=G1`);
    for (const e of events) await b.push(e);
    expect(sheet(b.c)?.getAttribute("data-gate-state")).toBe("decided");
    expect(sheet(b.c)?.getAttribute("data-opened-by")).toBe("person");
  });
  it("says a gate is not recorded, and shows no other gate, for an unknown or ambiguous address", async () => {
    const both = [requested(1), requested(2, SECOND, "G1", RUN_B)];
    const unknown = await sheetPage([], "/needs-you/gate?gate=G999");
    for (const e of both) await unknown.push(e);
    expect(unknown.c.querySelector('[data-testid="gate-not-found"]')).not.toBeNull();
    expect(sheet(unknown.c)).toBeNull();
    act(() => root?.unmount());
    document.body.replaceChildren();
    const ambiguous = await sheetPage([], "/needs-you/gate?gate=G1"); // no run: two runs have a G1
    for (const e of both) await ambiguous.push(e);
    expect(ambiguous.c.querySelector('[data-testid="gate-not-found"]')).not.toBeNull();
  });
  it("draws the gate from its events when the cards cannot load; only answering degrades", async () => {
    const live = liveClient([GATE_REPLY]);
    live.client.listCards = async () => {
      throw new Error("cards are down");
    };
    const c = await draw(
      <ClientProvider client={live.client}>
        <S_07 />
      </ClientProvider>,
    );
    await live.push(requested(1));
    expect(sheet(c)?.getAttribute("data-gate-state")).toBe("waiting");
    expect(c.querySelector('[role="alert"]')?.textContent).toContain("cards are down");
    expect(primary(c)).toBeNull();
  });
});
