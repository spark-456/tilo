import { useEffect, useState } from "react";
import type { Routine, RoutinesClient } from "../../api/live/routines";
import { ApiReadState } from "../../shared/ApiReadState";
import { RoutineList } from "./RoutineList";

/**
 * The Routines section (design/studio-v2 "Tilo S Worlds"). `client` is null in a demo session, which has no schedules to
 * read: the section is still there and says so ("No routines yet"), it never shows invented rows (POLISH-2).
 */
export function RoutinesPanel({ client }: { client: RoutinesClient | null }) {
  const [rows, setRows] = useState<Routine[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    void attempt;
    if (!client) {
      setLoading(false);
      return;
    }
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
      <div className="park-worlds-routines__head">
        <h2 className="park-worlds-h2">Routines</h2>
        <span className="park-worlds-routines__sub">Worlds that run on a schedule</span>
      </div>
      <p className="park-worlds-routines__how">
        To create a routine, start a world and choose Repeat weekly when approving its approach.{" "}
        <a href="/">Create a routine</a>
      </p>
      {client === null ? (
        <p className="park-worlds-routine-empty" data-testid="routines-empty">
          No routines yet. Routines you set up from a world appear here.
        </p>
      ) : null}
      {rows && client ? (
        <RoutineList api={client} first={rows} onError={setError} onPending={setBusy} />
      ) : null}
      {client ? (
        <ApiReadState
          title={rows === null ? "Could not load routines" : "Could not change this routine"}
          error={error}
          pending={loading || busy}
          retryRead={() => setAttempt((n) => n + 1)}
        />
      ) : null}
    </section>
  );
}
