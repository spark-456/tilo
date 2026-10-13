// ADR-0035 L4: the live connect flow for this page, or null. Null in the fixture world (no `VITE_TILO_API_URL`) and in a
// demo session (an anonymous demo connects no Google account), so dev, replay and the demo make no connect call.
import { API_URL, appCheckToken, authToken, sessionView } from "./ClientProvider";
import { type ConnectFlow, createConnectFlow } from "./connect";
import { HttpClient } from "./http";

export function liveConnectFlow(): ConnectFlow | null {
  const baseUrl = API_URL?.trim();
  if (!baseUrl || sessionView.demo()) return null;
  return createConnectFlow(
    new HttpClient({
      baseUrl,
      ...(appCheckToken ? { appCheckToken } : {}),
      ...(authToken ? { authToken } : {}),
    }),
  );
}
