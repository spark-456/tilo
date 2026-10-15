// The pictures of the Worlds page, drawn by the page's one kit (engines/kit.ts): icons, the waiting agent, a
// city's mini world, a town's building strip and a village's single building. All of them are frozen frames.
import { type ReactNode, createElement } from "react";
import type { Dec, Plan, World } from "../../api/types";
import { createKit } from "../../engines/kit";
import type { H } from "../../engines/types";
import { cachedCity } from "../../shell/cityCache";
import { parkKit } from "../../shell/kit";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));

export type Kit = ReturnType<typeof createKit>;
export type PlanSource = () => Record<string, Plan>;

export interface Art {
  icon(name: string, size: number): ReactNode;
  agent(): ReactNode;
  city(w: World): ReactNode;
  strip(w: World, size?: number): ReactNode;
  single(w: World, size?: number): ReactNode;
}

/** One kit per mounted page; its plans come from the Api result the page last loaded. */
export const makeKit = (plans: PlanSource): Kit => createKit(h, { plans });

export function makeArt(kit: Kit, plans: PlanSource, dec: Dec, night: boolean): Art {
  return {
    icon: (name, size) => kit.icon(name, size) as ReactNode,
    agent: () => kit.agent({ role: "builder", expr: "needs" }, 44, night) as ReactNode,
    city: (w) => {
      const plan = w.tier === "City" && w.plan ? plans()[w.plan] : undefined;
      if (!w.plan || !plan) return null;
      // A city's picture is the heaviest thing on the page (about 150 ms at 4x CPU); it is drawn once for the
      // plan's content (which holds the decisions) and the time of day, and shared with the World page and the
      // next visit (FR-UX-12).
      return cachedCity(plan, night, (p, n) => parkKit().TP.world(p, { night: n }) as ReactNode);
    },
    strip: (w, size = 64) => (w.row ? (kit.strip(w, size, night) as ReactNode) : null),
    single: (w, size = 36) => (w.single ? (kit.art(w, size, night) as ReactNode) : null),
  };
}
