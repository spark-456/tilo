// Status chip (README: h22-24, r7, 11.5-12px 800; pairs okSoft/okInk, heroSoft/heroInk, amberTile/amberInk,
// chip/ink2). Colour never carries the meaning alone: the text says it.
import type { ReactNode } from "react";
import "./park.components.css";

export type Tone = "ok" | "hero" | "amber" | "neutral";

export function StatusChip({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`park-chip park-chip--${tone}`}>{children}</span>;
}
