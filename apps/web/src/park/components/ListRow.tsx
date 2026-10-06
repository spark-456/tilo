// List row (README: grid 44px 1fr auto, gap 12, padding 8-10, r16, hover --rowHover, selected --rowOn).
// Always three cells: lead, body, trail. With an onClick the row is one real button.
import type { ReactNode } from "react";
import { cx } from "./cx";
import "./park.components.css";

export interface ListRowProps {
  lead?: ReactNode;
  trail?: ReactNode;
  selected?: boolean;
  onClick?: () => void;
  children: ReactNode;
}

export function ListRow({ lead, trail, selected, onClick, children }: ListRowProps) {
  const className = cx("park-row", selected && "park-row--on", onClick && "park-row--action");
  const cells = (
    <>
      <span className="park-row__lead">{lead}</span>
      <span className="park-row__body">{children}</span>
      <span className="park-row__trail">{trail}</span>
    </>
  );
  const current = selected ? { "aria-current": "true" as const } : {};
  return onClick ? (
    <button type="button" className={className} onClick={onClick} {...current}>
      {cells}
    </button>
  ) : (
    <div className={className} {...current}>
      {cells}
    </div>
  );
}
