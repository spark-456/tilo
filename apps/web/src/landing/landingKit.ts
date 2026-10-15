// STUDIO-6: the landing page's pictures (helpers and the recorded city) from the Park render kit (park/engines, ported
// from Tilo's own prototypes, ADR-0003a). One kit for the document, built on first use. Only the landing's lazy chunk
// imports this, so the engines never reach the sign-in bundle (NFR-01). The engines draw still pictures: no motion.
import { type ReactNode, createElement } from "react";
import type { Plan } from "../park/api/types";
import { createKit } from "../park/engines/kit";
import type { AgentSpec, H } from "../park/engines/types";
import { cachedCity } from "../park/shell/cityCache";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));

let held: ReturnType<typeof createKit> | null = null;
const kit = (): ReturnType<typeof createKit> => {
  held ??= createKit(h, { plans: () => ({}) });
  return held;
};

/** A helper's picture (decorative: the words beside it say who it is). */
export const helperArt = (spec: AgentSpec, size: number, night: boolean): ReactNode =>
  kit().agent(spec, size, night) as ReactNode;

/** The city of a recorded plan, drawn once per plan (by day: the page's CSS filter dims it for dark, as the design does). */
export const cityArt = (plan: Plan): ReactNode =>
  cachedCity(plan, false, (p) => kit().TP.world(p) as ReactNode);

/** A kit icon (search, mail, doc, chart, cap, ...). */
export const iconArt = (name: string, size: number): ReactNode =>
  kit().icon(name, size) as ReactNode;
