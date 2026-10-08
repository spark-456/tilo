// FR-AGT-14 (PRD 8, "Scheduled runs"): the person's routines, the weekly runs they set up on S-03.
// Lists GET /schedules, pauses and resumes (PATCH enabled) and deletes after an in-page
// confirmation. Each change is shown only after the API answered (HR-1). A client without the
// schedule routes (the fixture client) says so in words.
import { type KeyboardEvent, useLayoutEffect, useRef, useState } from "react";
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
  const [renaming, setRenaming] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const list = useRef<HTMLElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const restore = useRef(false);

  useLayoutEffect(() => {
    if (busy !== null) return;
    if (asking !== null) {
      list.current?.querySelector<HTMLButtonElement>("[data-keep-routine]")?.focus();
    } else if (renaming !== null) {
      list.current?.querySelector<HTMLInputElement>('input[aria-label="Routine title"]')?.focus();
    } else if (restore.current) {
      restore.current = false;
      const target = trigger.current;
      if (target?.isConnected && !target.disabled) target.focus();
      else
        (
          list.current?.querySelector<HTMLButtonElement>("button:not(:disabled)") ?? list.current
        )?.focus();
    }
  });

  const cancel = () => {
    restore.current = true;
    setAsking(null);
    setRenaming(null);
  };
  const dialogKeys = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && busy === null) {
      event.preventDefault();
      cancel();
    } else if (event.key === "Tab") {
      const controls = [
        ...event.currentTarget.querySelectorAll<HTMLElement>("button:not(:disabled), input"),
      ];
      const index = controls.indexOf(document.activeElement as HTMLElement);
      event.preventDefault();
      controls[(index + (event.shiftKey ? -1 : 1) + controls.length) % controls.length]?.focus();
    }
  };

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
      restore.current = true;
      setBusy(null);
      setAsking(null);
      setRenaming(null);
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
  const rename = (row: ScheduleView) =>
    run(row.schedule_id, "rename the routine", async () => {
      const updated = await api.updateSchedule(row.schedule_id, { title: title.trim() });
      const next = isScheduleView(updated) ? updated : { ...row, title: title.trim() };
      setRows((all) => all.map((r) => (r.schedule_id === row.schedule_id ? next : r)));
    });

  return (
    <section ref={list} aria-label="Routines" tabIndex={-1}>
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
                <span className="bitem-sub">{cadenceWords(row.cadence)}</span>
                <span className="bitem-sub">
                  {`Next run: ${nextRunWords(row.next_due, row.cadence.tz)}`}
                </span>
                {asking === row.schedule_id && (
                  <div
                    role="alertdialog"
                    aria-modal="true"
                    aria-label="Delete routine"
                    className="flow-notice"
                    onKeyDown={dialogKeys}
                  >
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
                        data-keep-routine
                        onClick={cancel}
                      >
                        Keep routine
                      </button>
                    </div>
                  </div>
                )}
                {renaming === row.schedule_id && (
                  <div
                    role="alertdialog"
                    aria-modal="true"
                    aria-label="Rename routine"
                    className="flow-notice"
                    onKeyDown={dialogKeys}
                  >
                    <input
                      aria-label="Routine title"
                      value={title}
                      maxLength={140}
                      disabled={busy !== null}
                      onChange={(event) => setTitle(event.target.value)}
                    />
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy !== null || !title.trim()}
                      onClick={() => rename(row)}
                    >
                      Save title
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      disabled={busy !== null}
                      onClick={cancel}
                    >
                      Cancel
                    </button>
                  </div>
                )}
              </div>
              {!row.enabled && <span className="btag">Paused</span>}
              <button
                type="button"
                className="secondary"
                disabled={busy !== null}
                aria-label={`${row.enabled ? "Pause" : "Resume"} ${row.title}`}
                onClick={(event) => {
                  trigger.current = event.currentTarget;
                  setEnabled(row, !row.enabled);
                }}
              >
                {row.enabled ? "Pause" : "Resume"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy !== null}
                aria-label={`Delete ${row.title}`}
                onClick={(event) => {
                  trigger.current = event.currentTarget;
                  setRenaming(null);
                  setAsking(row.schedule_id);
                }}
              >
                Delete
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy !== null}
                aria-label={`Rename ${row.title}`}
                onClick={(event) => {
                  trigger.current = event.currentTarget;
                  setAsking(null);
                  setTitle(row.title);
                  setRenaming(row.schedule_id);
                }}
              >
                Rename
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
