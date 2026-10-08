import { type RefObject, useLayoutEffect, useRef } from "react";
import { type Body, CityTraffic, type Route, TRAFFIC_TICK } from "./cityTraffic";

interface DrawRoute extends Route {
  originX: number;
  originY: number;
  scale: number;
}
/** Only ambient mover transforms change; artwork, walking frames and the cache stay intact. */
export function useCityTraffic(
  ref: RefObject<HTMLDivElement>,
  scene: unknown,
  paused: boolean,
): void {
  const state = useRef<{ traffic: CityTraffic; routes: DrawRoute[]; elements: HTMLElement[] }>();
  useLayoutEffect(() => {
    const root = ref.current;
    if (!scene || !root) return;
    const elements = Array.from(root?.querySelectorAll<HTMLElement>("[data-city-route]") ?? []);
    if (!elements.length) {
      state.current = undefined;
      return;
    }
    const routes = elements.map((el) => JSON.parse(el.dataset.cityRoute ?? "") as DrawRoute);
    const standing = JSON.parse(
      root?.querySelector<HTMLElement>("[data-city-standing]")?.dataset.cityStanding ?? "[]",
    ) as Body[];
    state.current = { traffic: new CityTraffic(routes, standing), routes, elements };
    for (const el of elements) el.style.animationName = "none";
    return () => {
      state.current = undefined;
    };
  }, [ref, scene]);
  useLayoutEffect(() => {
    const current = state.current;
    const view = ref.current?.ownerDocument.defaultView;
    if (!scene || !current || !view) return;
    const draw = () =>
      current.elements.forEach((el, i) => {
        const p = current.traffic.positions[i];
        const r = current.routes[i];
        if (!p || !r) return;
        const dx = p.x - r.originX;
        const dy = p.y - r.originY;
        el.style.transform = `translate(${((dx - dy) * 0.866 * r.scale).toFixed(1)}px, ${((dx + dy) * 0.5 * r.scale).toFixed(1)}px)`;
      });
    draw();
    if (paused) return;
    let frame = 0;
    let previous: number | undefined;
    let elapsed = 0;
    const tick = (now: number) => {
      if (previous !== undefined) elapsed += Math.min((now - previous) / 1000, 0.1);
      previous = now;
      while (elapsed >= TRAFFIC_TICK) {
        current.traffic.step();
        elapsed -= TRAFFIC_TICK;
      }
      draw();
      frame = view.requestAnimationFrame(tick);
    };
    frame = view.requestAnimationFrame(tick);
    return () => view.cancelAnimationFrame(frame);
  }, [ref, scene, paused]);
}
