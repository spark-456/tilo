import { useEffect, useRef, useState } from "react";
import {
  type Routine,
  type RoutinesClient,
  cadenceText,
  setRoutineEnabled,
} from "../../api/live/routines";

export function RoutinesPanel({ client }: { client: RoutinesClient }) {
  const [rows, setRows] = useState<Routine[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const writing = useRef(false);
  useEffect(() => {
    void attempt;
    let active = true;
    setRows(null);
    setError("");
    client
      .listSchedules()
      .then((list) => {
        if (active) setRows(list);
      })
      .catch(() => {
        if (active) setError("Could not load routines. Try again.");
      });
    return () => {
      active = false;
    };
  }, [client, attempt]);
  const toggle = async (row: Routine) => {
    if (writing.current) return;
    writing.current = true;
    setBusy(true);
    setError("");
    try {
      const updated = await setRoutineEnabled(client, row.schedule_id, !row.enabled);
      setRows(
        (old) => old?.map((r) => (r.schedule_id === updated.schedule_id ? updated : r)) ?? null,
      );
    } catch {
      setError("Could not change this routine. Its status is unchanged on this page.");
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
    </section>
  );
}
