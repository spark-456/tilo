import { type HttpClient, TiloApiError } from "../../../api/http";
import type { SkillProposal } from "../types";

export type ProposalClient = Pick<HttpClient, "getJson" | "postJson">;
const pathOf = (worldId: string) => `/worlds/${encodeURIComponent(worldId)}/skill-proposals`;

export async function readProposals(
  client: ProposalClient,
  worldId: string,
): Promise<SkillProposal[]> {
  const rows = proposalsFromList(await client.getJson(pathOf(worldId)), worldId);
  if (!rows) throw new TiloApiError("Could not read skill proposals.", 200, true);
  return rows;
}

export async function reviewProposal(
  client: ProposalClient,
  worldId: string,
  id: string,
  verb: "approve" | "reject",
): Promise<SkillProposal> {
  const body = await client.postJson(`${pathOf(worldId)}/${encodeURIComponent(id)}/${verb}`, {});
  const proposal = (body as { proposal?: unknown } | null)?.proposal;
  const done = proposalsFromList({ proposals: [proposal] }, worldId)?.[0];
  if (!done || done.id !== id || done.status !== (verb === "approve" ? "approved" : "rejected"))
    throw new TiloApiError("Could not read your review.", 200, true, true);
  return done;
}

const text = (v: unknown): v is string => typeof v === "string" && v.length > 0;
/** FR-AGT-15: the route's diff and status, never an inferred permission or a locally applied skill. */
export function proposalsFromList(body: unknown, worldId: string): SkillProposal[] | null {
  const rows = (body as { proposals?: unknown } | null)?.proposals;
  if (!Array.isArray(rows)) return null;
  const result: SkillProposal[] = [];
  for (const row of rows) {
    const p = row as SkillProposal | null;
    if (
      !p ||
      !text(p.id) ||
      !text(p.skill_id) ||
      !text(p.domain) ||
      !text(p.from_version) ||
      !text(p.to_version) ||
      typeof p.diff !== "string" ||
      !["proposed", "approved", "rejected"].includes(p.status) ||
      p.provenance?.world_id !== worldId ||
      !text(p.provenance.proposed_by) ||
      !text(p.provenance.proposed_at)
    )
      return null;
    result.push(p);
  }
  return result;
}
