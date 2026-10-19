// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount, q } from "../../../../test-support/park/componentsHarness";
import { MemoryPanel } from "./MemoryPanel";

const item = {
  id: "mem_1",
  org_id: "org_1",
  owner: "user_1",
  text: "I prefer mornings",
  kind: "preference" as const,
  source: "user" as const,
  created_at: "2026-10-16T00:00:00Z",
  updated_at: "2026-10-16T00:00:00Z",
};
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
};
function type(input: HTMLInputElement, value: string) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
afterEach(cleanup);

it("MI-08 lists notes and waits for the create acknowledgement before saying saved", async () => {
  const pending = deferred<typeof item>();
  const api = {
    list: vi.fn(async () => [item]),
    create: vi.fn(() => pending.promise),
    update: vi.fn(async () => item),
    remove: vi.fn(async () => undefined),
  };
  const m = mount(<MemoryPanel api={api} />);
  await act(async () => undefined);
  expect(m.container.textContent).toContain("I prefer mornings");
  const input = q<HTMLInputElement>(m.container, 'input[name="memory_text"]');
  type(input, "I work on Tilo");
  act(() => {
    q<HTMLButtonElement>(m.container, 'button[type="submit"]').click();
  });
  expect(m.container.textContent).not.toContain("Saved");
  await act(async () => pending.resolve({ ...item, id: "mem_2", text: "I work on Tilo" }));
  expect(m.container.textContent).toContain("Saved");
  expect(api.create).toHaveBeenCalledWith({
    text: "I work on Tilo",
    kind: "preference",
    source: "user",
  });
});

it("MI-08 keeps the prior note and draft when an edit fails", async () => {
  const api = {
    list: vi.fn(async () => [item]),
    create: vi.fn(async () => item),
    update: vi.fn(async () => {
      throw new Error("offline");
    }),
    remove: vi.fn(async () => undefined),
  };
  const m = mount(<MemoryPanel api={api} />);
  await act(async () => undefined);
  act(() => {
    q<HTMLButtonElement>(m.container, 'button[aria-label="Edit memory"]').click();
  });
  const input = q<HTMLInputElement>(m.container, 'input[name="memory_text"]');
  type(input, "I prefer evenings");
  await act(async () => {
    q<HTMLButtonElement>(m.container, 'button[type="submit"]').click();
  });
  expect(m.container.textContent).toContain("I prefer mornings");
  expect(input.value).toBe("I prefer evenings");
  expect(m.container.textContent).toContain("could not be saved");
});
