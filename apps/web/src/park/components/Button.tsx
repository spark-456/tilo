// Button (README "Core components": primary, secondary, needs). Classes: park-btn park-btn--<variant>
// park-btn--<size>, plus park-btn--icon when a leading icon is given. Hover brightness is a state; the
// design's easing is not built here (BQ-WEB-3).
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cx } from "./cx";
import "./park.components.css";

export type ButtonVariant = "primary" | "secondary" | "needs";
export type ButtonSize = "sm" | "md";

export interface ButtonProps
  extends Omit<ComponentPropsWithoutRef<"button">, "className" | "type" | "children"> {
  variant: ButtonVariant;
  size?: ButtonSize;
  /** A leading icon; hidden from assistive technology (the label names the button). */
  icon?: ReactNode;
  type?: "button" | "submit";
  children: ReactNode;
}

export function Button({
  variant,
  size = "md",
  icon,
  type = "button",
  children,
  ...rest
}: ButtonProps) {
  const className = cx(
    "park-btn",
    `park-btn--${variant}`,
    `park-btn--${size}`,
    icon ? "park-btn--icon" : false,
  );
  return (
    <button {...rest} type={type} className={className}>
      {icon ? (
        <span className="park-btn__icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  );
}
