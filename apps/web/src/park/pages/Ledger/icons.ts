// The page's icons: the park kit's icon set (20x20 viewBox, 2px round stroke). One kit per document.
import { type ReactNode, createElement } from "react";
import { createKit } from "../../engines/kit";
import type { H } from "../../engines/types";

const h: H = (tag, props, ...children) => createElement(tag, props, ...(children as ReactNode[]));
const kit = createKit(h, { plans: () => ({}) });

export const icon = (name: string, size = 16): ReactNode => kit.icon(name, size) as ReactNode;
