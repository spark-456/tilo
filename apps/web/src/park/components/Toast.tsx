// Toast (README: fixed top 92, centred, --toast, r16, 14.5px 700, green check dot, optional action h32 r10).
// Presentational: it starts no timer. The 4.2 s auto-hide belongs to the shell store (WEB-3), which
// calls onDismiss; TOAST_MS is the number it will use. The action runs, then the toast is dismissed.
import { cx } from "./cx";
import "./park.components.css";

export const TOAST_MS = 4200;

export interface ToastProps {
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  onDismiss: () => void;
  /** In the flow, not fixed to the top of the window: for a gallery or a test page. */
  inline?: boolean;
}

export function Toast({ message, actionLabel, onAction, onDismiss, inline }: ToastProps) {
  return (
    <div
      // biome-ignore lint/a11y/useSemanticElements: the design's own div; role and aria-live are pinned by the spec
      role="status"
      aria-live="polite"
      className={cx("park-toast", inline && "park-toast--inline")}
    >
      <span className="park-toast__dot" aria-hidden="true">
        <svg
          width="13"
          height="13"
          viewBox="-10 -10 20 20"
          aria-hidden="true"
          style={{ display: "block" }}
        >
          <path
            d="M-5 0.5 L-1.5 4 L5.5 -3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
      <span className="park-toast__msg">{message}</span>
      {actionLabel !== undefined ? (
        <button
          type="button"
          className="park-toast__action"
          onClick={() => {
            onAction?.();
            onDismiss();
          }}
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}
