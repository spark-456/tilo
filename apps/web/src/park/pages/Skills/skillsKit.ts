// The Skills page's pictures: icons, agent faces and the practice run's desk. One kit for the document, so its
// memoised art is shared by every render (engines/kit.ts). The page needs no city plans, only single pictures.
import { type ReactNode, createElement } from "react";
import { createKit } from "../../engines/kit";
import type { AgentSpec, H } from "../../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));

let held: ReturnType<typeof createKit> | null = null;
const kit = (): ReturnType<typeof createKit> => {
  held ??= createKit(h, { plans: () => ({}) });
  return held;
};

export const icon = (name: string, size: number): ReactNode => kit().icon(name, size) as ReactNode;

export const agent = (spec: AgentSpec, size: number, night: boolean): ReactNode =>
  kit().agent(spec, size, night) as ReactNode;

/** STUDIO-4: one teach step's building, still, in the state the step is in (planned, construction, complete). */
export const stepBuilding = (
  kind: string,
  state: string,
  district: string,
  night: boolean,
): ReactNode => kit().building(kind, state, district, 130, night) as ReactNode;
