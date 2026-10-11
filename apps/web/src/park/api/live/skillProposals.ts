import type { SkillProposal } from "../types";

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
