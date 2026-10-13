// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { type IntakeClient, IntakeControl, type IntakeResult } from "./IntakeControl";

afterEach(cleanup);
function required(container: HTMLElement, selector: string): HTMLElement {
  const el = container.querySelector<HTMLElement>(selector);
  if (!el) throw new Error(selector);
  return el;
}
const understood: IntakeResult = {
  id: "recorded-1",
  state: "understood",
  preview: "Recorded summary, page 2",
};
function fake() {
  let finish!: (value: IntakeResult) => void;
  const read = vi.fn(
    () =>
      new Promise<IntakeResult>((resolve) => {
        finish = resolve;
      }),
  );
  const remove = vi.fn(async () => undefined);
  return {
    client: { read, remove } satisfies IntakeClient,
    read,
    remove,
    finish: (r = understood) => finish(r),
  };
}
function transfer(el: Element, kind: "drop" | "paste", files: File[]) {
  const event = new Event(kind, { bubbles: true, cancelable: true });
  Object.defineProperty(event, kind === "drop" ? "dataTransfer" : "clipboardData", {
    value: { files },
  });
  act(() => {
    el.dispatchEvent(event);
  });
  return event;
}
async function settle() {
  await act(async () => {
    await Promise.resolve();
  });
}

it("I6_absent_transport_disables_intake_and_preserves_prompt_paste", () => {
  const m = mount(
    <IntakeControl>
      <input aria-label="Prompt" />
    </IntakeControl>,
  );
  expect(m.container.querySelector("button")).toBeNull();
  expect(m.container.querySelector('input[type="file"]')).toBeNull();
  expect(m.container.textContent).not.toContain("Add anything");
  expect(m.container.textContent).not.toContain("Task and sources");
  expect(m.container.textContent).not.toContain("File intake is not available yet");
  expect(transfer(required(m.container, "input"), "paste", []).defaultPrevented).toBe(false);
  expect(
    transfer(required(m.container, ".park-home-intake--unavailable"), "drop", [
      new File(["x"], "x.txt"),
    ]).defaultPrevented,
  ).toBe(true);
  expect(m.container.textContent).not.toContain("Reading");
});

it("I6_drop_displays_reading_then_only_recorded_preview_and_deletes_through_client", async () => {
  const f = fake();
  const m = mount(
    <IntakeControl client={f.client}>
      <input />
    </IntakeControl>,
  );
  const file = new File(["hello"], "note.txt");
  transfer(required(m.container, "fieldset"), "drop", [file]);
  await settle();
  expect(f.read).toHaveBeenCalledWith({ kind: "file", file });
  expect(m.container.textContent).toContain("Reading");
  expect(m.container.textContent).not.toContain("Understood");
  await act(async () => {
    f.finish();
  });
  expect(m.container.textContent).toContain("Understood");
  expect(m.container.textContent).toContain(understood.preview);
  expect(m.container.textContent).toContain("Items are not attached to your task yet");
  click(required(m.container, '[aria-label="Remove note.txt"]'));
  await settle();
  expect(f.remove).toHaveBeenCalledWith("recorded-1");
  expect(m.container.textContent).not.toContain("note.txt");
});

it("I6_file_picker_and_paste_use_the_same_client_and_recorded_refusal", async () => {
  const f = fake();
  const m = mount(
    <IntakeControl client={f.client}>
      <input aria-label="Prompt" />
    </IntakeControl>,
  );
  const picker = required(m.container, 'input[type="file"]');
  Object.defineProperty(picker, "files", { value: [new File(["x"], "unknown.bin")] });
  act(() => {
    picker.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
  await act(async () => {
    f.finish({ id: "refused", state: "unreadable", reason: "Unknown type" });
  });
  expect(m.container.textContent).toContain("Could not read: Unknown type");
  const pasted = new File(["image"], "paste.png");
  expect(
    transfer(required(m.container, '[aria-label="Prompt"]'), "paste", [pasted]).defaultPrevented,
  ).toBe(true);
  await settle();
  expect(f.read).toHaveBeenLastCalledWith({ kind: "file", file: pasted });
});

it("I6_text_paste_is_explicit_and_transport_failure_is_honest", async () => {
  const client: IntakeClient = {
    read: vi.fn(async () => {
      throw new Error("internal detail");
    }),
    remove: vi.fn(),
  };
  const m = mount(
    <IntakeControl client={client}>
      <input />
    </IntakeControl>,
  );
  const notes = required(m.container, "textarea");
  act(() => {
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: [], getData: () => "Pasted notes" },
    });
    notes.dispatchEvent(event);
  });
  expect(client.read).not.toHaveBeenCalled();
  click(required(m.container, '[aria-label="Read pasted text"]'));
  await settle();
  expect(client.read).toHaveBeenCalledWith({ kind: "text", text: "Pasted notes" });
  expect(m.container.textContent).toContain(
    "Could not read: Intake request failed. Try again later.",
  );
  expect(m.container.textContent).not.toContain("internal detail");
});

it("I6_failed_delete_keeps_recorded_item_until_deletion_succeeds", async () => {
  const client: IntakeClient = {
    read: vi.fn(async () => understood),
    remove: vi.fn(async () => {
      throw new Error();
    }),
  };
  const m = mount(
    <IntakeControl client={client}>
      <input />
    </IntakeControl>,
  );
  transfer(required(m.container, "fieldset"), "drop", [new File(["x"], "keep.txt")]);
  await settle();
  click(required(m.container, '[aria-label="Remove keep.txt"]'));
  await settle();
  expect(m.container.textContent).toContain(understood.preview);
  expect(m.container.textContent).toContain("Could not remove this item");
});
