// The pictures of the Worlds page, drawn by the page's one kit (engines/kit.ts): icons, the waiting agent, a
// city's mini world, a town's building strip and a village's single building. All of them are frozen frames.
import { type ReactNode, createElement } from "react";
import type { Dec, Plan, World } from "../../api/types";
import { createKit } from "../../engines/kit";
import type { H } from "../../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));

export type Kit = ReturnType<typeof createKit>;
export type PlanSource = () => Record<string, Plan>;

export interface Art {
  icon(name: string, size: number): ReactNode;
  agent(): ReactNode;
  city(w: World): ReactNode;
  strip(w: World): ReactNode;
  single(w: World): ReactNode;
}

/** One kit per mounted page; its plans come from the Api result the page last loaded. */
export const makeKit = (plans: PlanSource): Kit => createKit(h, { plans });

/** Frames already drawn, by the plan object they were drawn from (a new Api result is a new object). */
const CITY_FRAMES = new WeakMap<Plan, Map<string, ReactNode>>();

export function makeArt(kit: Kit, plans: PlanSource, dec: Dec, night: boolean): Art {
  return {
    icon: (name, size) => kit.icon(name, size) as ReactNode,
    agent: () => kit.agent({ role: "builder", expr: "needs" }, 44, night) as ReactNode,
    city: (w) => {
      const plan = w.tier === "City" && w.plan ? plans()[w.plan] : undefined;
      if (!w.plan || !plan) return null;
      // A city's picture is the heaviest thing on the page (about 150 ms at 4x CPU); the same plan, decisions
      // and time of day give the same frame, so it is drawn once per plan and kept for the next visit.
      const sig = `${w.plan}|${night}|${Object.entries(dec)
        .filter(([, on]) => on)
        .map(([k]) => k)
        .sort()
        .join(",")}`;
      const kept = CITY_FRAMES.get(plan) ?? new Map<string, ReactNode>();
      CITY_FRAMES.set(plan, kept);
      if (!kept.has(sig)) kept.set(sig, kit.world(w.plan, dec, night) as ReactNode);
      return kept.get(sig) ?? null;
    },
    strip: (w) => (w.row ? (kit.strip(w, 64, night) as ReactNode) : null),
    single: (w) => (w.single ? (kit.art(w, 36, night) as ReactNode) : null),
  };
}
