import { useEffect, useRef, useState } from "react";
import {
  type Routine,
  type RoutinesClient,
  cadenceText,
  setRoutineEnabled,
} from "../../api/live/routines";
import { ApiReadState } from "../../components/ApiReadState";

export function RoutinesPanel({ client }: { client: RoutinesClient }) {
  const [rows, setRows] = useState<Routine[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const writing = useRef(false);
  useEffect(() => {
    void attempt;
    let active = true;
    setLoading(true);
    setError(null);
    client
      .listSchedules()
      .then((list) => {
        if (active) setRows(list);
      })
      .catch((error: unknown) => {
        if (active) setError(error);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [client, attempt]);
  const toggle = async (row: Routine) => {
    if (writing.current) return;
    writing.current = true;
    setBusy(true);
    setError(null);
    try {
      const updated = await setRoutineEnabled(client, row.schedule_id, !row.enabled);
      setRows(
        (old) => old?.map((r) => (r.schedule_id === updated.schedule_id ? updated : r)) ?? null,
      );
    } catch (error: unknown) {
      setError(error);
    } finally {
      writing.current = false;
      setBusy(false);
    }
  };
  return (
    <section className="park-worlds-routines" aria-label="Routines">
      <h2>Routines</h2>
      <p>
        To create a routine, start a world and choose Repeat weekly when approving its approach.
      </p>
      <a href="/">Create a routine</a>
      {error ? (
        <>
          <p role="alert">{error}</p>
          {rows === null ? (
            <button type="button" onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </button>
          ) : null}
        </>
      ) : null}
      {!error && rows === null ? <p>Loading routines…</p> : null}
      {rows?.length === 0 ? <p>No routines yet.</p> : null}
      {rows?.map((row) => (
        <article key={row.schedule_id}>
          <h3>{row.title}</h3>
          <p>{cadenceText(row.cadence)}</p>
          <p>{row.enabled ? `Next run: ${row.next_due ?? "Not available yet"}` : "Paused"}</p>
          <button type="button" disabled={busy} onClick={() => void toggle(row)}>
            {row.enabled ? "Pause" : "Resume"}
          </button>
        </article>
      ))}
      <ApiReadState
        title={rows === null ? "Could not load routines" : "Could not change this routine"}
        error={error}
        pending={loading || busy}
        retryRead={() => setAttempt((n) => n + 1)}
      />
    </section>
  );
}
