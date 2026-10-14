import { useEffect, useState } from "react";
import type { Routine, RoutinesClient } from "../../api/live/routines";
import { ApiReadState } from "../../shared/ApiReadState";
import { RoutineList } from "./RoutineList";

export function RoutinesPanel({ client }: { client: RoutinesClient }) {
  const [rows, setRows] = useState<Routine[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
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
  return (
    <section className="park-worlds-routines" aria-label="Routines" tabIndex={-1}>
      <h2>Routines</h2>
      <p>
        To create a routine, start a world and choose Repeat weekly when approving its approach.
      </p>
      <a href="/">Create a routine</a>
      {rows ? (
        <RoutineList api={client} first={rows} onError={setError} onPending={setBusy} />
      ) : null}
      <ApiReadState
        title={rows === null ? "Could not load routines" : "Could not change this routine"}
        error={error}
        pending={loading || busy}
        retryRead={() => setAttempt((n) => n + 1)}
      />
    </section>
  );
}
