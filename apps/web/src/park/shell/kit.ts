// The one render kit of the Park shell (README "Performance": `TiloApp.kit(h)` memoises every agent, building
// and world render by key, so one kit serves the whole document). Built on first use. The shell draws its
// icons, the loader's art and the city backdrop with it.
import { type ReactNode, createElement } from "react";
import { plans } from "../api/fixtures/worlds";
import { createKit } from "../engines/kit";
import type { H } from "../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));

let held: ReturnType<typeof createKit> | null = null;

export function parkKit(): ReturnType<typeof createKit> {
  held ??= createKit(h, { plans });
  return held;
}

/** An icon of the kit (a 20x20 box, 2px round stroke) at `size` px. */
export const icon = (name: string, size: number): ReactNode =>
  parkKit().icon(name, size) as ReactNode;
