// Switch (README: 44x26, r99, knob 20 white, on --ok, off --track, knob 18 px to the right when on).
// The knob's end state is a transform offset in the stylesheet; its .25s travel arrives in WEB-3.
import { cx } from "./cx";
import "./park.components.css";

export interface SwitchProps {
  /** The accessible name (the visible label, if any, sits next to the switch). */
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** A hint for assistive technology and the hover title; never a visible string. */
  description?: string;
}

export function Switch({ label, checked, onChange, disabled, description }: SwitchProps) {
  return (
    // biome-ignore lint/a11y/useValidAriaProps: aria-description is ARIA 1.3 (supported by current browsers); biome's list predates it
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      aria-description={description}
      title={description}
      className={cx("park-switch", checked && "park-switch--on")}
      onClick={() => onChange(!checked)}
    >
      <span className={cx("park-switch__knob", checked && "park-switch__knob--on")} />
    </button>
  );
}
