// @vitest-environment happy-dom
// AGENDA-MODAL: the schedule dialog is a real modal (a <dialog> in the top layer, not a box in the page flow), named,
// closed by Escape, Tab stays inside it, and the empty-week line sits above the grid instead of over an hour row.
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { LiveWeek } from "./LiveWeek";
import { Modal } from "./Modal";

afterEach(cleanup);

it("AGENDA_MODAL_escape_closes_and_tab_wraps_inside_the_dialog", async () => {
  const onClose = vi.fn();
  const m = mount(
    <Modal label="Schedule with others" onClose={onClose}>
      <button type="button">First</button>
      <button type="button">Last</button>
    </Modal>,
  );
  const dialog = m.container.querySelector("dialog.park-agenda-modal") as HTMLDialogElement;
  expect(dialog.getAttribute("aria-label")).toBe("Schedule with others");
  expect(dialog.hasAttribute("open")).toBe(true);
  const [first, last] = Array.from(dialog.querySelectorAll("button"));
  await act(async () => last?.focus());
  await act(async () => {
    last?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }),
    );
  });
  expect(document.activeElement).toBe(first);
  await act(async () => {
    first?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }),
    );
  });
  expect(document.activeElement).toBe(last);
  await act(async () => {
    last?.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
    );
  });
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("AGENDA_MODAL_empty_week_line_is_a_banner_before_the_grid_not_inside_it", () => {
  const m = mount(
    <LiveWeek
      rows={[]}
      parked={[]}
      today="2026-10-21"
      meetings={[]}
      onSchedule={vi.fn()}
      host={null}
      minutes={null}
      getJson={null}
    />,
  );
  const line = m.container.querySelector(".cx-agenda-emptyline");
  const grid = m.container.querySelector(".cx-agenda-scroll");
  expect(line).not.toBeNull();
  expect(grid?.contains(line)).toBe(false);
  expect(line?.compareDocumentPosition(grid as Node)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
});
