// Tilo T icon (design/tilo-t/tilo-t.js `TiloT.ic`): 24px grid, 1.8 stroke, round caps and joins, currentColor.
// An unknown name draws the dot, as the design does.
import { ICON_PATHS, type IconName } from "./iconPaths";

export function Icon({
  name,
  size = 20,
  stroke = 1.8,
  title,
}: {
  name: IconName;
  size?: number;
  stroke?: number;
  /** Set only when the icon stands alone; otherwise it is decoration and hidden from screen readers. */
  title?: string;
}) {
  const d = ICON_PATHS[name] ?? ICON_PATHS.dot;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      style={{ display: "block", flex: "none" }}
    >
      <path d={d} />
    </svg>
  );
}
