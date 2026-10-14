// A1 (14 Oct QA): the greeting column and the Today panel are pinned to the top, the composer to the bottom, and
// the composer's height depends on what it holds (chips, the attach row, a plan card). A fixed offset let the
// chips and the composer lay over the stat tiles and the spend card. This hook publishes what the composer
// really takes, as two custom properties on the Home root, for Home.css to stop the panels above it:
//   --park-home-composer-h  the whole composer column (chips, cards, panel)
//   --park-home-panel-h     the same without the chips row, which is narrower than the page and only reaches
//                           the Today panel on a window under about 1390 px
// Where ResizeObserver is missing (jsdom) nothing is set and the CSS fallbacks hold.
import { type RefObject, useLayoutEffect } from "react";

const CHIPS_GAP = 12;

export function useComposerClearance(root: RefObject<HTMLElement | null>, active: boolean): void {
  useLayoutEffect(() => {
    const el = root.current;
    if (!el || !active || typeof ResizeObserver === "undefined") return;
    const composer = el.querySelector<HTMLElement>(".park-home-composer");
    if (!composer) return;
    const apply = () => {
      const whole = composer.offsetHeight;
      const chips = composer.querySelector<HTMLElement>(".park-home-chips");
      const panel = chips ? Math.max(0, whole - chips.offsetHeight - CHIPS_GAP) : whole;
      el.style.setProperty("--park-home-composer-h", `${whole}px`);
      el.style.setProperty("--park-home-panel-h", `${panel}px`);
    };
    apply();
    const watch = new ResizeObserver(apply);
    watch.observe(composer);
    return () => {
      watch.disconnect();
      el.style.removeProperty("--park-home-composer-h");
      el.style.removeProperty("--park-home-panel-h");
    };
  }, [root, active]);
}
