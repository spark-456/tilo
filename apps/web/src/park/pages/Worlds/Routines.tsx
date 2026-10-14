import { useClient } from "../../../api/ClientProvider";
import { canSchedule } from "../../../api/schedules";
import { RoutinesPanel } from "./RoutinesPanel";

/** Compatibility for the retiring Settings screen; the routine UI itself is Park. */
export function Routines() {
  const client = useClient();
  return canSchedule(client) ? (
    <RoutinesPanel client={client} />
  ) : (
    <p>
      No routines are recorded in this sample. Routines are listed when Tilo is connected to its
      server.
    </p>
  );
}
