// Modal scrim (README: fixed inset 0, --scrim), centring its child. A click on the scrim itself calls
// onClose; a click on the child does not. Without onClose it ignores clicks (a loader nobody can dismiss).
import type { ReactNode } from "react";
import { cx } from "./cx";
import "./park.components.css";

export interface ModalScrimProps {
  onClose?: () => void;
  /** In the flow, not fixed to the window: for a gallery. */
  inline?: boolean;
  children: ReactNode;
}

export function ModalScrim({ onClose, inline, children }: ModalScrimProps) {
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: a click-away layer; the keyboard way out is Escape, owned by the dialog inside
    <div
      className={cx("park-scrim", inline && "park-scrim--inline")}
      onClick={
        onClose
          ? (e) => {
              if (e.target === e.currentTarget) onClose();
            }
          : undefined
      }
    >
      {children}
    </div>
  );
}
