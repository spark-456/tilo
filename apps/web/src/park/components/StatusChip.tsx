// Status chip (README: h22-24, r7, 11.5-12px 800; pairs okSoft/okInk, heroSoft/heroInk, amberTile/amberInk,
// chip/ink2). Colour never carries the meaning alone: the text says it.
import type { ReactNode } from "react";
import "./park.components.css";

export type Tone = "ok" | "hero" | "amber" | "neutral";

export function StatusChip({
  tone,
  size = "md",
  children,
}: {
  tone: Tone;
  /** sm: h22 padding 0 8 11.5px, the chip of a list row; md is h24. */
  size?: "md" | "sm";
  children: ReactNode;
}) {
  const sm = size === "sm" ? " park-chip--sm" : "";
  return <span className={`park-chip park-chip--${tone}${sm}`}>{children}</span>;
}
