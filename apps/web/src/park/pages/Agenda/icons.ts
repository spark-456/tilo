// The page's pictures: the park kit's icon set (20x20 viewBox, 2px round stroke) and the agent faces.
// One kit per document (the kit memoises every picture by key).
import { type ReactNode, createElement } from "react";
import { createKit } from "../../engines/kit";
import type { AgentSpec, H } from "../../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));
const kit = createKit(h, { plans: () => ({}) });

export const icon = (name: string, size = 16): ReactNode => kit.icon(name, size) as ReactNode;
export const face = (spec: AgentSpec, size: number, night: boolean): ReactNode =>
  kit.agent(spec, size, night) as ReactNode;
