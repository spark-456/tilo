// ADR-0041 (BYOK-5): the live model-key flow, or null. Null in the fixture world (no `VITE_TILO_API_URL`), so dev and
// replay never call the route; a demo session never reaches here (the page says it needs a real sign-in).
import { API_URL, appCheckToken, authToken } from "./ClientProvider";
import { HttpClient } from "./http";
import { type ModelKeyFlow, createModelKeyFlow } from "./modelKey";

export function liveModelKeyFlow(): ModelKeyFlow | null {
  const baseUrl = API_URL?.trim();
  if (!baseUrl) return null;
  return createModelKeyFlow(
    new HttpClient({
      baseUrl,
      ...(appCheckToken ? { appCheckToken } : {}),
      ...(authToken ? { authToken } : {}),
    }),
  );
}
