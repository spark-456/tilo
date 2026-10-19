import { displayApiError } from "../../api/http";
import { Button } from "../components/Button";
import "../studio/studio.components.css";

/** Retry is explicitly a READ refresh: uncertain writes must never be resubmitted here.
 * The same reserved box stays mounted during loading/error/retry; long copy scrolls inside.
 * UI-STUDIO-1: loading is still skeleton shapes (no spinner), an error says what happened and what to do. */
export function ApiReadState({
  error,
  pending,
  retryRead,
  title,
}: { error?: unknown; pending: boolean; retryRead: () => void; title: string }) {
  const failed = error != null && !pending;
  return (
    <div
      data-api-read-state=""
      aria-busy={pending}
      className="park-readstate"
      style={{ blockSize: 176, overflow: "auto" }}
    >
      <div role={failed ? "alert" : "status"} className="park-readstate__body">
        {pending ? (
          <>
            <span className="park-sr-only">Loading…</span>
            <span className="park-skeleton__line park-skeleton__line--1" aria-hidden="true" />
            <span className="park-skeleton__line park-skeleton__line--2" aria-hidden="true" />
          </>
        ) : failed ? (
          <>
            <strong className="park-readstate__title">{title}</strong>
            <p className="park-readstate__line">{displayApiError(error)}</p>
          </>
        ) : null}
      </div>
      <Button
        variant="secondary"
        type="button"
        disabled={pending || error == null}
        style={{ visibility: failed ? "visible" : "hidden", minHeight: 44 }}
        onClick={retryRead}
      >
        Retry
      </Button>
    </div>
  );
}
