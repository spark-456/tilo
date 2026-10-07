// @vitest-environment happy-dom
// FR-UX-12 phone pass (f), BQ-WEB-MOTION-2b: the Agenda draws its boards one after the other (and the pins of a
// board top to bottom), not one pin row across all boards. The grid is reserved from the first part, so a board
// that is not drawn yet holds its cell and nothing already on screen moves.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, renderAgenda } from "../../../../test-support/park/agendaHarness";
import { q, qa } from "../../../../test-support/park/componentsHarness";
import { BOARDS, boardLimits } from "./model";

const g = globalThis as unknown as { CSSAnimation?: unknown };
const had = "CSSAnimation" in g;
afterEach(() => {
  if (!had) Reflect.deleteProperty(g, "CSSAnimation");
  cleanup();
});

describe("FR_UX_12 Agenda boardLimits", () => {
  it("FR_UX_12_agenda_boards_follow_each_other: a board starts only when the one before it is complete", () => {
    expect(boardLimits([3, 2], 0)).toEqual([0, null]);
    expect(boardLimits([3, 2], 2)).toEqual([2, null]);
    expect(boardLimits([3, 2], 3)).toEqual([3, 0]);
    expect(boardLimits([3, 2], 4)).toEqual([3, 1]);
    expect(boardLimits([3, 2], 5)).toEqual([3, 2]);
    expect(boardLimits([3, 2], Number.POSITIVE_INFINITY)).toEqual([3, 2]);
  });

  it("FR_UX_12_agenda_boards_only_grow: more drawn never takes a pin away or hides a board", () => {
    const counts = [4, 0, 3];
    let before = boardLimits(counts, 0);
    for (let drawn = 1; drawn <= 8; drawn++) {
      const now = boardLimits(counts, drawn);
      now.forEach((limit, i) => {
        const was = before[i];
        if (was !== null && was !== undefined) expect(limit).not.toBeNull();
        expect(limit ?? -1).toBeGreaterThanOrEqual(was ?? -1);
      });
      before = now;
    }
    expect(boardLimits(counts, 4)).toEqual([4, 0, 0]); // an empty board is passed in the same step
  });
});

describe("FR_UX_12 Agenda reserves the grid", () => {
  it("FR_UX_12_agenda_grid_reserved_at_first_part: every board has its cell from the first part; the later boards are empty cells", async () => {
    g.CSSAnimation = class {};
    const { container } = await renderAgenda();
    const grid = q(container, ".park-agenda-boards");
    expect(grid.children).toHaveLength(BOARDS.length);
    const first = grid.children[0] as HTMLElement;
    expect(first.getAttribute("data-board")).toBe(BOARDS[0]?.key);
    // the first board is there with its head and no pins yet; the others only hold their cell
    expect(qa(first, "[data-pin]")).toHaveLength(0);
    for (const cell of [...grid.children].slice(1)) {
      expect(cell.getAttribute("data-board-reserved")).not.toBeNull();
      expect(cell.textContent).toBe("");
      expect(cell.getAttribute("aria-hidden")).toBe("true");
    }
    expect(qa(container, "[data-pin]")).toHaveLength(0);
  });

  it("FR_UX_12_agenda_all_drawn_without_css_animations: the DOM stand-in still draws every board and pin at the first render", async () => {
    const { container } = await renderAgenda();
    const grid = q(container, ".park-agenda-boards");
    expect(qa(grid, "[data-board-reserved]")).toHaveLength(0);
    expect(grid.children).toHaveLength(BOARDS.length);
    expect(qa(container, "[data-pin]").length).toBeGreaterThan(0);
  });
});
