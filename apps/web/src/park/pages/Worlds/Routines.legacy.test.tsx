// @vitest-environment happy-dom
import { act } from "react";
import { describe, expect, it } from "vitest";
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
  rows,
  view,
} from "../../../../test-support/park/routinesHarness";
describe("FR-AGT-14 Routines list", () => {
  it("FR-AGT-14 delete confirmation focuses Keep, traps Tab and restores focus on Escape", async () => {
    const { calls } = await open({ "GET /schedules": json({ schedules: [A, B] }) });
    const trigger = buttonIn(row("sched_a1"), "Delete");
    trigger?.focus();
    await click(trigger);
    const keep = buttonIn(container, "Keep routine");
    expect(document.activeElement).toBe(keep);
    await act(async () => {
      keep?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }),
      );
    });
    expect(document.activeElement).toBe(buttonIn(container, "Delete routine"));
    await act(async () => {
      document.activeElement?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });
    expect(q('[role="alertdialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
  });

  it("FR-AGT-14 deleting a routine focuses the next row and pausing restores its action", async () => {
    await open({
      "GET /schedules": json({ schedules: [A, B] }),
      "DELETE /schedules/sched_a1": new Response(null, { status: 204 }),
      "PATCH /schedules/sched_b2": json({ ...B, enabled: true }),
    });
    await click(buttonIn(row("sched_a1"), "Delete"));
    await click(buttonIn(container, "Delete routine"));
    expect(document.activeElement).toBe(buttonIn(row("sched_b2"), "Resume"));
    await click(buttonIn(row("sched_b2"), "Resume"));
    expect(document.activeElement).toBe(buttonIn(row("sched_b2"), "Pause"));
  });

  it("FR-AGT-14 renames a routine only after the server accepts the title", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [A] }),
      "PATCH /schedules/sched_a1": json(view({ title: "New weekly summary" })),
    });
    await click(buttonIn(row("sched_a1"), "Rename"));
    const input = q<HTMLInputElement>('input[aria-label="Routine name"]');
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(
        input,
        "New weekly summary",
      );
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(row("sched_a1")?.querySelector("b")?.textContent).toBe(A.title);
    await click(buttonIn(container, "Save name"));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ title: "New weekly summary" });
    expect(row("sched_a1")?.querySelector("b")?.textContent).toBe("New weekly summary");
    expect(document.activeElement).toBe(buttonIn(row("sched_a1"), "Rename"));
  });

  it("FR-AGT-14 Routines: GETs /schedules once on mount and shows title, cadence in words and next run", async () => {
    const { calls } = await open({ "GET /schedules": json({ schedules: [A, B] }) });
    expect(calls.filter((c) => c.method === "GET" && c.path === "/schedules")).toHaveLength(1);
    expect(calls.filter((c) => c.method !== "GET")).toHaveLength(0); // reading writes nothing
    expect(rows()).toHaveLength(2);

    const a = row("sched_a1")?.textContent ?? "";
    expect(a).toContain("Weekly competitor scan");
    expect(a).toContain("Every Monday at 09:00");
    expect(a).toContain("Asia/Kolkata");
    expect(a).toMatch(/Next run/);
    expect(a).toMatch(/\b12\b/); // 12 Oct 2026 in the schedule's own zone
    expect(a).toMatch(/Oct/);
    expect(a).not.toMatch(/Paused/);
    expect(buttonIn(row("sched_a1"), "Pause")).toBeDefined();

    const b = row("sched_b2")?.textContent ?? "";
    expect(b).toContain("Friday digest");
    expect(b).toContain("Every Friday at 17:30");
    expect(b).toContain("Europe/London");
  });

  it("FR-AGT-14 Routines: a paused routine says Paused and offers Resume, not Pause", async () => {
    await open({ "GET /schedules": json({ schedules: [B] }) });
    const b = row("sched_b2");
    expect(b?.textContent).toMatch(/Paused/);
    expect(buttonIn(b ?? null, "Resume")).toBeDefined();
    expect(buttonIn(b ?? null, "Pause")).toBeUndefined();
  });

  it("FR-AGT-14 Routines: an empty list shows a plain empty state and no rows", async () => {
    await open({ "GET /schedules": json({ schedules: [] }) });
    expect(rows()).toHaveLength(0);
    expect(container.textContent).toContain("No routines yet.");
  });

  it("FR-AGT-14 Routines: Pause sends PATCH {enabled:false} and the row then says Paused with Resume", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [A] }),
      "PATCH /schedules/sched_a1": json(view({ enabled: false })),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Pause"));
    const patches = calls.filter((c) => c.method === "PATCH");
    expect(patches).toHaveLength(1);
    expect(patches[0]?.path).toBe("/schedules/sched_a1");
    expect(patches[0]?.body).toEqual({ enabled: false });
    const a = row("sched_a1");
    expect(a?.textContent).toMatch(/Paused/);
    expect(buttonIn(a ?? null, "Resume")).toBeDefined();
  });

  it("FR-AGT-14 Routines: Resume sends PATCH {enabled:true} and the row is live again", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [B] }),
      "PATCH /schedules/sched_b2": json({ ...B, enabled: true }),
    });
    await click(buttonIn(row("sched_b2") ?? null, "Resume"));
    const patches = calls.filter((c) => c.method === "PATCH");
    expect(patches).toHaveLength(1);
    expect(patches[0]?.body).toEqual({ enabled: true });
    expect(row("sched_b2")?.textContent).not.toMatch(/Paused/);
    expect(buttonIn(row("sched_b2") ?? null, "Pause")).toBeDefined();
  });

  it("FR-AGT-14 Routines: Delete asks first and sends nothing until confirmed; Keep leaves the row", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [A] }),
      "DELETE /schedules/sched_a1": new Response(null, { status: 204 }),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Delete"));
    expect(container.textContent).toMatch(/delete/i);
    expect(buttonIn(container, "Delete routine")).toBeDefined();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);

    await click(buttonIn(container, "Keep routine"));
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
    expect(row("sched_a1")).not.toBeNull();
    expect(buttonIn(container, "Delete routine")).toBeUndefined();
  });

  it("FR-AGT-14 Routines: confirming Delete sends DELETE once and removes the row; the last one leaves the empty state", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [A, B] }),
      "DELETE /schedules/sched_a1": new Response(null, { status: 204 }),
      "DELETE /schedules/sched_b2": new Response(null, { status: 204 }),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Delete"));
    await click(buttonIn(container, "Delete routine"));
    const deletes = calls.filter((c) => c.method === "DELETE");
    expect(deletes).toHaveLength(1);
    expect(deletes[0]?.path).toBe("/schedules/sched_a1");
    expect(row("sched_a1")).toBeNull();
    expect(row("sched_b2")).not.toBeNull();

    await click(buttonIn(row("sched_b2") ?? null, "Delete"));
    await click(buttonIn(container, "Delete routine"));
    expect(rows()).toHaveLength(0);
    expect(container.textContent).toContain("No routines yet.");
  });

  it("FR-AGT-14 Routines: a replay-only refusal on Pause shows the replay message, keeps the row, and does not crash", async () => {
    await open({
      "GET /schedules": json({ schedules: [A] }),
      "PATCH /schedules/sched_a1": json(
        { replay_only: true, detail: "This link is replay-only right now." },
        503,
      ),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Pause"));
    expect(q('[role="alert"]')?.textContent).toContain("Finished runs can still be replayed.");
    expect(row("sched_a1")).not.toBeNull();
    expect(row("sched_a1")?.textContent).not.toMatch(/Paused/); // nothing changed
  });

  it("FR-AGT-14 Routines: a replay-only refusal on Delete shows the replay message and keeps the row", async () => {
    await open({
      "GET /schedules": json({ schedules: [A] }),
      "DELETE /schedules/sched_a1": json({ replay_only: true, detail: "replay-only" }, 503),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Delete"));
    await click(buttonIn(container, "Delete routine"));
    expect(q('[role="alert"]')?.textContent).toContain("Finished runs can still be replayed.");
    expect(row("sched_a1")).not.toBeNull();
  });

  it("FR-AGT-14 Routines: a failed list load says so in words with a retry, never an unhandled rejection", async () => {
    const { calls } = await open({ "GET /schedules": json({ detail: "Forbidden" }, 403) });
    expect(q('[role="alert"]')).not.toBeNull();
    expect(rows()).toHaveLength(0);
    const retry = buttonIn(container, "Retry");
    expect(retry).toBeDefined();
    await click(retry);
    expect(calls.filter((c) => c.method === "GET" && c.path === "/schedules")).toHaveLength(2);
  });
});
