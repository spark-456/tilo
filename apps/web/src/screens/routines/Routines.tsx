// FR-AGT-14 (PRD 8, "Scheduled runs"): the person's routines, the weekly runs they set up on S-03.
// Lists GET /schedules, pauses and resumes (PATCH enabled) and deletes after an in-page
// confirmation. Each change is shown only after the API answered (HR-1). A client without the
// schedule routes (the fixture client) says so in words.
import { useLayoutEffect, useRef, useState } from "react";
import { useClient } from "../../api/ClientProvider";
import {
  type ScheduleView,
  type SchedulesApi,
  cadenceWords,
  canSchedule,
  isScheduleView,
  nextRunWords,
} from "../../api/schedules";
import { Loaded } from "../FlowShell";
import { describeError, isReplayOnly, useRemote } from "../remote";

interface Problem {
  readonly message: string;
  readonly replayOnly: boolean;
}

function RoutineList({ api, first }: { api: SchedulesApi; first: readonly ScheduleView[] }) {
  const [rows, setRows] = useState<readonly ScheduleView[]>(first);
  const [busy, setBusy] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
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
        : (scope.current?.querySelector<HTMLElement>(".bitem button:not(:disabled)") ??
          scope.current)
      )?.focus();
    }
  }, [asking, busy, editingId]);

  const run = async (id: string, doing: string, change: () => Promise<void>) => {
    setBusy(id);
    setProblem(null);
    try {
      await change();
    } catch (e) {
      const replayOnly = isReplayOnly(e);
      const said = e instanceof Error ? e.message : "";
      setProblem({ message: replayOnly ? said : describeError(doing, e), replayOnly });
    } finally {
      setBusy(null);
      setAsking(null);
      setEditing(null);
    }
  };
  const setEnabled = (row: ScheduleView, enabled: boolean) =>
    run(row.schedule_id, enabled ? "resume the routine" : "pause the routine", async () => {
      const updated = await api.updateSchedule(row.schedule_id, { enabled });
      const next = isScheduleView(updated) ? updated : { ...row, enabled };
      setRows((all) => all.map((r) => (r.schedule_id === row.schedule_id ? next : r)));
    });
  const remove = (row: ScheduleView) =>
    run(row.schedule_id, "delete the routine", async () => {
      await api.deleteSchedule(row.schedule_id);
      setRows((all) => all.filter((r) => r.schedule_id !== row.schedule_id));
    });

  return (
    <section
      className="routines-scope"
      aria-label="Routines"
      tabIndex={-1}
      ref={scope}
      onKeyDown={(e) => {
        if (busy !== null) return;
        if (e.key === "Escape" && (asking || editing)) {
          e.preventDefault();
          setAsking(null);
          setEditing(null);
        } else if (e.key === "Tab" && asking) {
          const buttons = scope.current?.querySelectorAll<HTMLButtonElement>(
            '[role="alertdialog"] button',
          );
          const target = e.shiftKey ? buttons?.[1] : buttons?.[0];
          const edge = e.shiftKey ? buttons?.[0] : buttons?.[1];
          if (document.activeElement === edge) {
            e.preventDefault();
            target?.focus();
          }
        }
      }}
    >
      {problem && (
        <div className="flow-notice" role="alert" data-testid="routines-problem">
          <p>{problem.message}</p>
        </div>
      )}
      {rows.length === 0 ? (
        <p className="section-note" data-testid="routines-empty">
          No routines yet.
        </p>
      ) : (
        <ul className="blist">
          {rows.map((row) => (
            <li
              key={row.schedule_id}
              className="bitem"
              data-testid={`routine-row-${row.schedule_id}`}
            >
              <div className="bitem-main">
                <b>{row.title}</b>
                {editing?.id === row.schedule_id && (
                  <form
                    className="routine-name"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const title = editing.title.trim();
                      if (!title || busy !== null) return;
                      void run(row.schedule_id, "rename the routine", async () => {
                        const updated = await api.updateSchedule(row.schedule_id, { title });
                        const next = isScheduleView(updated) ? updated : { ...row, title };
                        setRows((all) =>
                          all.map((r) => (r.schedule_id === row.schedule_id ? next : r)),
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
                    <button
                      type="submit"
                      className="secondary"
                      disabled={busy !== null || !editing.title.trim()}
                    >
                      Save name
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy !== null}
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                  </form>
                )}
                <span className="bitem-sub">{cadenceWords(row.cadence)}</span>
                <span className="bitem-sub">
                  {`Next run: ${nextRunWords(row.next_due, row.cadence.tz)}`}
                </span>
                {asking === row.schedule_id && (
                  <div role="alertdialog" aria-label="Delete routine" className="flow-notice">
                    <p>{`Delete "${row.title}"? It will not run again.`}</p>
                    <div style={{ display: "flex", gap: "var(--space-12)", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy !== null}
                        onClick={() => remove(row)}
                      >
                        Delete routine
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        disabled={busy !== null}
                        onClick={() => setAsking(null)}
                      >
                        Keep routine
                      </button>
                    </div>
                  </div>
                )}
              </div>
              {!row.enabled && <span className="btag">Paused</span>}
              <button
                type="button"
                className="secondary"
                disabled={busy !== null}
                aria-label={`Rename ${row.title}`}
                onClick={(e) => {
                  returnFocus.current = e.currentTarget;
                  setAsking(null);
                  setEditing({ id: row.schedule_id, title: row.title });
                }}
              >
                Rename
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy !== null}
                aria-label={`${row.enabled ? "Pause" : "Resume"} ${row.title}`}
                onClick={(e) => {
                  returnFocus.current = e.currentTarget;
                  void setEnabled(row, !row.enabled);
                }}
              >
                {row.enabled ? "Pause" : "Resume"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy !== null}
                aria-label={`Delete ${row.title}`}
                onClick={(e) => {
                  returnFocus.current = e.currentTarget;
                  setEditing(null);
                  setAsking(row.schedule_id);
                }}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Routines() {
  const client = useClient();
  const api = canSchedule(client) ? client : null;
  const [remote, retry] = useRemote(
    "load the routines",
    () => (api ? api.listSchedules() : Promise.resolve([])),
    api !== null,
  );
  if (!api) {
    return (
      <p className="section-note">Routines are listed when Tilo is connected to its server.</p>
    );
  }
  return (
    <Loaded what="the routines" remote={remote} retry={retry} isEmpty={() => false}>
      {(rows) => <RoutineList api={api} first={rows} />}
    </Loaded>
  );
}
