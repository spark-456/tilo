// Segmented control (README: track --seg r12 p3 gap 2, item h32 r9, selected --tabOn). A radio group:
// arrows move and select, wrapping at the ends; only the selected item is in the tab order.
// Sliding variant (the reference's tool-access and board-style toggles): the track is an N-column grid
// that fills its container, the "thumb" is the selected surface, sized (100% - 6px) / N and moved by
// index * 100% of its own width; the selected label takes the option's tone. The design's .4s slide is
// not built here (BQ-WEB-3), so the thumb is at its end state at once.
import type { CSSProperties, KeyboardEvent } from "react";
import { cx } from "./cx";
import "./park.components.css";

/** The colour of the selected label in the sliding variant (the reference's per-level colours). */
export type SegmentTone = "ink" | "ink2" | "sch" | "heroInk" | "amberInk";

export interface SegmentOption {
  readonly value: string;
  readonly label: string;
  /** Sliding only: the selected label's colour; ink when omitted. */
  readonly tone?: SegmentTone;
}

export interface SegmentedControlProps {
  /** The accessible name of the group. */
  label: string;
  options: readonly SegmentOption[];
  value: string;
  onChange: (value: string) => void;
  /** A thumb slides under the selected item and the track fills its container. */
  sliding?: boolean;
  /** lg: items h34 14px (the reference's board-style toggle); md is the default. */
  size?: "md" | "lg";
}

export function SegmentedControl({
  label,
  options,
  value,
  onChange,
  sliding = false,
  size = "md",
}: SegmentedControlProps) {
  const n = options.length;
  const found = options.findIndex((o) => o.value === value);
  const selected = Math.max(found, 0);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, from: number) => {
    let to: number;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") to = (from + 1) % n;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") to = (from - 1 + n) % n;
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = n - 1;
    else return;
    e.preventDefault();
    const next = options[to];
    if (!next) return;
    const items = e.currentTarget.parentElement?.querySelectorAll<HTMLElement>('[role="radio"]');
    items?.[to]?.focus();
    onChange(next.value);
  };

  const trackStyle: CSSProperties | undefined = sliding
    ? { gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }
    : undefined;

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx("park-seg", sliding && "park-seg--sliding", size === "lg" && "park-seg--lg")}
      style={trackStyle}
    >
      {sliding ? (
        <span
          className="park-seg__thumb"
          aria-hidden="true"
          style={{
            width: `calc((100% - 6px) / ${n})`,
            transform: `translateX(${selected * 100}%)`,
          }}
        />
      ) : null}
      {options.map((o, i) => {
        const on = i === selected && found >= 0;
        return (
          <button
            key={o.value}
            type="button"
            // biome-ignore lint/a11y/useSemanticElements: the design's radiogroup of buttons (one thumb slides under them)
            role="radio"
            aria-checked={on}
            tabIndex={i === selected ? 0 : -1}
            className={cx(
              "park-seg__item",
              sliding && "park-seg__item--slide",
              size === "lg" && "park-seg__item--lg",
              // sliding: the thumb is the selected surface, the item only recolours its text
              on && (sliding ? `park-seg__item--${o.tone ?? "ink"}` : "park-seg__item--on"),
            )}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
