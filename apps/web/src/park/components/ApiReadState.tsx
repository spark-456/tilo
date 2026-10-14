import { displayApiError } from "../../api/http";

/** Retry is explicitly a READ refresh: uncertain writes must never be resubmitted here.
 * The same reserved box stays mounted during loading/error/retry; long copy scrolls inside. */
export function ApiReadState({
  error,
  pending,
  retryRead,
  title,
}: { error?: unknown; pending: boolean; retryRead: () => void; title: string }) {
  const visible = pending || error != null;
  return (
    <div
      data-api-read-state=""
      aria-busy={pending}
      style={{
        blockSize: 176,
        overflow: "auto",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        justifyContent: "center",
        alignItems: "center",
        textAlign: "center",
      }}
    >
      <div role={error != null && !pending ? "alert" : "status"}>
        {visible ? <strong>{pending ? "Loading" : title}</strong> : null}
        {visible ? <p>{pending ? "Loading…" : displayApiError(error)}</p> : null}
      </div>
      <button
        type="button"
        disabled={pending || error == null}
        style={{ visibility: !pending && error != null ? "visible" : "hidden", minHeight: 44 }}
        onClick={retryRead}
      >
        Retry
      </button>
    </div>
  );
}
