// Page sheet (README: --sheet, 1px --gBd, r28, --sh, padding 28 32 36, gap 20-30 between sections).
import type { ReactNode } from "react";
import "./park.components.css";

export interface PageSheetProps {
  /** Space between sections in px; the design uses 20, 22 (default) and 30. */
  gap?: number;
  children: ReactNode;
}

export function PageSheet({ gap, children }: PageSheetProps) {
  return (
    <section className="park-sheet" style={gap !== undefined ? { gap } : undefined}>
      {children}
    </section>
  );
}
