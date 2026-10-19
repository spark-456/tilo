// Agent / art tile (README: square, r12-18, --sunk or a role tint, art on the bottom edge so agents stand
// on the tile's bottom edge). The art is a child (an svg or img); it is decorative, the row names it.
import type { ReactNode } from "react";
import { cx } from "./cx";
import "./park.components.css";

export type ArtTint = "sunk" | "hero" | "amber" | "ok" | "blue" | "pink" | "orange" | "green";

export interface ArtTileProps {
  size?: number;
  tint?: ArtTint;
  /** Corner radius in px; the stylesheet's 13 (the 44 px tile) when omitted. */
  radius?: number;
  children: ReactNode;
}

export function ArtTile({ size = 44, tint = "sunk", radius, children }: ArtTileProps) {
  return (
    <span
      className={cx("park-art", `park-art--${tint}`)}
      style={{
        width: size,
        height: size,
        ...(radius !== undefined ? { borderRadius: radius } : {}),
      }}
    >
      {children}
    </span>
  );
}
