// A real modal for the Agenda: the native <dialog> opened with showModal() sits in the browser's top layer, so no
// calendar header, hour label or now-line can paint over it, the page behind is inert, and Escape asks to close it.
// Where showModal is missing (older engines, test DOMs) it falls back to a fixed, high z-index box. Tab stays inside
// either way, and focus goes back to what opened it. Styles: `.park-agenda-modal` in Agenda.css.
import { type CSSProperties, type KeyboardEvent, type ReactNode, useEffect, useRef } from "react";

const MODAL_BOX: CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 2147483000,
  boxSizing: "border-box",
  width: "min(560px, calc(100vw - 32px))",
  maxWidth: "none",
  height: "fit-content",
  maxHeight: "calc(100dvh - 32px)",
  margin: "auto",
  padding: 0,
  overflow: "auto",
  borderRadius: 20,
};

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({
  label,
  onClose,
  children,
}: { label: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return undefined;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    try {
      if (!dialog.open) dialog.showModal();
    } catch {
      dialog.setAttribute("open", "");
    }
    return () => {
      if (typeof dialog.close === "function" && dialog.open) dialog.close();
      opener?.focus?.();
    };
  }, []);
  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close.current();
      return;
    }
    if (event.key !== "Tab") return;
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return (
    <dialog
      ref={ref}
      className="park-agenda-modal"
      // Layout inline as well, so the card stays a centred box above the calendar even before Agenda.css loads.
      style={MODAL_BOX}
      aria-label={label}
      onKeyDown={onKeyDown}
      onCancel={(event) => {
        event.preventDefault();
        close.current();
      }}
    >
      {children}
    </dialog>
  );
}
