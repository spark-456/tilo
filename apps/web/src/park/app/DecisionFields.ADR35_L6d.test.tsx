// @vitest-environment happy-dom
// ADR35_L6d / FR_CON_02: a `provide` decision on the Park pages is answered by the fields form, not by a tap.
// Rendered through the two real panels (the World page's Waiting card and the Worlds page's Spotlight).
import type { ReactElement } from "react";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import type { FieldsApi } from "../../api/fields";
import { TiloApiError } from "../../api/http";
import type { Decision, DecisionKey } from "../api/types";
import { WaitingCard } from "../pages/World/Side";
import { Spotlight } from "../pages/Worlds/Spotlight";
import { FieldsContext } from "./fieldsContext";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});
async function draw(node: ReactElement): Promise<HTMLElement> {
  document.body.replaceChildren();
  const c = document.createElement("div");
  document.body.append(c);
  root = createRoot(c);
  await act(async () => root?.render(node));
  return c;
}

const KEY = "w_a:c1" as unknown as DecisionKey;
const asks: Decision = {
  k: KEY,
  world: "w_a",
  title: "Send: needs recipient.",
  body: "Nothing is sent.",
  yes: "",
  icon: "",
  done: "",
  toast: "",
  approvedTitle: "",
  provide: { cardId: "c1" },
};
const { provide: _form, ...rest } = asks;
const plain: Decision = { ...rest, k: "w_a:c2" as unknown as DecisionKey, yes: "Approve" };

function fieldsApi(over: Partial<FieldsApi> = {}) {
  const calls: { world: string; card: string; values: unknown }[] = [];
  const asked: string[] = [];
  const forWorld = (world: string): FieldsApi => ({
    getCardFields: async (card) => {
      asked.push(`${world}/${card}`);
      return [{ name: "recipient", label: "Send to", hint: "Plain addresses.", maxLength: 1000 }];
    },
    supplyCardFields: async (card, values) => {
      calls.push({ world, card, values });
    },
    ...over,
  });
  return { forWorld, calls, asked };
}

const panels: [string, (d: Decision, extra?: object) => ReactElement][] = [
  [
    "the World page's Waiting card",
    (d) => <WaitingCard mine={[d]} dec={{}} night={false} onDecide={() => {}} onLater={() => {}} />,
  ],
  [
    "the Worlds page's Spotlight",
    (d) => (
      <Spotlight
        art={{ icon: () => null, agent: () => null } as never}
        decisions={[d]}
        worldName="W"
        dec={{}}
        needsLeft={1}
        onDecide={() => {}}
        onOpen={() => {}}
      />
    ),
  ],
];

async function type(c: HTMLElement, value: string) {
  const input = c.querySelector<HTMLInputElement>('input[name="recipient"]');
  if (!input) throw new Error("no input");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const submit = (c: HTMLElement) =>
  act(async () => {
    c.querySelector("form")?.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
const buttons = (c: HTMLElement) => [...c.querySelectorAll("button")].map((b) => b.textContent);

describe.each(panels)("ADR35_L6d FR_CON_02 %s", (_name, panel) => {
  it("shows the fields form for a provide card and no Add it tap", async () => {
    const api = fieldsApi();
    const c = await draw(
      <FieldsContext.Provider value={api.forWorld}>{panel(asks)}</FieldsContext.Provider>,
    );
    expect(api.asked).toEqual(["w_a/c1"]); // the card's own world and id
    const form = c.querySelector("form[aria-label='What to add']");
    expect(form).not.toBeNull();
    const input = c.querySelector<HTMLInputElement>('input[name="recipient"]');
    expect(c.querySelector(`label[for="${input?.id}"]`)?.textContent).toBe("Send to");
    expect(buttons(c)).not.toContain("Add it");
    expect(buttons(c)).toContain("Add details");
    expect(c.textContent).not.toContain("Needs you screen");
  });

  it("posts the typed values to the fields route of that card and says so", async () => {
    const api = fieldsApi();
    const c = await draw(
      <FieldsContext.Provider value={api.forWorld}>{panel(asks)}</FieldsContext.Provider>,
    );
    await type(c, "  eve@example.org  ");
    await submit(c);
    expect(api.calls).toEqual([
      { world: "w_a", card: "c1", values: { recipient: "eve@example.org" } },
    ]);
    expect(c.textContent).toContain("Added. Waiting for the item");
  });

  it("an empty submit answers nothing, announces why and focuses the field", async () => {
    const api = fieldsApi();
    const c = await draw(
      <FieldsContext.Provider value={api.forWorld}>{panel(asks)}</FieldsContext.Provider>,
    );
    await submit(c);
    expect(api.calls).toEqual([]);
    expect(c.querySelector('[role="alert"]')?.textContent).toBe("Send to is needed.");
    const input = c.querySelector<HTMLInputElement>('input[name="recipient"]');
    expect(input?.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(input);
  });

  it("shows the API's own reason after a refusal (422) and lets the person fix it", async () => {
    let refuse = true;
    const api = fieldsApi({
      supplyCardFields: async () => {
        if (refuse)
          throw new TiloApiError("the recipient must be a plain email address", 422, false, true);
      },
    });
    const c = await draw(
      <FieldsContext.Provider value={api.forWorld}>{panel(asks)}</FieldsContext.Provider>,
    );
    await type(c, "eve@example.org");
    await submit(c);
    const alert = c.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("plain email address");
    refuse = false;
    await submit(c);
    expect(c.querySelector('[role="alert"]')).toBeNull();
    expect(c.textContent).toContain("Added.");
  });

  it("draws no form without the fields calls (offline, demo) and still no tap", async () => {
    const c = await draw(panel(asks));
    expect(c.querySelector("form")).toBeNull();
    expect(buttons(c)).not.toContain("Add it");
  });

  it("keeps the tap of an ordinary decision", async () => {
    const api = fieldsApi();
    const c = await draw(
      <FieldsContext.Provider value={api.forWorld}>{panel(plain)}</FieldsContext.Provider>,
    );
    expect(c.querySelector("form")).toBeNull();
    expect(buttons(c)).toContain("Approve");
  });
});
