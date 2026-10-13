// The one floating panel behind Popover (role dialog) and Menu (role menu): a click-away backdrop, the
// panel, Escape on the document, focus moved in on open and given back to the opener on close. Internal;
// the barrel exports Popover and Menu. `inline` is the in-flow gallery form: no backdrop, no focus work.
import { type KeyboardEventHandler, type ReactNode, useEffect, useRef } from "react";
import { cx } from "./cx";
import "./park.components.css";

export interface PanelProps {
  /** A popover is a dialog; a menu is a menu. */
  kind: "popover" | "menu";
  label: string;
  width?: number | undefined;
  inline: boolean;
  /** An extra class, so the shell can place this panel (the notifications sit at right 60). */
  className?: string | undefined;
  onClose: () => void;
  onKeyDown?: KeyboardEventHandler<HTMLDivElement> | undefined;
  children: ReactNode;
}

export function Panel({
  kind,
  label,
  width,
  inline,
  className,
  onClose,
  onKeyDown,
  children,
}: PanelProps) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    if (inline) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = ref.current?.querySelector<HTMLElement>('[role="menuitem"]') ?? ref.current;
    // preventScroll: opening or closing a menu must not move the window (the phone page menu closes just before a
    // page swap, and the swap scrolls to the top only at its own midpoint).
    first?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, [inline]);

  return (
    <>
      {inline ? null : (
        // biome-ignore lint/a11y/useKeyWithClickEvents: a click-away layer; the keyboard way out is Escape, on the document
        <div className="park-popover__backdrop" onClick={onClose} />
      )}
      <div
        ref={ref}
        role={kind === "menu" ? "menu" : "dialog"}
        aria-label={label}
        tabIndex={kind === "menu" ? undefined : -1}
        className={cx("park-popover", inline && "park-popover--inline", className)}
        style={width !== undefined ? { width } : undefined}
        onKeyDown={onKeyDown}
      >
        {children}
      </div>
    </>
  );
}
