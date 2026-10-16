// @vitest-environment happy-dom
// OLD-UI-OUT wave 3: the Park Library page. Every state is honest: loading, not connected, a failed read with Try
// again, nothing delivered, and rows that open their world.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import type { Library } from "../../api/live/library";
import { LibraryPage, LibraryView } from "./LibraryPage";

afterEach(cleanup);

const library = (over: Partial<Library> = {}): Library => ({
  items: [
    {
      worldId: "w1",
      worldTitle: "Supplier review",
      artifactId: "a1",
      title: "Price report",
      kind: "pdf",
      version: 2,
    },
    {
      worldId: "w2",
      worldTitle: "Board pack",
      artifactId: "a2",
      title: "Board deck",
      kind: "slide_deck",
      version: 1,
    },
  ],
  unreadable: 0,
  truncated: false,
  credits: 40,
  ...over,
});

const ready = (over: Partial<Library> = {}) => ({
  status: "ready" as const,
  library: library(over),
});

describe("OLD_UI_OUT_3_library_page", () => {
  it("TILO_T_STATES_HR1_library_reuses_shared_loading_error_and_empty_states", () => {
    const app = stubApp("library");
    const loading = mount(<LibraryView app={app} state={{ status: "loading" }} retry={vi.fn()} />);
    expect(loading.container.querySelector('[data-testid="tt-loading"]')?.getAttribute("aria-busy")).toBe("true");

    const failed = mount(<LibraryView app={app} state={{ status: "error" }} retry={vi.fn()} />);
    expect(failed.container.querySelector('[data-testid="tt-error"]')?.getAttribute("role")).toBe("alert");

    const empty = mount(<LibraryView app={app} state={ready({ items: [] })} retry={vi.fn()} />);
    expect(empty.container.querySelector('[data-testid="tt-empty"]')).not.toBeNull();
  });

  it("OLD_UI_OUT_3_library_without_an_api_says_not_connected_yet", async () => {
    const m = mount(<LibraryPage app={stubApp("library")} />);
    await act(async () => undefined);
    expect(q(m.container, '[data-testid="park-page-library"]')).not.toBeNull();
    expect(qa(m.container, "h1")).toHaveLength(1);
    expect(m.container.textContent).toContain("Not connected yet");
  });

  it("OLD_UI_OUT_3_library_lists_deliverables_with_their_world_and_opens_it", () => {
    const app = stubApp("library");
    const m = mount(<LibraryView app={app} state={ready()} retry={vi.fn()} />);
    const rows = qa(m.container, '[data-testid="library-rows"] li');
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("Price report");
    expect(rows[0]?.textContent).toContain("Pdf · version 2 · Supplier review");
    expect(rows[1]?.textContent).toContain("Slide deck");
    (rows[1]?.querySelector("button") as HTMLButtonElement).click();
    expect(app.go).toHaveBeenCalledWith("world", { id: "w2" });
  });

  it("OLD_UI_OUT_3_library_search_filters_by_title_or_world_and_says_when_nothing_matches", async () => {
    const m = mount(<LibraryView app={stubApp("library")} state={ready()} retry={vi.fn()} />);
    const search = q<HTMLInputElement>(m.container, 'input[type="search"]');
    const type = async (value: string) => {
      await act(async () => {
        const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        set?.call(search, value);
        search.dispatchEvent(new Event("input", { bubbles: true }));
      });
    };
    await type("board");
    expect(qa(m.container, '[data-testid="library-rows"] li')).toHaveLength(1);
    await type("zzz");
    expect(m.container.querySelector('[data-testid="library-nomatch"]')).not.toBeNull();
  });

  it("OLD_UI_OUT_3_library_with_nothing_delivered_says_so_and_names_no_row", () => {
    const m = mount(
      <LibraryView app={stubApp("library")} state={ready({ items: [] })} retry={vi.fn()} />,
    );
    expect(q(m.container, '[data-testid="library-empty"]').textContent).toContain(
      "Nothing delivered yet",
    );
    expect(m.container.querySelector('[data-testid="library-rows"]')).toBeNull();
  });

  it("OLD_UI_OUT_3_library_says_how_many_worlds_could_not_be_read", () => {
    const m = mount(
      <LibraryView app={stubApp("library")} state={ready({ unreadable: 2 })} retry={vi.fn()} />,
    );
    expect(m.container.textContent).toContain("2 finished worlds could not be read just now.");
  });

  it("OLD_UI_OUT_3_library_a_failed_read_offers_try_again", () => {
    const retry = vi.fn();
    const m = mount(
      <LibraryView app={stubApp("library")} state={{ status: "error" }} retry={retry} />,
    );
    expect(m.container.textContent).toContain("The Library could not load");
    (m.container.querySelector("button") as HTMLButtonElement).click();
    expect(retry).toHaveBeenCalledOnce();
  });
});
