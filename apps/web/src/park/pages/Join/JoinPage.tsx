import { useEffect, useState } from "react";
import type { TeamsClient } from "../../api/selfServeTeams";
import { teamsClient } from "../../api/selfServeTeams";
import type { AppCtx } from "../../app/AppCtx";
import { Button, PageSheet } from "../../components";
import { JOIN_TOKEN_KEY, captureJoinToken } from "./joinToken";

const UNAVAILABLE =
  "This invite link can't be used. It may have expired, been used or withdrawn, or you may already be in the team. Ask for a new link.";
const LIMIT = "You're already in 8 teams. Leave one, then open the link again.";
const DOWN = "Invite links are not available right now.";

export function JoinPage({ client: supplied }: { app?: AppCtx; client?: TeamsClient | null }) {
  captureJoinToken();
  const [client] = useState(() => (supplied === undefined ? teamsClient() : supplied));
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [team, setTeam] = useState<string | null>(null);
  useEffect(() => {
    if (!client) return;
    let active = true;
    void client.ensurePerson().then(
      () => {
        if (active) setReady(true);
      },
      () => {
        if (active) setMessage(DOWN);
      },
    );
    return () => {
      active = false;
    };
  }, [client]);
  const join = async () => {
    if (!client || !ready || busy) return;
    const token = sessionStorage.getItem(JOIN_TOKEN_KEY);
    if (!token) {
      setMessage(UNAVAILABLE);
      return;
    }
    setBusy(true);
    try {
      const result = await client.acceptLink(token);
      sessionStorage.removeItem(JOIN_TOKEN_KEY);
      const roster = await client.roster(result.team).catch(() => []);
      const lead = roster.find((person) => person.lead)?.name;
      setTeam(result.team);
      setMessage(lead ? `You joined ${lead}'s team` : "You joined the team");
    } catch (error) {
      const status = (error as { status?: number } | null)?.status;
      if (status !== 409) sessionStorage.removeItem(JOIN_TOKEN_KEY);
      setMessage(status === 404 ? UNAVAILABLE : status === 409 ? LIMIT : DOWN);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div data-testid="park-page-join">
      <PageSheet gap={22}>
        <section
          className="park-team-card"
          data-testid="join-card"
          style={{
            width: "100%",
            maxWidth: "390px",
            boxSizing: "border-box",
            padding: "20px",
            overflowWrap: "anywhere",
          }}
        >
          <h1>Join a team</h1>
          <p>You've been invited to join a team on Tilo.</p>
          {team ? (
            <a href="/team">Go to Team</a>
          ) : (
            <Button variant="primary" disabled={!ready || busy} onClick={() => void join()}>
              Join
            </Button>
          )}
          <output>{message}</output>
        </section>
      </PageSheet>
    </div>
  );
}
