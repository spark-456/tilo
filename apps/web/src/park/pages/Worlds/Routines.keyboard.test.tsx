// @vitest-environment happy-dom
import { act } from "react";
import { expect, it } from "vitest";
import {
  A,
  B,
  buttonIn,
  click,
  container,
  json,
  open,
  q,
  row,
  view,
} from "./Routines.legacy.harness";
const editName = async (value: string) =>
  act(async () => {
    const input = q<HTMLInputElement>('input[aria-label="Routine name"]');
    expect(input).not.toBeNull();
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input?.dispatchEvent(new Event("input", { bubbles: true }));
  });

it("FR_AGT_14 rename sends only the trimmed title and waits for the server reply", async () => {
  let reply!: (value: Response) => void;
  const pending = new Promise<Response>((resolve) => {
    reply = resolve;
  });
  const { calls } = await open({
    "GET /schedules": json({ schedules: [A] }),
    "PATCH /schedules/sched_a1": () => pending,
  });
  await click(buttonIn(row("sched_a1") ?? null, "Rename"));
  expect(document.activeElement).toBe(q('input[aria-label="Routine name"]'));
  await editName("  Monday scan  ");
  await click(buttonIn(container, "Save name"));
  expect(calls.filter((call) => call.method === "PATCH").map((call) => call.body)).toEqual([
    { title: "Monday scan" },
  ]);
  expect(row("sched_a1")?.querySelector("b")?.textContent).toBe(A.title);
  await act(async () => reply(json(view({ title: "Monday scan" }))));
  expect(row("sched_a1")?.querySelector("b")?.textContent).toBe("Monday scan");
  expect(document.activeElement).toBe(buttonIn(row("sched_a1") ?? null, "Rename"));
});

it("FR_AGT_14 blank rename and Escape send no write and return focus", async () => {
  const { calls } = await open({ "GET /schedules": json({ schedules: [A] }) });
  const rename = buttonIn(row("sched_a1") ?? null, "Rename");
  await click(rename);
  await editName("   ");
  expect(buttonIn(container, "Save name")?.disabled).toBe(true);
  await act(async () =>
    document.activeElement?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    ),
  );
  expect(q('input[aria-label="Routine name"]')).toBeNull();
  expect(document.activeElement).toBe(rename);
  expect(calls.filter((call) => call.method !== "GET")).toEqual([]);
});

it("FR_AGT_14 failed rename retains the recorded title and returns focus", async () => {
  await open({
    "GET /schedules": json({ schedules: [A] }),
    "PATCH /schedules/sched_a1": json({ detail: "Unavailable" }, 503),
  });
  await click(buttonIn(row("sched_a1") ?? null, "Rename"));
  await editName("New title");
  await click(buttonIn(container, "Save name"));
  expect(q('[role="alert"]')).not.toBeNull();
  expect(row("sched_a1")?.querySelector("b")?.textContent).toBe(A.title);
  expect(document.activeElement).toBe(buttonIn(row("sched_a1") ?? null, "Rename"));
});

it.each([null, {}, { title: "New title" }])(
  "FR_AGT_14 unreadable rename reply %j keeps the recorded title and reports uncertainty",
  async (reply) => {
    await open({
      "GET /schedules": json({ schedules: [A] }),
      "PATCH /schedules/sched_a1": json(reply),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Rename"));
    await editName("New title");
    await click(buttonIn(container, "Save name"));
    expect(row("sched_a1")?.querySelector("b")?.textContent).toBe(A.title);
    expect(q('[role="alert"]')?.textContent).toContain("We could not confirm it.");
    expect(q('[role="alert"]')?.textContent).not.toContain("Nothing was changed");
    expect(document.activeElement).toBe(buttonIn(row("sched_a1") ?? null, "Rename"));
  },
);

it("FR_AGT_14 rename blur keeps the draft without saving or cancelling", async () => {
  const { calls } = await open({ "GET /schedules": json({ schedules: [A] }) });
  await click(buttonIn(row("sched_a1") ?? null, "Rename"));
  await editName("Draft name");
  await act(async () => buttonIn(container, "Save name")?.focus());
  expect(q<HTMLInputElement>('input[aria-label="Routine name"]')?.value).toBe("Draft name");
  expect(row("sched_a1")?.querySelector("b")?.textContent).toBe(A.title);
  expect(calls.filter((call) => call.method !== "GET")).toEqual([]);
});

it("FR_AGT_14 delete confirmation focuses Keep, contains Tab and closes with Escape", async () => {
  const { calls } = await open({ "GET /schedules": json({ schedules: [A] }) });
  const trigger = buttonIn(row("sched_a1") ?? null, "Delete");
  await click(trigger);
  const keep = buttonIn(container, "Keep routine");
  const confirm = buttonIn(container, "Delete routine");
  expect(document.activeElement).toBe(keep);
  await act(async () =>
    keep?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }),
    ),
  );
  expect(document.activeElement).toBe(confirm);
  await act(async () =>
    confirm?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }),
    ),
  );
  expect(document.activeElement).toBe(keep);
  await act(async () =>
    keep?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })),
  );
  expect(q('[role="alertdialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(calls.filter((call) => call.method === "DELETE")).toEqual([]);
  await click(trigger);
  await click(buttonIn(container, "Keep routine"));
  expect(document.activeElement).toBe(trigger);
});

it("FR_AGT_14 Pause restores focus to Resume and Delete moves focus to the remaining row", async () => {
  await open({
    "GET /schedules": json({ schedules: [A, B] }),
    "PATCH /schedules/sched_a1": json(view({ enabled: false })),
    "DELETE /schedules/sched_a1": new Response(null, { status: 204 }),
    "DELETE /schedules/sched_b2": new Response(null, { status: 204 }),
  });
  await click(buttonIn(row("sched_a1") ?? null, "Pause"));
  expect(document.activeElement).toBe(buttonIn(row("sched_a1") ?? null, "Resume"));
  await click(buttonIn(row("sched_a1") ?? null, "Delete"));
  await click(buttonIn(container, "Delete routine"));
  expect(row("sched_b2")?.contains(document.activeElement)).toBe(true);
  await click(buttonIn(row("sched_b2") ?? null, "Delete"));
  await click(buttonIn(container, "Delete routine"));
  expect(q('[data-testid="routines-empty"]')).not.toBeNull();
  expect(document.activeElement).toBe(q('[aria-label="Routines"]'));
});
