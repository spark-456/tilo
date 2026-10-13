// FR-CHN-17d: the live push flow, or null. Null in the fixture world (no `VITE_TILO_API_URL`) and in a demo session, so
// dev, replay and the demo never ask for notification permission or register a worker.
import { API_URL, appCheckToken, authToken, sessionView } from "./ClientProvider";
import { HttpClient } from "./http";
import { type PushFlow, createPushFlow } from "./push";

export function livePushFlow(): PushFlow | null {
  const baseUrl = API_URL?.trim();
  if (!baseUrl || sessionView.demo()) return null;
  return createPushFlow(
    new HttpClient({
      baseUrl,
      ...(appCheckToken ? { appCheckToken } : {}),
      ...(authToken ? { authToken } : {}),
    }),
  );
}
