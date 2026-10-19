import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { TiloApiError } from "../../../api/http";
import {
  type ScheduleView,
  type SchedulesApi,
  cadenceWords,
  isScheduleView,
  nextRunWords,
} from "../../../api/schedules";
import { Button } from "../../components/Button";
import "./RoutineList.css";

export function RoutineList({
  api,
  first,
  onError,
  onPending,
}: {
  api: Pick<SchedulesApi, "updateSchedule" | "deleteSchedule">;
  first: readonly ScheduleView[];
  onError: (error: unknown) => void;
  onPending: (pending: boolean) => void;
}) {
  const [rows, setRows] = useState<readonly ScheduleView[]>(first);
  const [busy, setBusy] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const writing = useRef(false);
  useEffect(() => setRows(first), [first]);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const scope = useRef<HTMLElement>(null);
  const returnFocus = useRef<HTMLButtonElement | null>(null);
  const editingId = editing?.id;
  useLayoutEffect(() => {
    if (busy !== null) return;
    if (asking || editingId) {
      scope.current
        ?.querySelector<HTMLElement>(
          asking ? '[role="alertdialog"] button:last-child' : 'input[aria-label="Routine name"]',
        )
        ?.focus();
    } else if (returnFocus.current) {
      const target = returnFocus.current;
      returnFocus.current = null;
      (target.isConnected
        ? target
        : (scope.current?.querySelector<HTMLElement>(
            'article button[aria-label^="Resume "]:not(:disabled), article button[aria-label^="Pause "]:not(:disabled)',
          ) ??
          scope.current?.querySelector<HTMLElement>("article button:not(:disabled)") ??
          scope.current?.closest<HTMLElement>('[aria-label="Routines"]') ??
          scope.current)
      )?.focus();
    }
  }, [asking, busy, editingId]);

  const run = async (id: string, _doing: string, change: () => Promise<void>) => {
    if (writing.current) return;
    writing.current = true;
    setBusy(id);
    onPending(true);
    onError(null);
    try {
      await change();
    } catch (e) {
      onError(e);
    } finally {
      writing.current = false;
      onPending(false);
      setBusy(null);
      setAsking(null);
      setEditing(null);
    }
  };
  const setEnabled = (row: ScheduleView, enabled: boolean) =>
    run(row.schedule_id, enabled ? "resume the routine" : "pause the routine", async () => {
      const updated = await api.updateSchedule(row.schedule_id, { enabled });
      if (
        !isScheduleView(updated) ||
        updated.schedule_id !== row.schedule_id ||
        updated.enabled !== enabled
      )
        throw new TiloApiError("Unreadable routine reply", 200, true, true, "write_unconfirmed");
      const next = updated;
      setRows((all) => all.map((r) => (r.schedule_id === row.schedule_id ? next : r)));
    });
  const remove = (row: ScheduleView) =>
    run(row.schedule_id, "delete the routine", async () => {
      await api.deleteSchedule(row.schedule_id);
      setRows((all) => all.filter((r) => r.schedule_id !== row.schedule_id));
    });

  return (
    <section
      className="park-worlds-routine-list"
      aria-label="Scheduled routines"
      tabIndex={-1}
      ref={scope}
      onKeyDown={(e) => {
        if (busy !== null) return;
        if (e.key === "Escape" && (asking || editing)) {
          e.preventDefault();
          setAsking(null);
          setEditing(null);
        } else if (e.key === "Tab" && (asking || editing)) {
          const controls = scope.current?.querySelectorAll<HTMLElement>(
            asking
              ? '[role="alertdialog"] button:not(:disabled)'
              : ".park-worlds-routine-name input:not(:disabled), .park-worlds-routine-name button:not(:disabled)",
          );
          const last = (controls?.length ?? 0) - 1;
          const target = e.shiftKey ? controls?.[last] : controls?.[0];
          const edge = e.shiftKey ? controls?.[0] : controls?.[last];
          if (document.activeElement === edge) {
            e.preventDefault();
            target?.focus();
          }
        }
      }}
    >
      {rows.length === 0 ? (
        <p className="park-worlds-routine-empty" data-testid="routines-empty">
          No routines yet. <a href="/">Create a routine</a> by starting a run and choosing Repeat
          weekly.
        </p>
      ) : (
        <div>
          {rows.map((row) => (
            <article
              key={row.schedule_id}
              className="park-worlds-routine"
              data-testid={`routine-row-${row.schedule_id}`}
            >
              <div className="park-worlds-routine-main">
                <h3>
                  <b>{row.title}</b>
                </h3>
                {editing?.id === row.schedule_id && (
                  <form
                    className="park-worlds-routine-name"
                    aria-label="Rename routine"
                    // Blur neither saves nor cancels: the draft stays until an explicit action.
                    onSubmit={(e) => {
                      e.preventDefault();
                      const title = editing.title.trim();
                      if (!title || busy !== null) return;
                      void run(row.schedule_id, "rename the routine", async () => {
                        const updated = await api.updateSchedule(row.schedule_id, { title });
                        if (
                          !isScheduleView(updated) ||
                          updated.schedule_id !== row.schedule_id ||
                          updated.title !== title
                        ) {
                          throw new TiloApiError(
                            "Unreadable routine reply",
                            200,
                            true,
                            true,
                            "write_unconfirmed",
                          );
                        }
                        setRows((all) =>
                          all.map((r) => (r.schedule_id === row.schedule_id ? updated : r)),
                        );
                      });
                    }}
                  >
                    <input
                      aria-label="Routine name"
                      value={editing.title}
                      maxLength={140}
                      required
                      disabled={busy !== null}
                      onChange={(e) => setEditing({ id: row.schedule_id, title: e.target.value })}
                    />
                    <Button
                      variant="secondary"
                      type="submit"
                      disabled={busy !== null || !editing.title.trim()}
                    >
                      Save name
                    </Button>
                    <Button
                      variant="secondary"
                      type="button"
                      disabled={busy !== null}
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </Button>
                  </form>
                )}
                <span className="park-worlds-routine-detail">{cadenceWords(row.cadence)}</span>
                <span className="park-worlds-routine-detail">
                  {`Next run: ${nextRunWords(row.next_due, row.cadence.tz)}`}
                </span>
                {asking === row.schedule_id && (
                  <div
                    role="alertdialog"
                    aria-modal="true"
                    aria-label="Delete routine"
                    className="park-worlds-routine-confirm"
                  >
                    <p>{`Delete "${row.title}"? It will not run again.`}</p>
                    <div style={{ display: "flex", gap: "var(--space-12)", flexWrap: "wrap" }}>
                      <Button
                        variant="secondary"
                        type="button"
                        disabled={busy !== null}
                        onClick={() => remove(row)}
                      >
                        Delete routine
                      </Button>
                      <Button
                        variant="secondary"
                        type="button"
                        disabled={busy !== null}
                        onClick={() => setAsking(null)}
                      >
                        Keep routine
                      </Button>
                    </div>
                  </div>
                )}
              </div>
              {!row.enabled && <span className="park-worlds-routine-state">Paused</span>}
              <Button
                variant="secondary"
                type="button"
                disabled={busy !== null}
                aria-label={`Rename ${row.title}`}
                onClick={(e) => {
                  returnFocus.current = e.currentTarget;
                  setAsking(null);
                  setEditing({ id: row.schedule_id, title: row.title });
                }}
              >
                Rename
              </Button>
              <Button
                variant="secondary"
                type="button"
                disabled={busy !== null}
                aria-label={`${row.enabled ? "Pause" : "Resume"} ${row.title}`}
                onClick={(e) => {
                  returnFocus.current = e.currentTarget;
                  void setEnabled(row, !row.enabled);
                }}
              >
                {row.enabled ? "Pause" : "Resume"}
              </Button>
              <Button
                variant="secondary"
                type="button"
                disabled={busy !== null}
                aria-label={`Delete ${row.title}`}
                onClick={(e) => {
                  returnFocus.current = e.currentTarget;
                  setEditing(null);
                  setAsking(row.schedule_id);
                }}
              >
                Delete
              </Button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
