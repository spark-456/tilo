// @vitest-environment happy-dom
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../../api/ClientProvider";
import type { TiloClient } from "../../api/client";
import { FixtureClient } from "../../api/fixtureClient";
import { SUGGESTED_TASKS } from "../../api/fixtures/suggestedTasks";
import { FlowShell } from "../FlowShell";
import { PRESS_MS } from "../remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
const q = <T extends Element>(sel: string) => container.querySelector<T>(sel);
const settle = (ms = PRESS_MS + 40) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));

async function show(client: TiloClient) {
  window.history.pushState({}, "", "/");
  await act(async () => {
    root.render(
      <ClientProvider client={client}>
        <FlowShell />
      </ClientProvider>,
    );
  });
}
/** Types into a controlled React field the way a user does. */
async function type(el: HTMLTextAreaElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  await act(async () => {
    set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function attach(names: string[]) {
  const input = q<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  const files = names.map((n) => new File(["x"], n));
  Object.defineProperty(input, "files", { value: files, configurable: true });
  await act(async () => void input.dispatchEvent(new Event("change", { bubbles: true })));
  return files;
}
const alertText = () => q('[role="alert"]')?.textContent ?? "";
const primary = () => q<HTMLButtonElement>("button.primary");
const box = () => q<HTMLTextAreaElement>("textarea");

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

describe("S-01 Start", () => {
  it("PRD-18.3 S-01: one primary button; a suggested task fills the box without submitting", async () => {
    const fixture = new FixtureClient();
    const submit = vi.spyOn(fixture, "submitIntake");
    await show(fixture);
    expect(container.querySelectorAll("button.primary")).toHaveLength(1);
    expect(primary()?.textContent).toBe("Start");
    expect(primary()?.disabled).toBe(true); // nothing to start yet
    const chips = container.querySelectorAll<HTMLButtonElement>(
      '[aria-label="Suggested tasks"] button',
    );
    expect(chips).toHaveLength(3);
    expect([...chips].map((c) => c.textContent)).toEqual([...SUGGESTED_TASKS]);
    await act(async () => chips[1]?.click());
    expect(box()?.value).toBe(SUGGESTED_TASKS[1]);
    expect(primary()?.disabled).toBe(false);
    expect(submit).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/");
  });

  it("FR-INT-01 S-01: text plus 3 files submits once and lands on Understanding", async () => {
    const fixture = new FixtureClient({ delayMs: 60 });
    const submit = vi.spyOn(fixture, "submitIntake");
    await show(fixture);
    await type(box() as HTMLTextAreaElement, "Compare the three supplier quotes");
    const files = await attach(["a.pdf", "b.docx", "c.csv"]);
    expect(container.querySelectorAll('[aria-label="Attached files"] li')).toHaveLength(3);
    await act(async () => primary()?.click());
    await act(async () => primary()?.click()); // a double click is one submit
    expect(primary()?.getAttribute("aria-busy")).toBe("true");
    await settle(200);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith("Compare the three supplier quotes", files);
    expect(window.location.pathname).toBe("/task/task_fixture_1/understanding");
  });

  it("FR-INT-01 S-01: the counter shows the length and the box keeps at most 4,000 characters", async () => {
    await show(new FixtureClient());
    expect(container.textContent).toContain("0 / 4,000");
    await type(box() as HTMLTextAreaElement, "x".repeat(4001));
    expect(box()?.value).toHaveLength(4000);
    expect(container.textContent).toContain("4,000 / 4,000");
    expect(alertText()).toBe("The text is 4001 characters; the limit is 4000.");
    await type(box() as HTMLTextAreaElement, "x".repeat(10));
    expect(alertText()).toBe("");
  });

  it("FR-INT-01 S-01: an 11th file and an unsupported type show the server's message and block Start", async () => {
    await show(new FixtureClient());
    await type(box() as HTMLTextAreaElement, "task");
    await attach(Array.from({ length: 11 }, (_, i) => `f${i}.pdf`));
    expect(alertText()).toBe("11 files attached; the limit is 10.");
    expect(primary()?.disabled).toBe(true);
    const remove = container.querySelector<HTMLButtonElement>(
      '[aria-label="Attached files"] button',
    );
    expect(remove?.getAttribute("aria-label")).toBe("Remove f0.pdf");
    await act(async () => remove?.click());
    expect(alertText()).toBe("");
    expect(primary()?.disabled).toBe(false);
    await act(async () =>
      container.querySelector<HTMLButtonElement>('[aria-label="Attached files"] button')?.click(),
    );
    await attach(["notes.txt"]);
    expect(alertText()).toBe(
      "notes.txt is not accepted; attach PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG files.",
    );
    expect(primary()?.disabled).toBe(true);
  });

  it("FR-INT-01 S-01: a rejected submit shows the server's reason and the button works again", async () => {
    const fixture = new FixtureClient();
    vi.spyOn(fixture, "submitIntake").mockRejectedValue(
      new Error("11 files attached; the limit is 10."),
    );
    await show(fixture);
    await type(box() as HTMLTextAreaElement, "task");
    await act(async () => primary()?.click());
    await settle();
    expect(container.textContent).toContain(
      "Could not start the task: 11 files attached; the limit is 10.",
    );
    expect(primary()?.disabled).toBe(false);
    expect(window.location.pathname).toBe("/");
  });
});
