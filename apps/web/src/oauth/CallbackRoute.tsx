import type { CallbackParams } from "../api/connect";
import { liveConnectFlow } from "../api/connectEnv";
// ADR-0035 L4: the lazy half of the callback route (loaded only at /oauth/google/callback). The sign-in gate is the
// app's own (SEC-15): the page posts with the person's ID token, so a signed-out visitor signs in first; the params
// were already taken out of the address by Root, before the gate rendered.
import { SignInGate } from "../auth/SignInGate";
import { session } from "../auth/session";
import { navigateFlow } from "../router";
import CallbackPage from "./CallbackPage";

export default function CallbackRoute({ params }: { readonly params: CallbackParams | null }) {
  return (
    <SignInGate auth={session}>
      <CallbackPage
        params={params}
        flow={liveConnectFlow}
        back={() => navigateFlow("/connectors")}
      />
    </SignInGate>
  );
}
