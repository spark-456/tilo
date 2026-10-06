// The Home page's pictures: icons, agent faces, building art. One kit for the document, so its memoised
// art is shared by every render (engines/kit.ts). Home needs no city plans, only single pictures.
import { type ReactNode, createElement } from "react";
import { createKit } from "../../engines/kit";
import type { ArtWorld, H } from "../../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));

let held: ReturnType<typeof createKit> | null = null;
const kit = (): ReturnType<typeof createKit> => {
  held ??= createKit(h, { plans: () => ({}) });
  return held;
};

export const icon = (name: string, size: number): ReactNode => kit().icon(name, size) as ReactNode;

/** The builder agent with the "needs you" face, in the amber pill. */
export const needsAgent = (size: number, night: boolean): ReactNode =>
  kit().agent({ role: "builder", expr: "needs" }, size, night) as ReactNode;

/** A world's picture for the Live now tile: the town hall for a city, else the world's own art. */
export function worldArt(world: ArtWorld & { tier: string }, night: boolean): ReactNode {
  return (
    world.tier === "City"
      ? kit().building("townhall", "active", "hall", 34, night)
      : kit().art(world, 30, night)
  ) as ReactNode;
}
