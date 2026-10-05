// The page shell every plain screen renders into. It scrolls, so a keyboard user must be able to reach it
// (axe scrollable-region-focusable): it takes a tab stop and a name only while its content overflows, set
// on the element itself so a resize never re-renders the screen and nothing shifts (CLS).
import { type ReactNode, useEffect, useRef } from "react";

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
    watch.observe(page);
    for (const child of Array.from(page.children)) watch.observe(child);
    return () => watch.disconnect();
  }, []);
  return (
    <main ref={ref} className="screen-page" data-testid="screen-page" data-screen={screenId}>
      {children}
    </main>
  );
}
