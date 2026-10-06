// The page shell every plain screen renders into. It scrolls, so a keyboard user must be able to reach it
// (axe scrollable-region-focusable): it takes a tab stop and a name only while its content overflows, set
// on the element itself so a resize never re-renders the screen and nothing shifts (CLS).
import { type ReactNode, Suspense, useEffect, useRef } from "react";
import { ChunkBoundary } from "./ChunkBoundary";

export function ScreenPage({ screenId, children }: { screenId: string; children: ReactNode }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const page = ref.current;
    if (!page) return;
    const sync = () => {
      if (page.scrollHeight > page.clientHeight) {
        page.tabIndex = 0;
        page.setAttribute("aria-label", "Page content");
      } else {
        page.removeAttribute("tabindex");
        page.removeAttribute("aria-label");
      }
    };
    sync();
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(sync);
    const follow = () => {
      watch.disconnect();
      watch.observe(page);
      for (const child of Array.from(page.children)) watch.observe(child);
    };
    follow();
    // A screen that swaps its root (loading -> loaded, a changed param) is followed too.
    const swaps = new MutationObserver(() => {
      follow();
      sync();
    });
    swaps.observe(page, { childList: true });
    return () => {
      watch.disconnect();
      swaps.disconnect();
    };
  }, []);
  return (
    <main ref={ref} className="screen-page" data-testid="screen-page" data-screen={screenId}>
      {/* The frame is already on screen; the fallback fills the same box, so nothing shifts. */}
      <ChunkBoundary>
        <Suspense
          fallback={
            <output className="screen-loading" data-testid="screen-loading">
              Loading…
            </output>
          }
        >
          {children}
        </Suspense>
      </ChunkBoundary>
    </main>
  );
}
