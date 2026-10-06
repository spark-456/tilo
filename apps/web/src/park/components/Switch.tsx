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
}

export function Switch({ label, checked, onChange, disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className={cx("park-switch", checked && "park-switch--on")}
      onClick={() => onChange(!checked)}
    >
      <span className={cx("park-switch__knob", checked && "park-switch__knob--on")} />
    </button>
  );
}
