// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { LivePinboards } from "./LivePinboards";

afterEach(cleanup);

describe("R-AGENDA pinboards", () => {
  it("R-AGENDA shows colourful notes and opens the inline pin form from a note button", async () => {
    const load = vi.fn(async () => ({
      data: {
        rows: ["Plan launch", "Call Maya", "Review copy", "Book room"].map((title, index) => ({
          id: `pb_${index}`,
          title,
          body: null,
          status: "active",
          created: "2026-10-18T08:00:00Z",
          scope: "Personal" as const,
        })),
        truncated: false,
      },
    }));
    const m = mount(
      <div data-park="">
        <LivePinboards load={load} teamIds={[]} createPin={vi.fn()} onPinCreated={vi.fn()} />
      </div>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const board = m.container.querySelector('[aria-label="My board"]') as HTMLElement;
    expect(board.querySelector("input")).toBeNull();
    const add = board.querySelector<HTMLButtonElement>(".park-agenda-liveboard__addnote");
    expect(add?.textContent).toContain("Add a pin");
    click(add as HTMLButtonElement);
    expect(board.querySelector('input[placeholder="Write a note…"]')).not.toBeNull();
    expect(
      [...board.querySelectorAll("[data-pin-tone]")].map((pin) =>
        pin.getAttribute("data-pin-tone"),
      ),
    ).toEqual(["0", "1", "2", "3"]);
  });
});
