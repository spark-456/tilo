// Menu (README: popover with rows h42 r12). A popover whose rows are menuitem buttons: focus lands on the
// first row, Up and Down move between rows and wrap, a chosen row runs its onSelect and then closes.
import { type KeyboardEvent, type ReactNode, useState } from "react";
import "./park.components.css";
import { Panel } from "./Panel";

export interface MenuItem {
  id: string;
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  /** Quiet text at the row's end ("6 on", "Concept"). */
  hint?: string;
}

export interface MenuProps {
  label: string;
  items: readonly MenuItem[];
  onClose: () => void;
  width?: number;
  inline?: boolean;
  /** Above the rows, inside the panel (the account menu's name, email and plan, then its rule). */
  header?: ReactNode;
}

export function Menu({ label, items, onClose, width, inline = false, header }: MenuProps) {
  const [current, setCurrent] = useState(0);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const rows = [...e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    const n = rows.length;
    if (n === 0) return;
    const at = rows.findIndex((r) => r === document.activeElement);
    let to: number;
    if (e.key === "ArrowDown") to = at < 0 ? 0 : (at + 1) % n;
    else if (e.key === "ArrowUp") to = at < 0 ? n - 1 : (at - 1 + n) % n;
    else if (e.key === "Home") to = 0;
    else if (e.key === "End") to = n - 1;
    else return;
    e.preventDefault();
    rows[to]?.focus();
  };

  return (
    <Panel
      kind="menu"
      label={label}
      width={width}
      inline={inline}
      onClose={onClose}
      onKeyDown={onKeyDown}
    >
      {header}
      {items.map((item, i) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          tabIndex={i === current ? 0 : -1}
          className="park-menu__row"
          onFocus={() => setCurrent(i)}
          onClick={() => {
            item.onSelect();
            onClose();
          }}
        >
          {item.icon ? (
            <span className="park-menu__icon" aria-hidden="true">
              {item.icon}
            </span>
          ) : null}
          <span className="park-menu__label">{item.label}</span>
          {item.hint !== undefined ? <span className="park-menu__hint">{item.hint}</span> : null}
        </button>
      ))}
    </Panel>
  );
}
