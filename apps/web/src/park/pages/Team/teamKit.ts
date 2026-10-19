// WEB-10 Team page: the render kit for the icons (mail, check, dot, more, chevD) and the builder agent art.
// One kit for the document (its art is memoised per key; park/CLAUDE.md "hold one kit per document").
import { type ReactNode, createElement } from "react";
import { createKit } from "../../engines/kit";
import type { H } from "../../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));
const kit = createKit(h, { plans: () => ({}) });

export const icon = (name: string, size = 16): ReactNode => kit.icon(name, size) as ReactNode;
/** UI-STUDIO-5: a helper's picture for the "Your helpers" cards (a role, or the director's rank). */
export const helperArt = (
  a: { role?: string; rank?: string; expr: string },
  night: boolean,
): ReactNode => kit.agent(a, 58, night) as ReactNode;
export const agentArt = (night: boolean): ReactNode =>
  kit.agent({ role: "builder", expr: "needs" }, 38, night) as ReactNode;
