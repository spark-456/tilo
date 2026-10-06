// Connectors page icons: the design's `K.icon(name, size)` from the Park kit (one kit for this module, so
// its art is memoised once). Icons are decorative (aria-hidden by the kit); the label names the control.
import { type ReactNode, createElement } from "react";
import { createKit } from "../../engines/kit";
import type { H } from "../../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));
const kit = createKit(h, { plans: () => ({}) });

export const icon = (name: string, size = 16): ReactNode => kit.icon(name, size) as ReactNode;
