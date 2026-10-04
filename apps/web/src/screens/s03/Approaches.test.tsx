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

// biome-ignore format: compact test helpers
async function openApproaches(overrides: Partial<ApproachesResult> = {}, getApproaches?: () => Promise<ApproachesResult>) {
  const approve = vi.fn(async () => ({ world_id: "w_approved" }));
  const result: ApproachesResult = { task_id: "t1", ...FIXTURE_APPROACHES, ...overrides };
  const load = vi.fn(getApproaches ?? (async () => result));
  const client: TiloClient = Object.assign(new FixtureClient(), { getApproaches: load, approve });
  window.history.pushState({}, "", "/task/t1/approaches");
  await act(async () => {
    root.render(<ClientProvider client={client}><FlowShell /></ClientProvider>);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await settle(0);
  return { approve, load };
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

// biome-ignore format: compact assertions
describe("AGW-04 S-03 Approaches and budget", () => {
  it("FR-INT-06 S-03: shows each approach's time and credit ranges, risks and skips", async () => {
    await openApproaches();
    const quick = q('[data-testid="approach-card-quick"]');
    const thorough = q('[data-testid="approach-card-thorough"]');
    for (const s of ["Quick scan: overview research over 3 sources.", "3–5 min (180–300 s)", "30–45 credits", "A supplier may not have published prices", "Warranty terms", "Depth: overview", "Sources: 3"]) {
      expect(quick?.textContent).toContain(s);
    }
    for (const s of ["Thorough review: deep research over 8 sources.", "10–15 min (600–900 s)", "90–130 credits", "A supplier may not have published prices", "Skips: Nothing", "Depth: deep", "Output format: pptx"]) {
      expect(thorough?.textContent).toContain(s);
    }
    expect(quick?.querySelector('[data-testid="recommended-badge"]')?.textContent).toBe("Recommended");
    expect(thorough?.querySelector('[data-testid="recommended-badge"]')).toBeNull();
    expect(qa("button.approach-select").every((b) => b.getAttribute("aria-pressed") === "false")).toBe(true);
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    await act(async () => q<HTMLButtonElement>('[data-testid="select-approach-quick"]')?.click());
    expect(q('[data-testid="select-approach-quick"]')?.getAttribute("aria-pressed")).toBe("true");
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(false);
  });

  it('FR-INT-08 S-03: the budget line reads exactly "This run can use up to 250 credits (about US$1.25). You can pause it any time." for a cap of 250 at 0.005 US$ per credit', async () => {
    await openApproaches({ credit_usd: 0.005 });
    const capInput = q<HTMLInputElement>('[data-testid="budget-cap-input"]');
    await act(async () => void (capInput && setInputValue(capInput, "250")));
    expect(q('[data-testid="budget-line"]')?.textContent).toBe("This run can use up to 250 credits (about US$1.25). You can pause it any time.");
  });

  it("FR-INT-08 S-03: approve sends the chosen approach id and the edited cap", async () => {
    const { approve } = await openApproaches();
    await act(async () => q<HTMLButtonElement>('[data-testid="select-approach-thorough"]')?.click());
    const capInput = q<HTMLInputElement>('[data-testid="budget-cap-input"]');
    expect(capInput?.value).toBe("130");
    await act(async () => void (capInput && setInputValue(capInput, "150")));
    const primary = q<HTMLButtonElement>("button.primary");
    expect(primary?.textContent).toBe("Start this approach");
    await act(async () => primary?.click());
    await settle();
    expect(approve).toHaveBeenCalledWith("t1", { approach_id: "thorough", budget_cap: 150 });
    expect(window.location.pathname).toBe("/world/w_approved");
  });

  it("FR-INT-08 S-03: disables Start and marks input invalid on empty, 0, 1.5 or above-ceiling cap", async () => {
    await openApproaches();
    await act(async () => q<HTMLButtonElement>('[data-testid="select-approach-quick"]')?.click());
    const capInput = q<HTMLInputElement>('[data-testid="budget-cap-input"]');
    expect(capInput?.getAttribute("aria-describedby")).toBe("budget-cap-hint");
    for (const bad of ["", "0", "1.5", "-5", "301", "1e20"]) {
      await act(async () => void (capInput && setInputValue(capInput, bad)));
      expect(capInput?.getAttribute("aria-invalid"), bad).toBe("true");
      expect(q<HTMLButtonElement>("button.primary")?.disabled, bad).toBe(true);
      // The reason is in words, tied to the input; the cost line states no number for a bad cap.
      expect(q('[data-testid="budget-cap-hint"]')?.textContent, bad).toBe("Enter a whole number from 1 to 300 credits.");
      expect(q('[data-testid="budget-line"]')?.textContent, bad).not.toMatch(/\d/);
    }
    for (const good of ["80", "300"]) {
      await act(async () => void (capInput && setInputValue(capInput, good)));
      expect(capInput?.getAttribute("aria-invalid")).toBe("false");
      expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(false);
      expect(q('[data-testid="budget-cap-hint"]')?.textContent).toBe(""); // the message clears
      expect(q('[data-testid="budget-line"]')?.textContent).toContain(`up to ${good} credits`);
    }
  });

  it("FR-INT-08 S-03: the budget meter shows the estimate and follows the cap, in words", async () => {
    await openApproaches();
    const meter = q("[data-testid=budget-meter]");
    const rec = FIXTURE_APPROACHES.approaches.find((a) => a.id === FIXTURE_APPROACHES.recommended);
    expect(meter?.getAttribute("role")).toBe("img");
    expect(meter?.getAttribute("aria-label")).toBe(
      `Estimated ${rec?.credits.min} to ${rec?.credits.max} credits; your cap is ${rec?.credits.max}`,
    );
    const input = q<HTMLInputElement>("[data-testid=budget-cap-input]");
    await act(async () => input && setInputValue(input, "0"));
    expect(q("[data-testid=budget-meter]")?.getAttribute("aria-label")).not.toContain("your cap");
  });

  it("FR-INT-06 S-03: no approaches says so and offers a way back to Start", async () => {
    await openApproaches({ approaches: [], recommended: "" });
    expect(container.textContent).toContain("Nothing came back for the approaches.");
    expect(qa("button.secondary").map((b) => b.textContent)).toContain("Try again");
    expect(q<HTMLAnchorElement>("a[href='/']")?.textContent).toBe("Describe the task again");
    expect(q("[data-testid=budget-meter]")).toBeNull();
  });

  it("FR-INT-06 S-03: surfaces a load error with retry and keeps Start disabled", async () => {
    const { load } = await openApproaches({}, () => Promise.reject(new Error("offline")));
    expect(q('[role="alert"]')?.textContent).toContain("Could not load the approaches: offline.");
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    await act(async () => q<HTMLButtonElement>("button.secondary")?.click());
    await settle(0);
    expect(load).toHaveBeenCalledTimes(2);
  });
});
