// ONBOARD-1: the tour's optional last step offers the read-only sample project (STARTER-1). `GET /worlds` marks it
// `sample: true` when the person has no worlds of their own. Feature-detected: no marked item, no reader (the fixture
// world has no API) or any failure means no sample, and the tour is the same without it.
import { API_URL, appCheckToken, authToken } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import { session } from "../auth/session";

export type WorldsReader = () => Promise<unknown>;

const PLAIN_ID = /^[A-Za-z0-9_-]{1,128}$/;

/** The id of the item marked `sample: true` in a worlds page, or null. Never rejects. */
export async function findSampleWorldId(read: WorldsReader | null): Promise<string | null> {
  if (!read) return null;
  try {
    const body = (await read()) as { worlds?: unknown } | null;
    if (typeof body !== "object" || body === null || !Array.isArray(body.worlds)) return null;
    for (const item of body.worlds) {
      const w = item as { sample?: unknown; world_id?: unknown } | null;
      if (w?.sample === true && typeof w.world_id === "string" && PLAIN_ID.test(w.world_id)) {
        return w.world_id;
      }
    }
  } catch {
    // a failed or unreadable list leaves the step out
  }
  return null;
}

/** The real reader: the first page of the person's worlds, or none without an API address. */
export function liveWorldsReader(status: string = session.getState().status): WorldsReader | null {
  if (!API_URL?.trim() || status === "anonymous") return null; // a demo reads the sample company, never the API
  const http = new HttpClient({
    baseUrl: API_URL,
    ...(appCheckToken ? { appCheckToken } : {}),
    ...(authToken ? { authToken } : {}),
  });
  return () => http.getJson("/worlds?limit=100");
}

export const findSampleWorld = (): Promise<string | null> => findSampleWorldId(liveWorldsReader());
