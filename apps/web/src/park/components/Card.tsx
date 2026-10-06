// Card (README: --card, 1px --line2, r22, padding 18-22).
import type { ReactNode } from "react";
import "./park.components.css";

export function Card({ children }: { children: ReactNode }) {
  return <div className="park-card">{children}</div>;
}
