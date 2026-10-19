// Summary pill (README: h30, r999, 13.5px 800). Same four tone pairs as the status chip; neutral by default.
import type { ReactNode } from "react";
import "./park.components.css";
import type { Tone } from "./StatusChip";

export function SummaryPill({
  tone = "neutral",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return <span className={`park-pill park-pill--${tone}`}>{children}</span>;
}
