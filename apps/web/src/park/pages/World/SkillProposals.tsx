import { useEffect, useRef, useState } from "react";
import { type HttpClient, TiloApiError } from "../../../api/http";
import { proposalsFromList } from "../../api/live/skillProposals";
import type { SkillProposal } from "../../api/types";

/** The server determines who may review; the page records success only from its response. */
export function SkillProposals({ client, worldId }: { client: HttpClient; worldId: string }) {
  const [rows, setRows] = useState<SkillProposal[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const writing = useRef(false);
  const path = `/worlds/${encodeURIComponent(worldId)}/skill-proposals`;
  useEffect(() => {
    generation.current++;
    writing.current = false;
    setBusy(false);
    // Retry reruns the same read, without adding a query parameter to the route.
    void attempt;
    let active = true;
    setRows(null);
    setError("");
    client
      .getJson(path)
      .then((body) => {
        const list = proposalsFromList(body, worldId);
        if (!list) throw new TiloApiError("Could not read skill proposals.", 200, true);
        if (active) setRows(list);
      })
      .catch(() => {
        if (active)
          setError("Skill proposals not available. You may need an expert Team Lead assignment.");
      });
    return () => {
      active = false;
      generation.current++;
    };
  }, [client, path, worldId, attempt]);
  const decide = async (p: SkillProposal, verb: "approve" | "reject") => {
    if (writing.current) return;
    writing.current = true;
    const current = generation.current;
    setBusy(true);
    setError("");
    try {
      const body = await client.postJson(`${path}/${encodeURIComponent(p.id)}/${verb}`, {});
      const proposal = (body as { proposal?: unknown } | null)?.proposal;
      const list = proposalsFromList({ proposals: [proposal] }, worldId);
      const done = list?.[0];
      if (
        !done ||
        done.id !== p.id ||
        done.status !== (verb === "approve" ? "approved" : "rejected")
      )
        throw new Error("Unreadable decision");
      if (current === generation.current)
        setRows((old) => old?.map((row) => (row.id === done.id ? done : row)) ?? null);
    } catch {
      if (current === generation.current)
        setError("Could not record your review. The proposal has not changed on this page.");
    } finally {
      if (current === generation.current) {
        writing.current = false;
        setBusy(false);
      }
    }
  };
  return (
    <section className="park-world-proposals" aria-label="Skill proposals">
      <h2>Skill proposals</h2>
      {error ? (
        <>
          <p role="alert">{error}</p>
          {rows === null ? (
            <button type="button" onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </button>
          ) : null}
        </>
      ) : null}
      {!error && rows === null ? <p>Loading skill proposals…</p> : null}
      {rows?.length === 0 ? <p>No skill proposals yet.</p> : null}
      {rows?.map((p) => (
        <article key={p.id}>
          <h3>
            {p.skill_id} · {p.from_version} → {p.to_version}
          </h3>
          <p>
            {p.domain} · {p.status} · Proposed by {p.provenance.proposed_by}
          </p>
          <pre>{p.diff}</pre>
          {p.status === "proposed" ? (
            <>
              <button type="button" disabled={busy} onClick={() => void decide(p, "approve")}>
                Accept
              </button>
              <button type="button" disabled={busy} onClick={() => void decide(p, "reject")}>
                Decline
              </button>
            </>
          ) : null}
        </article>
      ))}
    </section>
  );
}
