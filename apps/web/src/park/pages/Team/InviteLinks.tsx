import { useCallback, useEffect, useState } from "react";
import type { InviteLinkRow, MadeLink, TeamsClient } from "../../api/selfServeTeams";
import { Button } from "../../components";

const labels: Record<InviteLinkRow["state"], string> = {
  unused: "Unused",
  expired: "Expired",
  used: "Used",
  withdrawn: "Withdrawn",
};
const errorMessage = (error: unknown) =>
  (error as { status?: number } | null)?.status === 429
    ? "This team already has 10 unused links. Withdraw one first."
    : "Invite links are not available right now.";

/** A bearer token lives only in this mounted view after make answers. Re-reading never reconstructs it. */
export function InviteLinks({
  client,
  team,
  allowed,
}: { client: TeamsClient; team: string; allowed: boolean }) {
  const [rows, setRows] = useState<InviteLinkRow[]>([]);
  const [share, setShare] = useState<MadeLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const read = useCallback(async () => {
    const answer = await client.listLinks(team);
    setShare(null);
    setRows(answer);
  }, [client, team]);
  useEffect(() => {
    if (!allowed) return;
    void read().catch(() => setMessage("Invite links are not available right now."));
  }, [allowed, read]);
  if (!allowed) return null;

  const make = async () => {
    setBusy(true);
    setMessage("");
    setShare(null);
    try {
      const made = await client.makeLink(team);
      await read();
      setShare(made);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const withdraw = async (id: string) => {
    setBusy(true);
    setMessage("");
    try {
      await client.revokeLink(team, id);
      await read();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  };
  const url = share ? `${window.location.origin}/join#${share.token}` : null;
  return (
    <section
      className="park-team-card"
      aria-label="Invite by link"
      style={{ padding: "16px", overflowWrap: "anywhere" }}
    >
      <h3 className="park-team-h2">Invite by link</h3>
      <Button variant="secondary" disabled={busy} onClick={() => void make()}>
        Make a link
      </Button>
      {url ? (
        <div>
          <p>
            Anyone with this link can join this team until it is used, withdrawn or expires (7
            days).
          </p>
          <p>Expires {new Date(share?.expires_at ?? "").toLocaleString()}</p>
          <code>{url}</code>{" "}
          <Button
            variant="secondary"
            onClick={() =>
              void navigator.clipboard
                ?.writeText(url)
                .catch(() => setMessage("Copy did not work. Select the link to copy it."))
            }
          >
            Copy
          </Button>
        </div>
      ) : null}
      <ul>
        {rows.map((row) => (
          <li key={row.id}>
            <span>
              {labels[row.state]} · {new Date(row.expires_at).toLocaleDateString()}
            </span>{" "}
            {row.state === "unused" ? (
              <Button variant="secondary" disabled={busy} onClick={() => void withdraw(row.id)}>
                Withdraw
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      <output>{message}</output>
    </section>
  );
}
