import { type ReactNode, useState } from "react";
import { useClient } from "../../../api/ClientProvider";
import { LifetimeCapDialog } from "../../../components/LifetimeCapDialog";
import type { Remote } from "../../../screens/remote";
function Cap() {
  const client = useClient();
  const [closed, setClosed] = useState(false);
  return closed ? null : (
    <LifetimeCapDialog
      submit={(text) => client.submitFeedback(text)}
      onClose={() => setClosed(true)}
    />
  );
}
export function Loaded<T>({
  what,
  remote,
  retry,
  children,
}: {
  what: string;
  remote: Remote<T>;
  retry?: () => void;
  isEmpty: (value: T) => boolean;
  children: (value: T) => ReactNode;
}) {
  if (remote.status === "loading") return <output>Loading {what}…</output>;
  if (remote.status === "error")
    return remote.lifetimeCap ? (
      <Cap key={remote.message} />
    ) : (
      <div role="alert">
        <p>{remote.message}</p>
        <button type="button" onClick={retry}>
          Try again
        </button>
      </div>
    );
  return <>{children(remote.value)}</>;
}
