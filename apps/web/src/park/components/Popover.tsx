// Popover (README: --pop, 1px --line, r20, --shPop, p8). A named dialog; the shell places it (WEB-3).
// Escape and a click on the backdrop call onClose; focus returns to whatever opened it.
import type { ReactNode } from "react";
import { Panel } from "./Panel";

export interface PopoverProps {
  label: string;
  width?: number;
  onClose: () => void;
  /** In the flow, with no backdrop: for a gallery. */
  inline?: boolean;
  /** An extra class for the shell to place it. */
  className?: string;
  children: ReactNode;
}

export function Popover({
  label,
  width,
  onClose,
  inline = false,
  className,
  children,
}: PopoverProps) {
  return (
    <Panel
      kind="popover"
      label={label}
      width={width}
      inline={inline}
      className={className}
      onClose={onClose}
    >
      {children}
    </Panel>
  );
}
