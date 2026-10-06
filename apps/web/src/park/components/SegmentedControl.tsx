// Segmented control (README: track --seg r12 p3 gap 2, item h32 r9 13.5px 800, selected --tabOn). A radio
// group: arrows move and select, wrapping at the ends; only the selected item is in the tab order.
// Sliding variant: the "thumb" is the selected surface and sits at index * (itemWidth + 2) px; the
// design's .4s slide is not built here (BQ-WEB-3), so it is at its end state at once.
import type { KeyboardEvent } from "react";
import { cx } from "./cx";
import "./park.components.css";

export interface SegmentOption {
  readonly value: string;
  readonly label: string;
}

interface Base {
  /** The accessible name of the group. */
  label: string;
  options: readonly SegmentOption[];
  value: string;
  onChange: (value: string) => void;
}
export type SegmentedControlProps =
  | (Base & { sliding?: false; itemWidth?: undefined })
  | (Base & { sliding: true; itemWidth: number });

const GAP = 2; // README: gap 2

export function SegmentedControl(props: SegmentedControlProps) {
  const { label, options, value, onChange } = props;
  const itemWidth = props.sliding ? props.itemWidth : undefined;
  const found = options.findIndex((o) => o.value === value);
  const selected = Math.max(found, 0);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, from: number) => {
    const n = options.length;
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

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cx("park-seg", props.sliding && "park-seg--sliding")}
    >
      {itemWidth !== undefined ? (
        <span
          className="park-seg__thumb"
          aria-hidden="true"
          style={{
            width: itemWidth,
            transform: `translateX(${selected * (itemWidth + GAP)}px)`,
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
              // sliding: the thumb is the selected surface, the item only darkens its text
              on && (props.sliding ? "park-seg__item--ink" : "park-seg__item--on"),
              props.sliding && "park-seg__item--slide",
            )}
            style={itemWidth !== undefined ? { width: itemWidth } : undefined}
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
