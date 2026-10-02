// @vitest-environment happy-dom
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../../api/ClientProvider";
import type { ApproachesResult, TiloClient } from "../../api/client";
import { FixtureClient } from "../../api/fixtureClient";
import { FIXTURE_APPROACHES } from "../../api/fixtures/derived";
import { FlowShell } from "../FlowShell";
import { PRESS_MS } from "../remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
const q = <T extends Element = HTMLElement>(s: string) => container.querySelector<T>(s);
const qa = (s: string) => [...container.querySelectorAll(s)];
const settle = (ms = PRESS_MS + 25) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));

function setInputValue(input: HTMLInputElement, value: string): void {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

async function openApproaches(overrides: Partial<ApproachesResult> = {}) {
  const approve = vi.fn(async () => ({ world_id: "w_approved" }));
  const result: ApproachesResult = {
    task_id: "t1",
    ...FIXTURE_APPROACHES,
    ...overrides,
  };
  const client: TiloClient = Object.assign(new FixtureClient(), {
    getApproaches: async () => result,
    approve,
  });
  window.history.pushState({}, "", "/task/t1/approaches");
  await act(async () => {
    root.render(
      <ClientProvider client={client}>
        <FlowShell />
      </ClientProvider>,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await settle(0);
  return { approve };
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("AGW-04 S-03 Approaches and budget", () => {
  it("FR-INT-06 S-03: shows each approach's time and credit ranges, risks and skips", async () => {
    await openApproaches();
    const quick = q('[data-testid="approach-card-quick"]');
    const thorough = q('[data-testid="approach-card-thorough"]');
    expect(quick).not.toBeNull();
    expect(thorough).not.toBeNull();

    expect(quick?.textContent).toContain("Quick scan: overview research over 3 sources.");
    expect(quick?.textContent).toContain("3–5 min (180–300 s)");
    expect(quick?.textContent).toContain("30–45 credits");
    expect(quick?.textContent).toContain("A supplier may not have published prices");
    expect(quick?.textContent).toContain("Warranty terms");
    expect(quick?.textContent).toContain("Depth: overview");
    expect(quick?.textContent).toContain("Sources: 3");

    expect(thorough?.textContent).toContain("Thorough review: deep research over 8 sources.");
    expect(thorough?.textContent).toContain("10–15 min (600–900 s)");
    expect(thorough?.textContent).toContain("90–130 credits");
    expect(thorough?.textContent).toContain("A supplier may not have published prices");
    expect(thorough?.textContent).toContain("Skips: Nothing");
    expect(thorough?.textContent).toContain("Depth: deep");
    expect(thorough?.textContent).toContain("Output format: pptx");

    expect(quick?.querySelector('[data-testid="recommended-badge"]')?.textContent).toBe(
      "Recommended",
    );
    expect(thorough?.querySelector('[data-testid="recommended-badge"]')).toBeNull();
    expect(
      qa("button.approach-select").every((b) => b.getAttribute("aria-pressed") === "false"),
    ).toBe(true);
  });

  it('FR-INT-08 S-03: the budget line reads exactly "This run can use up to 520 credits (about US$2.60). You can pause it any time." for a cap of 520 at 0.005 US$ per credit', async () => {
    await openApproaches({ credit_usd: 0.005 });
    const capInput = q<HTMLInputElement>('[data-testid="budget-cap-input"]');
    expect(capInput).not.toBeNull();
    await act(async () => void (capInput && setInputValue(capInput, "520")));
    expect(q('[data-testid="budget-line"]')?.textContent).toBe(
      "This run can use up to 520 credits (about US$2.60). You can pause it any time.",
    );
  });

  it("FR-INT-08 S-03: approve sends the chosen approach id and the edited cap", async () => {
    const { approve } = await openApproaches();
    const selectThorough = q<HTMLButtonElement>('[data-testid="select-approach-thorough"]');
    expect(selectThorough).not.toBeNull();
    await act(async () => selectThorough?.click());

    const capInput = q<HTMLInputElement>('[data-testid="budget-cap-input"]');
    expect(capInput?.value).toBe("130");
    await act(async () => void (capInput && setInputValue(capInput, "150")));

    const primary = q<HTMLButtonElement>("button.primary");
    expect(primary?.textContent).toBe("Start this approach");
    await act(async () => primary?.click());
    await settle();

    expect(approve).toHaveBeenCalledWith("t1", {
      approach_id: "thorough",
      budget_cap: 150,
    });
    expect(window.location.pathname).toBe("/world/w_approved");
  });
});
