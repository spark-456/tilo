import { API_URL, appCheckToken, authToken, sessionView } from "../../../api/ClientProvider";
import { HttpClient, TiloApiError } from "../../../api/http";
import {
  type ScheduleView,
  cadenceWords as cadenceText,
  isScheduleView,
} from "../../../api/schedules";

export { cadenceText };
export type Routine = ScheduleView;
export type RoutinesClient = Pick<
  HttpClient,
  "listSchedules" | "updateSchedule" | "deleteSchedule"
>;
/** No scheduled-run requests from the demo company. Creation uses the existing approved approach flow. */
export function createRoutinesClient(): RoutinesClient | null {
  return API_URL?.trim() && !sessionView.demo()
    ? new HttpClient({ baseUrl: API_URL, appCheckToken, authToken })
    : null;
}
export async function setRoutineEnabled(
  client: RoutinesClient,
  id: string,
  enabled: boolean,
): Promise<Routine> {
  const row = await client.updateSchedule(id, { enabled });
  if (!isScheduleView(row) || row.schedule_id !== id || row.enabled !== enabled)
    throw new TiloApiError("Could not read the routine change.", 200, true, true);
  return row;
}
