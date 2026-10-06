// @vitest-environment happy-dom
// WEB-3a: the page registry (plan section 10: other lanes add exactly one line each). Pinned surface,
// park/app/pages.ts: `export const PAGES: Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>>`,
// a plain object literal, one `<pageId>: ...` line per page; every page that has no real page yet is a
// lazy Placeholder: `data-testid="park-page-<id>"`, the page name as <h1>, "Not built yet", in a PageSheet.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Suspense, act } from "react";
import type { ComponentType, LazyExoticComponent } from "react";
import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";
import { PAGE_LABEL, stubApp } from "../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../test-support/park/componentsHarness";
import { type AppCtx, PAGE_IDS, type PageId } from "./AppCtx";
import { PAGES } from "./pages";

afterEach(cleanup);

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};

const LAZY = Symbol.for("react.lazy");

describe("WEB_3a_pages: the registry", () => {
  it("WEB_3a_pages_keys_equal_PAGE_IDS", () => {
    expect(Object.keys(PAGES).sort()).toEqual([...PAGE_IDS].sort());
  });

  it("WEB_3a_pages_every_value_is_a_lazy_component", () => {
    for (const id of PAGE_IDS) {
      expect((PAGES[id] as unknown as { $$typeof: symbol }).$$typeof, id).toBe(LAZY);
    }
  });

  it("WEB_3a_pages_the_registry_type", () => {
    expectTypeOf(PAGES).toEqualTypeOf<
      Record<PageId, LazyExoticComponent<ComponentType<{ app: AppCtx }>>>
    >();
  });

  it("WEB_3a_pages_one_line_per_page_in_a_plain_object", () => {
    const src = readFileSync(join(__dirname, "pages.ts"), "utf8");
    expect(src).toMatch(/export const PAGES\s*:[^=]*=\s*\{/);
    for (const id of PAGE_IDS) {
      const lines = src.split(/\r?\n/).filter((l) => new RegExp(`^\\s*${id}\\s*:`).test(l));
      expect(lines, `${id} needs its own line`).toHaveLength(1);
    }
  });
});

describe("WEB_3a_pages: a page with no real page yet renders the Placeholder", () => {
  it("WEB_3a_pages_placeholder_prints_the_params_it_was_given", async () => {
    const Page = PAGES.world;
    const m = mount(
      <Suspense fallback={null}>
        <Page app={stubApp("world", { params: { id: "k1" } })} />
      </Suspense>,
    );
    await settle();
    expect(q(m.container, '[data-testid="park-page-world"]').textContent).toContain("k1");
  });

  it("WEB_3a_pages_placeholder_for_every_page", async () => {
    for (const id of PAGE_IDS) {
      const Page = PAGES[id];
      const m = mount(
        <Suspense fallback={null}>
          <Page app={stubApp(id)} />
        </Suspense>,
      );
      await settle();
      const root = q(m.container, `[data-testid="park-page-${id}"]`);
      expect(qa(m.container, "h1"), id).toHaveLength(1);
      expect(q(m.container, "h1").textContent, id).toBe(PAGE_LABEL[id]);
      expect(root.textContent, id).toContain("Not built yet");
      expect(m.container.querySelector("section.park-sheet"), id).not.toBeNull();
      expect(qa(m.container, "main"), id).toHaveLength(0); // the landmark belongs to the shell
      m.unmount();
    }
  });
});
