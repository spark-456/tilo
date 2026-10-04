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
const LONE_SURROGATE = /[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;
/** Types into a controlled React field the way a user does. */
async function type(el: HTMLTextAreaElement, value: string) {
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  await act(async () => {
    set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
/** Attaches files by name, or by [name, size in bytes]. */
async function attach(entries: (string | [string, number])[]) {
  const input = q<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  const files = entries.map((e) => {
    const [name, size] = typeof e === "string" ? [e, 1] : e;
    const file = new File(["x"], name);
    Object.defineProperty(file, "size", { value: size });
    return file;
  });
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
    expect(primary()?.textContent).toBe("Start task");
    expect(container.textContent).toContain(
      "You see the plan and the cost before any agent starts.",
    );
    expect(box()?.placeholder).toBe("e.g. Summarise this week's customer feedback");
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

  it("FR-UX-03 S-01 Home: the hero, the plan promise and a preview made only of product rules", async () => {
    await show(new FixtureClient());
    expect(container.querySelector("h1")?.textContent).toBe("What should Tilo do?");
    expect(container.textContent).toContain(
      "asks before anything spends, shares or can't be undone",
    );
    const preview = container.querySelector("aside[aria-label='What Tilo would build']");
    const tiles = [...(preview?.querySelectorAll("dt") ?? [])].map((t) => t.textContent);
    expect(tiles).toEqual(["Size", "You see", "You approve"]);
    // Nothing is planned yet, so the preview states no figure for the task: only the PRD tier range.
    expect(preview?.textContent?.match(/\d+/g)).toEqual(["1", "2", "16"]);
    expect(container.querySelectorAll("button.primary")).toHaveLength(1);
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
    expect(alertText()).toBe(
      "The text is 4001 characters; the limit is 4000. Kept the first 4000 characters.",
    );
    // The kept text is valid, so a truncated paste never leaves Start blocked.
    expect(primary()?.disabled).toBe(false);
    await type(box() as HTMLTextAreaElement, "x".repeat(10));
    expect(alertText()).toBe("");
  });

  it("FR-INT-01 S-01: the limit counts code points like the server, so an emoji is 1 and no pair is split", async () => {
    await show(new FixtureClient());
    await type(box() as HTMLTextAreaElement, "😀".repeat(4000)); // 8,000 UTF-16 units
    expect(container.textContent).toContain("4,000 / 4,000");
    expect(alertText()).toBe("");
    expect(primary()?.disabled).toBe(false);
    await type(box() as HTMLTextAreaElement, `${"😀".repeat(4000)}😀😀`);
    const kept = box()?.value ?? "";
    expect(Array.from(kept)).toHaveLength(4000);
    expect(LONE_SURROGATE.test(kept)).toBe(false);
    expect(alertText()).toContain("The text is 4002 characters; the limit is 4000.");
  });

  it("FR-INT-01 S-01: a file dropped outside the zone cannot navigate away, and the guard goes with the screen", async () => {
    await show(new FixtureClient());
    const drop = () => {
      const e = new Event("drop", { bubbles: true, cancelable: true });
      document.body.dispatchEvent(e);
      return e.defaultPrevented;
    };
    const over = () => {
      const e = new Event("dragover", { bubbles: true, cancelable: true });
      document.body.dispatchEvent(e);
      return e.defaultPrevented;
    };
    expect(drop()).toBe(true);
    expect(over()).toBe(true);
    await act(async () => root.unmount());
    expect(drop()).toBe(false);
    expect(over()).toBe(false);
    root = createRoot(container); // for afterEach
  });

  it("FR-INT-01 S-01: each file's status reflects the file count and the total-size limit", async () => {
    await show(new FixtureClient());
    await type(box() as HTMLTextAreaElement, "task");
    const MB = 1024 * 1024;
    await attach([
      ["a.pdf", 30 * MB],
      ["b.pdf", 30 * MB],
      ["c.pdf", 1 * MB],
    ]);
    const status = () =>
      [...container.querySelectorAll(".file-meta")].map((m) => m.textContent?.split(" · ")[1]);
    expect(status()).toEqual(["Ready to send", "Over the 50 MB total", "Over the 50 MB total"]);
    expect(alertText()).toBe("The files total more than 50 MB.");
    expect(primary()?.disabled).toBe(true);
    await act(async () =>
      container
        .querySelectorAll<HTMLButtonElement>('[aria-label="Attached files"] button')[1]
        ?.click(),
    );
    expect(status()).toEqual(["Ready to send", "Ready to send"]);
    expect(primary()?.disabled).toBe(false);
    await attach(Array.from({ length: 9 }, (_, i) => `f${i}.pdf`));
    expect(status().slice(-2)).toEqual(["Ready to send", "Over the 10 file limit"]);
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
