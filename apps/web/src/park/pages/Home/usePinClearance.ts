import { useLayoutEffect, useRef } from "react";
import type { PlacedPin } from "./homeData";
import { type PinRect, clearPin } from "./pinClearance";

export function usePinClearance(pins: readonly PlacedPin[]) {
  const nodes = useRef(new Map<string, HTMLDivElement>());
  useLayoutEffect(() => {
    const root = nodes.current.values().next().value?.parentElement;
    if (!root) return;
    const panels = () =>
      Array.from(
        root.querySelectorAll<HTMLElement>(
          ".park-home-glass, .park-home-composer, .park-home-chips, .park-home-legal",
        ),
      );
    const measure = () => {
      const r = root.getBoundingClientRect();
      const header = document.querySelector("header")?.getBoundingClientRect();
      const bounds = {
        left: Math.max(8, r.left),
        right: Math.min(innerWidth - 8, r.right),
        top: Math.max(header?.bottom ?? 0, r.top),
        bottom: Math.min(innerHeight, r.bottom),
      };
      const occupied: PinRect[] = panels()
        .filter((p) => p.offsetWidth && p.offsetHeight)
        .map((p) => p.getBoundingClientRect());
      for (const pin of pins) {
        const node = nodes.current.get(pin.worldId);
        if (!node) continue;
        // Reset to the recorded city position before measuring; offsets never accumulate.
        node.style.left = `${pin.x}px`;
        node.style.top = `${pin.y}px`;
        node.style.visibility = "hidden";
        const rect = node.getBoundingClientRect();
        const offset = clearPin(rect, bounds, occupied);
        if (!offset) continue;
        node.style.left = `${pin.x + offset.x}px`;
        node.style.top = `${pin.y + offset.y}px`;
        node.style.visibility = "visible";
        occupied.push(node.getBoundingClientRect());
      }
    };
    measure();
    const resize = new ResizeObserver(measure);
    resize.observe(root);
    for (const panel of panels()) resize.observe(panel);
    for (const node of nodes.current.values()) resize.observe(node);
    // Composer phases and asynchronously loaded panel text can change the clear space.
    const changes = new MutationObserver(() => {
      for (const panel of panels()) resize.observe(panel);
      measure();
    });
    changes.observe(root, { childList: true, subtree: true, characterData: true });
    window.addEventListener("resize", measure);
    root.addEventListener("scroll", measure);
    return () => {
      resize.disconnect();
      changes.disconnect();
      window.removeEventListener("resize", measure);
      root.removeEventListener("scroll", measure);
    };
  }, [pins]);
  return (id: string, node: HTMLDivElement | null) => {
    if (node) nodes.current.set(id, node);
    else nodes.current.delete(id);
  };
}
